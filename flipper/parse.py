"""Turn raw listing text (title / subtitle / price) into structured vehicle fields."""
from __future__ import annotations

import re

MAKES = {
    "acura": "acura", "alfa": "alfa romeo", "audi": "audi", "bmw": "bmw", "buick": "buick",
    "cadillac": "cadillac", "chevrolet": "chevrolet", "chevy": "chevrolet", "chrysler": "chrysler",
    "dodge": "dodge", "fiat": "fiat", "ford": "ford", "genesis": "genesis", "gmc": "gmc",
    "honda": "honda", "hyundai": "hyundai", "infiniti": "infiniti", "jaguar": "jaguar",
    "jeep": "jeep", "kia": "kia", "land": "land rover", "lexus": "lexus", "lincoln": "lincoln",
    "mazda": "mazda", "mercedes": "mercedes-benz", "mercedes-benz": "mercedes-benz",
    "benz": "mercedes-benz", "mini": "mini", "mitsubishi": "mitsubishi", "nissan": "nissan",
    "pontiac": "pontiac", "porsche": "porsche", "ram": "ram", "saturn": "saturn",
    "scion": "scion", "subaru": "subaru", "suzuki": "suzuki", "tesla": "tesla",
    "toyota": "toyota", "volkswagen": "volkswagen", "vw": "volkswagen", "volvo": "volvo",
}
# Words that follow a make but aren't the model ("Land Rover", "Alfa Romeo").
_SKIP_AFTER_MAKE = {"rover", "romeo", "benz"}

_YEAR_RE = re.compile(r"\b(19[5-9]\d|20[0-4]\d)\b")
_MILES_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(k)?\s*(miles|mi|km)\b", re.I)
_PRICE_RE = re.compile(r"[\d,]+(?:\.\d+)?")


def parse_price(text: str | None) -> float | None:
    """'$4,500' -> 4500.0. 'Free' / None -> None."""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text)
    m = _PRICE_RE.search(str(text).replace(" ", ""))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def parse_mileage(text: str | None) -> int | None:
    """'120K miles' -> 120000, '85,000 mi' -> 85000, '150K km' -> ~93206 (converted to miles)."""
    if not text:
        return None
    m = _MILES_RE.search(text)
    if not m:
        return None
    num = float(m.group(1).replace(",", ""))
    if m.group(2):
        num *= 1000
    if m.group(3).lower() == "km":
        num *= 0.621371
    return int(round(num))


def parse_title(title: str | None) -> dict:
    """'2012 Honda Civic LX Sedan' -> {'year': 2012, 'make': 'honda', 'model': 'civic'}."""
    out = {"year": None, "make": None, "model": None}
    if not title:
        return out
    m = _YEAR_RE.search(title)
    if m:
        out["year"] = int(m.group(1))
    tokens = re.findall(r"[A-Za-z0-9\-]+", title.lower())
    for i, tok in enumerate(tokens):
        if tok in MAKES:
            out["make"] = MAKES[tok]
            rest = [t for t in tokens[i + 1:] if t not in _SKIP_AFTER_MAKE and not _YEAR_RE.fullmatch(t)]
            if rest:
                out["model"] = rest[0]
            break
    return out
