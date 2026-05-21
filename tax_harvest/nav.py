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
# cwd-relative — keeps the project self-contained; gitignored at repo root.
DEFAULT_CACHE_DIR = Path("cache")
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

    # Column layouts of the two AMFI feeds we consume. Indexes are positional
    # offsets into a `;`-split row. The daily NAVAll.txt feed places the scheme
    # name AFTER the two ISINs; the historical DownloadNAVHistoryReport feed
    # places the name BEFORE the ISINs and adds Repurchase + Sale columns.
    _LAYOUT_DAILY = {"code": 0, "isin_g": 1, "isin_r": 2, "name": 3, "nav": 4, "date": 5, "min_cols": 6}
    _LAYOUT_HISTORICAL = {"code": 0, "name": 1, "isin_g": 2, "isin_r": 3, "nav": 4, "date": 7, "min_cols": 8}

    @classmethod
    def from_text(cls, text: str) -> "NavIndex":
        """Parse the daily NAVAll.txt feed (6-column layout)."""
        return cls._parse(text, cls._LAYOUT_DAILY)

    @classmethod
    def from_historical_text(cls, text: str) -> "NavIndex":
        """Parse the DownloadNAVHistoryReport feed (8-column layout with Repurchase + Sale)."""
        return cls._parse(text, cls._LAYOUT_HISTORICAL)

    @classmethod
    def _parse(cls, text: str, layout: dict[str, int]) -> "NavIndex":
        idx = cls()
        date_counts: dict[str, int] = {}
        for line in text.splitlines():
            line = line.strip()
            if not line or ";" not in line:
                continue
            parts = [p.strip() for p in line.split(";")]
            if len(parts) < layout["min_cols"] or not parts[layout["code"]].isdigit():
                continue
            code = parts[layout["code"]]
            isin_g = parts[layout["isin_g"]]
            isin_r = parts[layout["isin_r"]]
            name = parts[layout["name"]]
            nav_str = parts[layout["nav"]]
            date_str = parts[layout["date"]]
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
            date_counts[date_str] = date_counts.get(date_str, 0) + 1
        # Snapshot date = most common date across all rows. The AMFI feed mixes in
        # stale dates from interval / FMP / wound-up schemes; using the last-seen
        # date misreports the freshness of the actively-traded universe.
        if date_counts:
            idx.snapshot_date = max(date_counts.items(), key=lambda kv: kv[1])[0]
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
        # Treat a zero-byte cache as stale — happens if a prior run crashed mid-write
        # (e.g. encoding error) and left an empty file behind. Without this, every
        # subsequent run within the 24h window silently returns zero NAVs.
        if cache_file.stat().st_size == 0:
            needs_fetch = True
        else:
            age = time.time() - cache_file.stat().st_mtime
            needs_fetch = age > max_age_sec
    if needs_fetch:
        try:
            resp = requests.get(AMFI_URL, timeout=timeout)
            resp.raise_for_status()
            cache_file.write_text(resp.text, encoding="utf-8")
        except requests.RequestException as exc:
            if not cache_file.exists():
                raise RuntimeError(f"AMFI NAV fetch failed and no cache present: {exc}") from exc
            # Use stale cache, but warn caller via the snapshot_date.
    text = cache_file.read_text(encoding="utf-8")
    return NavIndex.from_text(text)
