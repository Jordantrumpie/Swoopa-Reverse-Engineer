import json
import tempfile
import unittest
from pathlib import Path

from flipper.db import DB
from flipper.extract import extract_listings, iter_html_json, iter_json_docs
from flipper.fb import build_url
from flipper.parse import parse_mileage, parse_price, parse_title
from flipper.scoring import evaluate


def node(lid, title, price, sub="", city="Austin", state="TX"):
    return {"__typename": "GroupCommerceProductItem", "id": lid, "marketplace_listing_title": title,
            "listing_price": {"formatted_amount": f"${price:,}", "amount": f"{price}.00"},
            "custom_sub_titles_with_rendering_flags": [{"subtitle": sub}],
            "location": {"reverse_geocode": {"city": city, "state": state}},
            "primary_listing_photo": {"image": {"uri": f"https://img/{lid}.jpg"}},
            "is_sold": False, "is_pending": False}


GRAPHQL = {"data": {"marketplace_search": {"feed_units": {"edges": [
    {"node": {"listing": node("111", "2012 Honda Civic LX", 4500, "120K miles")}},
    {"node": {"listing": node("222", "2015 Chevy Silverado 1500", 14900, "98,000 miles")}},
]}}}}


class ParseTests(unittest.TestCase):
    def test_title(self):
        self.assertEqual(parse_title("2012 Honda Civic LX Sedan"), {"year": 2012, "make": "honda", "model": "civic"})
        self.assertEqual(parse_title("2016 Land Rover Range Rover")["model"], "range")
        self.assertEqual(parse_title("Chevy Tahoe 2008")["make"], "chevrolet")
        self.assertEqual(parse_title("Couch, barely used"), {"year": None, "make": None, "model": None})

    def test_mileage_price(self):
        self.assertEqual(parse_mileage("120K miles"), 120000)
        self.assertEqual(parse_mileage("Dealership · 85,000 mi"), 85000)
        self.assertEqual(parse_mileage("100K km"), 62137)
        self.assertEqual(parse_price("$4,500"), 4500)
        self.assertIsNone(parse_price("Free"))


class ExtractTests(unittest.TestCase):
    def test_graphql_multi_doc(self):
        body = "for (;;);" + json.dumps(GRAPHQL) + "\n" + json.dumps({"extensions": {}})
        items = extract_listings(list(iter_json_docs(body)))
        by_id = {i["id"]: i for i in items}
        self.assertEqual(by_id["111"]["price"], 4500)
        self.assertEqual(by_id["111"]["mileage"], 120000)
        self.assertEqual(by_id["222"]["make"], "chevrolet")
        self.assertEqual(by_id["111"]["location"], "Austin, TX")
        self.assertTrue(by_id["111"]["url"].endswith("/item/111/"))

    def test_html_embedded(self):
        html = ('<html><script type="application/json" data-sjs>' + json.dumps({"require": [[GRAPHQL]]})
                + '</script><script type="application/json">{"x":1}</script></html>')
        self.assertEqual(len(extract_listings(list(iter_html_json(html)))), 2)


class UrlTests(unittest.TestCase):
    def test_build(self):
        u = build_url({"location": "austin", "max_price": 5000, "max_miles": 150000})
        self.assertIn("/marketplace/austin/vehicles?", u)
        self.assertIn("sortBy=creation_time_descend", u)
        self.assertIn("maxMileage=150000", u)
        self.assertIn("/search?", build_url({"location": "austin", "query": "tacoma"}))
        self.assertIn("sortBy=", build_url({"url": "https://www.facebook.com/marketplace/x/vehicles?maxPrice=1"}))


class ScoringTests(unittest.TestCase):
    cfg = {"targets": [{"make": "honda", "model": "civic", "max_price": 6000}],
           "alerts": {"min_comps": 3, "min_discount": 0.2}}

    def item(self, **kw):
        base = {"id": "1", "title": "2012 Honda Civic", "subtitle": "", "price": 4500, "mileage": 120000,
                "year": 2012, "make": "honda", "model": "civic"}
        base.update(kw)
        return base

    def test_target(self):
        self.assertTrue(evaluate(self.item(), [], self.cfg).alert)
        self.assertFalse(evaluate(self.item(price=7000), [], self.cfg).alert)

    def test_comps(self):
        v = evaluate(self.item(make="toyota", model="corolla", price=5000), [8000, 8500, 9000], self.cfg)
        self.assertTrue(v.alert)
        self.assertEqual(v.median, 8500)

    def test_red_flag_and_placeholder(self):
        self.assertFalse(evaluate(self.item(title="2012 Honda Civic salvage title"), [], self.cfg).alert)
        self.assertFalse(evaluate(self.item(price=1), [], self.cfg).alert)

    def test_target_needs_year(self):
        self.assertFalse(evaluate(self.item(title="Honda EU2200i generator", year=None, model="eu2200i"),
                                  [], self.cfg).alert)

    def test_price_drop(self):
        v = evaluate(self.item(make="ford", model="focus", price=4000), [], self.cfg, price_drop_from=5000)
        self.assertTrue(v.alert)


class DBTests(unittest.TestCase):
    def test_upsert_and_comps(self):
        with tempfile.TemporaryDirectory() as d:
            db = DB(Path(d) / "x.db")
            items = extract_listings([GRAPHQL])
            for it in items:
                self.assertEqual(db.upsert("s", it), (True, None))
            civic = next(i for i in items if i["id"] == "111")
            self.assertEqual(db.upsert("s", civic), (False, None))
            self.assertEqual(db.upsert("s", {**civic, "price": 3900}), (False, 4500))
            self.assertEqual(db.comps("chevrolet", "silverado", 2014, "999"), [14900])


class SeedTests(unittest.TestCase):
    def test_empty_pass_does_not_seed(self):
        from flipper.__main__ import process
        from flipper.notify import Notifier
        with tempfile.TemporaryDirectory() as d:
            db = DB(Path(d) / "x.db")
            process(db, Notifier({}), {}, {"name": "s"}, [])
            self.assertFalse(db.is_seeded("s"))
            process(db, Notifier({}), {}, {"name": "s"}, extract_listings([GRAPHQL]))
            self.assertTrue(db.is_seeded("s"))

    def test_old_db_empty_seed_is_redone(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "old.db"
            c = sqlite3.connect(path)
            c.executescript("CREATE TABLE searches (name TEXT PRIMARY KEY, seeded_at REAL);"
                            "INSERT INTO searches VALUES ('honda', 1), ('main', 1);"
                            "CREATE TABLE listings (id TEXT PRIMARY KEY, search TEXT, title TEXT, price REAL,"
                            " mileage INTEGER, subtitle TEXT, location TEXT, year INTEGER, make TEXT, model TEXT,"
                            " url TEXT, photo TEXT, first_seen REAL, last_seen REAL, first_price REAL,"
                            " alerted INTEGER DEFAULT 0);"
                            "INSERT INTO listings (id, search) VALUES ('1', 'main');")
            c.commit(); c.close()
            db = DB(path)
            self.assertFalse(db.is_seeded("honda"))
            self.assertTrue(db.is_seeded("main"))


if __name__ == "__main__":
    unittest.main()
