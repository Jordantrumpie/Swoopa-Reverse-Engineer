"""Drive a real Chromium session (your logged-in Facebook profile) to load Marketplace searches."""
from __future__ import annotations

import logging
import random
import urllib.parse
from pathlib import Path

from .extract import extract_listings, iter_html_json, iter_json_docs

log = logging.getLogger(__name__)

BASE = "https://www.facebook.com/marketplace"


def build_url(s: dict) -> str:
    """Build a Marketplace URL from a search block, or use its raw `url`.

    Always forces newest-first sorting: being first to message is the whole game.
    """
    if s.get("url"):
        url = s["url"]
        if "sortBy=" not in url:
            url += ("&" if "?" in url else "?") + "sortBy=creation_time_descend"
        return url
    location = s.get("location", "")
    params = {"sortBy": "creation_time_descend", "exact": "false"}
    for key, fb_key in [("min_price", "minPrice"), ("max_price", "maxPrice"), ("max_miles", "maxMileage"),
                        ("min_miles", "minMileage"), ("min_year", "minYear"), ("max_year", "maxYear"),
                        ("days_since_listed", "daysSinceListed"), ("radius_km", "radius")]:
        if s.get(key) is not None:
            params[fb_key] = s[key]
    if s.get("query"):
        params["query"] = s["query"]
        path = f"{BASE}/{location}/search" if location else f"{BASE}/search"
    else:
        path = f"{BASE}/{location}/vehicles" if location else f"{BASE}/category/vehicles"
    return f"{path}?{urllib.parse.urlencode(params)}"


class Browser:
    def __init__(self, profile_dir: str | Path, headless: bool = True):
        from playwright.sync_api import sync_playwright  # imported lazily so tests don't need it
        self._pw = sync_playwright().start()
        self.ctx = self._pw.chromium.launch_persistent_context(
            str(profile_dir), headless=headless, viewport={"width": 1280, "height": 900},
            locale="en-US")
        self.page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()

    def close(self):
        try:
            self.ctx.close()
        finally:
            self._pw.stop()

    def login(self):
        self.page.goto("https://www.facebook.com/")
        input("Log in to Facebook in the browser window, then press Enter here to save the session... ")

    def _content(self) -> str:
        for _ in range(4):
            try:
                return self.page.content()
            except Exception:  # "page is navigating" - give it a moment
                self.page.wait_for_timeout(1500)
        return self.page.content()

    def fetch(self, url: str, scrolls: int = 1) -> list[dict]:
        captured = []

        def on_response(r):
            if "/api/graphql" in r.url:
                captured.append(r)

        self.page.on("response", on_response)
        try:
            self.page.goto(url, wait_until="domcontentloaded", timeout=45000)
            # Search pages redirect while loading; wait for the page to settle and listings to appear.
            for wait in (lambda: self.page.wait_for_load_state("load", timeout=15000),
                         lambda: self.page.wait_for_selector('a[href*="/marketplace/item/"]', timeout=15000)):
                try:
                    wait()
                except Exception:
                    pass
            self.page.wait_for_timeout(random.randint(1500, 3000))
            for _ in range(scrolls):
                self.page.mouse.wheel(0, random.randint(1800, 2600))
                self.page.wait_for_timeout(random.randint(1200, 2200))
            docs = list(iter_html_json(self._content()))
            for r in captured:
                try:
                    body = r.text()
                except Exception:
                    continue
                if "marketplace_listing_title" in body:
                    docs.extend(iter_json_docs(body))
        finally:
            self.page.remove_listener("response", on_response)

        items = extract_listings(docs)
        if not items and "login" in self.page.url:
            log.warning("Redirected to login — run `python -m flipper login` again.")
        return items
