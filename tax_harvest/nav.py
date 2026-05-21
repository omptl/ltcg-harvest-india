"""AMFI NAV fetch and lookup.

Source: https://www.amfiindia.com/spages/NAVAll.txt — a pipe-delimited daily snapshot
of every scheme's NAV. We cache the file locally and refresh if older than 24h.

Format (one section per AMC):
    Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Net Asset Value;Date
"""

from __future__ import annotations

import re
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests

from .models import Scheme

AMFI_URL = "https://www.amfiindia.com/spages/NAVAll.txt"
DEFAULT_CACHE_DIR = Path.home() / ".tax_harvest"
DEFAULT_CACHE_FILE = DEFAULT_CACHE_DIR / "nav_cache.txt"
CACHE_MAX_AGE_SEC = 24 * 60 * 60


class NavIndex:
    """In-memory lookup keyed by ISIN, AMFI scheme code, and normalized scheme name."""

    def __init__(self) -> None:
        self.by_isin: dict[str, float] = {}
        self.by_code: dict[str, float] = {}
        self.by_name: dict[str, float] = {}
        self.snapshot_date: Optional[str] = None
        self.unmatched: list[str] = []  # populated by callers

    @classmethod
    def from_text(cls, text: str) -> "NavIndex":
        idx = cls()
        for line in text.splitlines():
            line = line.strip()
            if not line or ";" not in line:
                continue
            parts = line.split(";")
            if len(parts) < 6 or not parts[0].strip().isdigit():
                continue
            code, isin_g, isin_r, name, nav_str, date_str = (p.strip() for p in parts[:6])
            try:
                nav = float(nav_str)
            except ValueError:
                continue
            if nav <= 0:
                continue
            idx.by_code[code] = nav
            for isin in (isin_g, isin_r):
                if isin and isin != "-":
                    idx.by_isin[isin] = nav
            idx.by_name[_normalize(name)] = nav
            idx.snapshot_date = date_str
        return idx

    def lookup(self, scheme: Scheme) -> Optional[float]:
        if scheme.isin and scheme.isin in self.by_isin:
            return self.by_isin[scheme.isin]
        if scheme.scheme_code and scheme.scheme_code in self.by_code:
            return self.by_code[scheme.scheme_code]
        norm = _normalize(scheme.scheme_name)
        if norm in self.by_name:
            return self.by_name[norm]
        # Fallback: prefix match on normalized name (handles trailing "- Growth" variants)
        for key, nav in self.by_name.items():
            if key.startswith(norm) or norm.startswith(key):
                if abs(len(key) - len(norm)) <= 12:
                    return nav
        self.unmatched.append(scheme.scheme_name)
        return None


def _normalize(name: str) -> str:
    """Lowercase, collapse whitespace, strip punctuation noise for fuzzy name match."""
    s = name.lower()
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def load_nav_index(cache_file: Path = DEFAULT_CACHE_FILE,
                   max_age_sec: int = CACHE_MAX_AGE_SEC,
                   force_refresh: bool = False,
                   timeout: int = 30) -> NavIndex:
    """Return a NavIndex, refreshing the cache from AMFI if stale or missing."""
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    needs_fetch = force_refresh or not cache_file.exists()
    if not needs_fetch:
        age = time.time() - cache_file.stat().st_mtime
        needs_fetch = age > max_age_sec
    if needs_fetch:
        try:
            resp = requests.get(AMFI_URL, timeout=timeout)
            resp.raise_for_status()
            cache_file.write_text(resp.text)
        except requests.RequestException as exc:
            if not cache_file.exists():
                raise RuntimeError(f"AMFI NAV fetch failed and no cache present: {exc}") from exc
            # Use stale cache, but warn caller via the snapshot_date.
    text = cache_file.read_text()
    return NavIndex.from_text(text)
