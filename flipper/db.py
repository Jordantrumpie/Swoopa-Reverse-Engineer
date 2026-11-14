"""SQLite store: dedupes listings and doubles as your own price-comp database."""
from __future__ import annotations

import sqlite3
import statistics
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    id TEXT PRIMARY KEY,
    search TEXT,
    title TEXT, price REAL, mileage INTEGER, subtitle TEXT, location TEXT,
    year INTEGER, make TEXT, model TEXT,
    url TEXT, photo TEXT,
    first_seen REAL, last_seen REAL,
    first_price REAL,
    alerted INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_mm ON listings(make, model, year);
CREATE TABLE IF NOT EXISTS searches (name TEXT PRIMARY KEY, seeded_at REAL);
"""


class DB:
    def __init__(self, path: str | Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        cols = [r["name"] for r in self.conn.execute("PRAGMA table_info(searches)")]
        if "n" not in cols:
            # Older DBs could mark a search seeded after a failed (empty) pass; redo those.
            self.conn.execute("ALTER TABLE searches ADD COLUMN n INTEGER")
            self.conn.execute("DELETE FROM searches WHERE name NOT IN (SELECT DISTINCT search FROM listings)")
            self.conn.commit()

    def is_seeded(self, search: str) -> bool:
        return self.conn.execute("SELECT 1 FROM searches WHERE name=?", (search,)).fetchone() is not None

    def mark_seeded(self, search: str, n: int = 0) -> None:
        self.conn.execute("INSERT OR IGNORE INTO searches (name, seeded_at, n) VALUES (?, ?, ?)",
                          (search, time.time(), n))
        self.conn.commit()

    def upsert(self, search: str, item: dict) -> tuple[bool, float | None]:
        """Returns (is_new, previous_price). previous_price is set when a known listing changed price."""
        now = time.time()
        row = self.conn.execute("SELECT price FROM listings WHERE id=?", (item["id"],)).fetchone()
        if row is None:
            self.conn.execute(
                "INSERT INTO listings (id, search, title, price, mileage, subtitle, location, year, make, model,"
                " url, photo, first_seen, last_seen, first_price) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (item["id"], search, item["title"], item["price"], item["mileage"], item["subtitle"],
                 item["location"], item["year"], item["make"], item["model"], item["url"], item["photo"],
                 now, now, item["price"]))
            self.conn.commit()
            return True, None
        prev = row["price"]
        self.conn.execute("UPDATE listings SET price=?, last_seen=?, mileage=COALESCE(?, mileage) WHERE id=?",
                          (item["price"], now, item["mileage"], item["id"]))
        self.conn.commit()
        changed = prev is not None and item["price"] is not None and item["price"] != prev
        return False, (prev if changed else None)

    def mark_alerted(self, lid: str) -> None:
        self.conn.execute("UPDATE listings SET alerted=1 WHERE id=?", (lid,))
        self.conn.commit()

    def comps(self, make: str, model: str, year: int | None, exclude_id: str,
              year_window: int = 2, days: int = 90, min_price: float = 500) -> list[float]:
        q = ("SELECT price FROM listings WHERE make=? AND model=? AND id!=? AND price>=? AND last_seen>=?")
        args: list = [make, model, exclude_id, min_price, time.time() - days * 86400]
        if year:
            q += " AND year BETWEEN ? AND ?"
            args += [year - year_window, year + year_window]
        return [r["price"] for r in self.conn.execute(q, args)]

    def comp_summary(self, min_count: int = 3) -> list[dict]:
        rows = self.conn.execute(
            "SELECT make, model, GROUP_CONCAT(price) AS prices, COUNT(*) AS n FROM listings "
            "WHERE make IS NOT NULL AND model IS NOT NULL AND price >= 500 "
            "GROUP BY make, model HAVING n >= ? ORDER BY n DESC", (min_count,)).fetchall()
        out = []
        for r in rows:
            prices = [float(p) for p in r["prices"].split(",")]
            out.append({"make": r["make"], "model": r["model"], "n": r["n"],
                        "median": statistics.median(prices), "low": min(prices), "high": max(prices)})
        return out
