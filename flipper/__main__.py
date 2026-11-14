"""CLI:  python -m flipper {login|run|once|comps|test-alert} [-c config.yaml]"""
from __future__ import annotations

import argparse
import logging
import random
import time
from pathlib import Path

import yaml

from .db import DB
from .notify import Notifier
from .scoring import Verdict, evaluate

log = logging.getLogger("flipper")


def load_config(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    cfg.setdefault("data_dir", "data")
    cfg.setdefault("searches", [])
    return cfg


def process(db: DB, notifier: Notifier, cfg: dict, s: dict, items: list[dict]) -> int:
    name = s["name"]
    seeding = not db.is_seeded(name)
    alerts = 0
    new = 0
    for item in items:
        is_new, prev_price = db.upsert(name, item)
        new += is_new
        if seeding or (not is_new and prev_price is None):
            continue
        comps = db.comps(item["make"], item["model"], item["year"], item["id"]) if item["make"] and item["model"] else []
        v = evaluate(item, comps, cfg, s, price_drop_from=prev_price)
        if v.alert:
            notifier.send(item, v)
            db.mark_alerted(item["id"])
            alerts += 1
    if seeding and not items:
        log.warning("[%s] found 0 listings - will try again next pass", name)
    elif seeding:
        db.mark_seeded(name, len(items))
        log.info("[%s] seeded with %d listings (no alerts on first pass)", name, len(items))
    else:
        log.info("[%s] %d listings, %d new, %d alerts", name, len(items), new, alerts)
    return alerts


def run(cfg: dict, loop: bool, headless: bool) -> None:
    from .fb import Browser, build_url
    data = Path(cfg["data_dir"])
    db = DB(data / "listings.db")
    notifier = Notifier(cfg.get("notify", {}))
    browser = Browser(data / "browser-profile", headless=headless)
    interval = cfg.get("interval_seconds", 90)
    try:
        while True:
            for s in cfg["searches"]:
                if s.get("enabled", True) is False:
                    continue
                url = build_url(s)
                try:
                    items = browser.fetch(url, scrolls=s.get("scrolls", 1))
                    process(db, notifier, cfg, s, items)
                except Exception as e:
                    log.warning("[%s] fetch failed: %s", s["name"], e)
                time.sleep(random.uniform(3, 8))
            if not loop:
                break
            hour = time.localtime().tm_hour
            quiet = cfg.get("quiet_hours")  # e.g. [1, 6] -> sleep longer 1am-6am
            wait = interval * (4 if quiet and quiet[0] <= hour < quiet[1] else 1)
            time.sleep(wait * random.uniform(0.75, 1.35))
    except KeyboardInterrupt:
        pass
    finally:
        browser.close()


def main() -> None:
    ap = argparse.ArgumentParser(prog="flipper")
    ap.add_argument("command", choices=["login", "run", "once", "comps", "test-alert"])
    ap.add_argument("-c", "--config", default="config.yaml")
    ap.add_argument("--show", action="store_true", help="show the browser window")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    cfg = load_config(args.config)

    if args.command == "login":
        from .fb import Browser
        b = Browser(Path(cfg["data_dir"]) / "browser-profile", headless=False)
        try:
            b.login()
        finally:
            b.close()
    elif args.command in ("run", "once"):
        run(cfg, loop=args.command == "run", headless=not args.show)
    elif args.command == "comps":
        for r in DB(Path(cfg["data_dir"]) / "listings.db").comp_summary():
            print(f"{r['make']:>14} {r['model']:<14} n={r['n']:<4} median=${r['median']:>8,.0f}"
                  f"  range=${r['low']:,.0f}-${r['high']:,.0f}")
    elif args.command == "test-alert":
        item = {"id": "0", "title": "2012 Honda Civic LX (test alert)", "price": 4200, "mileage": 118000,
                "location": "Test City", "url": "https://www.facebook.com/marketplace/", "photo": None}
        Notifier(cfg.get("notify", {})).send(item, Verdict(alert=True, reasons=["this is a test"]))


if __name__ == "__main__":
    main()
