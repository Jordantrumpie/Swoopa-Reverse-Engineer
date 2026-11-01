"""Pull listing objects out of whatever Facebook hands the browser.

Marketplace delivers listings two ways:
  1. JSON blobs embedded in the initial HTML (<script type="application/json">).
  2. GraphQL XHR responses (/api/graphql/) as you scroll.

Rather than hard-coding a brittle path through Facebook's response shape (which
changes often), we walk every JSON value and pick out any dict that looks like a
listing: it has an `id` and a `marketplace_listing_title`.
"""
from __future__ import annotations

import json
import re
from typing import Any, Iterator

from .parse import parse_mileage, parse_price, parse_title

_SCRIPT_JSON_RE = re.compile(r'<script[^>]*type="application/json"[^>]*>(.*?)</script>', re.S)


def iter_json_docs(text: str) -> Iterator[Any]:
    """Facebook responses may be prefixed with 'for (;;);' and hold several
    newline-separated JSON documents."""
    text = text.strip()
    if text.startswith("for (;;);"):
        text = text[len("for (;;);"):]
    try:
        yield json.loads(text)
        return
    except ValueError:
        pass
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("{") or line.startswith("["):
            try:
                yield json.loads(line)
            except ValueError:
                continue


def iter_html_json(html: str) -> Iterator[Any]:
    for body in _SCRIPT_JSON_RE.findall(html):
        if "marketplace_listing_title" not in body:
            continue
        yield from iter_json_docs(body)


def _walk(obj: Any) -> Iterator[dict]:
    stack = [obj]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            if "marketplace_listing_title" in cur and "id" in cur:
                yield cur
            stack.extend(cur.values())
        elif isinstance(cur, list):
            stack.extend(cur)


def _get(d: Any, *path, default=None):
    for p in path:
        if isinstance(d, dict):
            d = d.get(p)
        elif isinstance(d, list) and isinstance(p, int) and -len(d) <= p < len(d):
            d = d[p]
        else:
            return default
        if d is None:
            return default
    return d


def normalize(raw: dict) -> dict | None:
    lid = str(raw.get("id") or "")
    if not lid.isdigit():
        return None
    title = raw.get("custom_title") or raw.get("marketplace_listing_title") or ""
    price = parse_price(_get(raw, "listing_price", "amount")) \
        or parse_price(_get(raw, "listing_price", "formatted_amount"))
    subtitles = [s.get("subtitle", "") for s in (raw.get("custom_sub_titles_with_rendering_flags") or [])
                 if isinstance(s, dict)]
    subtitle = " · ".join(s for s in subtitles if s)
    geo = _get(raw, "location", "reverse_geocode") or {}
    city = ", ".join(x for x in (geo.get("city"), geo.get("state")) if x)
    info = parse_title(title)
    return {
        "id": lid,
        "title": title.strip(),
        "price": price,
        "mileage": parse_mileage(subtitle),
        "subtitle": subtitle,
        "location": city,
        "photo": _get(raw, "primary_listing_photo", "image", "uri")
                 or _get(raw, "primary_listing_photo", "listing_image", "uri"),
        "url": f"https://www.facebook.com/marketplace/item/{lid}/",
        "is_sold": bool(raw.get("is_sold")),
        "is_pending": bool(raw.get("is_pending")),
        **info,
    }


def extract_listings(docs: list[Any]) -> list[dict]:
    seen: dict[str, dict] = {}
    for doc in docs:
        for raw in _walk(doc):
            item = normalize(raw)
            if not item:
                continue
            # Keep the richest version if a listing shows up more than once.
            prev = seen.get(item["id"])
            if prev is None or sum(v is not None for v in item.values()) > sum(v is not None for v in prev.values()):
                seen[item["id"]] = item
    return list(seen.values())
