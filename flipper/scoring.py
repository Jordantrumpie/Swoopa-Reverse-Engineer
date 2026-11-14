"""Decide whether a listing is worth pinging you about."""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field

DEFAULT_RED_FLAGS = ["salvage", "rebuilt", "parts only", "for parts", "no title", "lien", "bonded title",
                     "blown", "won't start", "wont start", "not running", "flood", "trade only", "down payment",
                     "financing", "buy here pay here", "no credit", "dealer"]
DEFAULT_MOTIVATED = ["must sell", "need gone", "moving", "obo", "cash only", "price drop", "reduced",
                     "first come", "quick sale", "needs work", "mechanic special", "as is", "as-is"]


@dataclass
class Verdict:
    alert: bool
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    median: float | None = None
    n_comps: int = 0


def _matches_target(item: dict, t: dict) -> bool:
    # Car listings put the year in the title; this skips Honda generators, Toyota parts, etc.
    if item.get("year") is None:
        return False
    if t.get("make") and item.get("make") != t["make"].lower():
        return False
    if t.get("model") and item.get("model") != t["model"].lower():
        return False
    y = item.get("year")
    if t.get("year_min") and (y is None or y < t["year_min"]):
        return False
    if t.get("year_max") and (y is None or y > t["year_max"]):
        return False
    if t.get("max_miles") and item.get("mileage") and item["mileage"] > t["max_miles"]:
        return False
    if t.get("max_price") and (item.get("price") is None or item["price"] > t["max_price"]):
        return False
    return True


def evaluate(item: dict, comps: list[float], cfg: dict, search_cfg: dict | None = None,
             price_drop_from: float | None = None) -> Verdict:
    search_cfg = search_cfg or {}
    acfg = cfg.get("alerts", {})
    text = f"{item.get('title', '')} {item.get('subtitle', '')}".lower()
    v = Verdict(alert=False)

    if item.get("is_sold") or item.get("is_pending"):
        return v
    price = item.get("price")
    if price is not None and price < acfg.get("min_price", 500):
        return v  # $1 "message me" placeholder prices, down-payment scams

    red_flags = acfg.get("red_flags", DEFAULT_RED_FLAGS)
    v.flags = [w for w in red_flags if w in text]
    if v.flags and acfg.get("skip_red_flags", True):
        return v

    for kw in search_cfg.get("exclude", []):
        if kw.lower() in text:
            return v

    if search_cfg.get("max_miles") and item.get("mileage") and item["mileage"] > search_cfg["max_miles"]:
        return v

    # 1) Explicit buy targets.
    for t in cfg.get("targets", []):
        if _matches_target(item, t):
            v.alert = True
            v.score += 50
            v.reasons.append(f"target: {t.get('name') or (t.get('make', '') + ' ' + t.get('model', '')).strip()}")
            break

    # 2) Under market vs. your own comp database.
    min_comps = acfg.get("min_comps", 5)
    if price and len(comps) >= min_comps:
        med = statistics.median(comps)
        v.median, v.n_comps = med, len(comps)
        discount = 1 - price / med
        v.score += max(0.0, discount) * 100
        if discount >= acfg.get("min_discount", 0.2):
            v.alert = True
            v.reasons.append(f"{discount:.0%} under median ${med:,.0f} ({len(comps)} comps)")

    # 3) Price drop on a listing we've already seen.
    if price_drop_from and price and price < price_drop_from:
        drop = 1 - price / price_drop_from
        if drop >= acfg.get("min_price_drop", 0.1):
            v.alert = True
            v.score += drop * 50
            v.reasons.append(f"price drop ${price_drop_from:,.0f} -> ${price:,.0f}")

    # 4) Searches flagged alert_all: every new hit pings you (fastest-to-message mode).
    if search_cfg.get("alert_all") and price_drop_from is None:
        v.alert = True
        v.reasons.append("new listing")

    motivated = [w for w in acfg.get("motivated", DEFAULT_MOTIVATED) if w in text]
    if motivated:
        v.score += 5 * len(motivated)
        v.reasons.append("motivated: " + ", ".join(motivated))
    return v
