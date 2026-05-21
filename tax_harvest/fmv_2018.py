"""Fair-Market-Value lookup for 31-Jan-2018 (Section 112A grandfathering).

For equity-oriented mutual fund units acquired on or before 31-Jan-2018, the cost
of acquisition for LTCG purposes is:

    effective_COA = max(actual_COA, min(FMV_31_Jan_2018, sale_value))

We pull the historical NAV snapshot for 31-Jan-2018 from AMFI's
DownloadNAVHistoryReport endpoint, which returns the same pipe-delimited format
as the daily NAVAll.txt feed. We cache it permanently — Jan 2018 NAVs don't
change.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import requests

from .models import Scheme
from .nav import NavIndex, _normalize

FMV_URL = (
    "https://portal.amfiindia.com/DownloadNAVHistoryReport_Po.aspx"
    "?frmdt=31-Jan-2018&todt=31-Jan-2018"
)
# cwd-relative — keeps the project self-contained; gitignored at repo root.
DEFAULT_CACHE_DIR = Path("cache")
DEFAULT_CACHE_FILE = DEFAULT_CACHE_DIR / "fmv_jan_2018.txt"


class Fmv2018Index:
    """Thin wrapper around NavIndex pinned to the 31-Jan-2018 snapshot."""

    def __init__(self, nav_index: NavIndex) -> None:
        self._idx = nav_index
        self.unmatched: list[str] = []

    @property
    def snapshot_date(self) -> Optional[str]:
        return self._idx.snapshot_date

    def lookup(self, scheme: Scheme) -> Optional[float]:
        """Return the 31-Jan-2018 NAV for the given scheme, or None if not found.

        Records misses on self.unmatched so the caller can surface them.
        """
        # We can't just call NavIndex.lookup because it logs misses to its own list
        # and we want them on ours. Reimplement the lookup chain.
        idx = self._idx
        if scheme.isin and scheme.isin in idx.by_isin:
            return idx.by_isin[scheme.isin]
        if scheme.scheme_code and scheme.scheme_code in idx.by_code:
            return idx.by_code[scheme.scheme_code]
        norm = _normalize(scheme.scheme_name)
        if norm in idx.by_name:
            return idx.by_name[norm]
        for key, nav in idx.by_name.items():
            if (key.startswith(norm) or norm.startswith(key)) and abs(len(key) - len(norm)) <= 12:
                return nav
        self.unmatched.append(scheme.scheme_name)
        return None


def load_fmv_index(cache_file: Path = DEFAULT_CACHE_FILE,
                   force_refresh: bool = False,
                   timeout: int = 60) -> Fmv2018Index:
    """Load the 31-Jan-2018 NAV snapshot from cache, fetching from AMFI if missing.

    The cache is permanent (historical NAVs don't change). If fetch fails and no
    cache exists, returns an empty index — callers degrade gracefully (no
    grandfathering applied, warning surfaced).
    """
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    if force_refresh or not cache_file.exists():
        try:
            resp = requests.get(FMV_URL, timeout=timeout)
            resp.raise_for_status()
            if resp.text.strip():
                cache_file.write_text(resp.text, encoding="utf-8")
        except requests.RequestException:
            # Fall through — return an empty index if no cache.
            pass

    if not cache_file.exists():
        return Fmv2018Index(NavIndex())

    text = cache_file.read_text(encoding="utf-8")
    return Fmv2018Index(NavIndex.from_historical_text(text))


def compute_grandfathered_cost(actual_cost_per_unit: float,
                               fmv: float,
                               sale_nav: float) -> float:
    """Section 112A grandfathering formula, per-unit.

    effective_COA = max(actual_COA, min(FMV_31_Jan_2018, sale_NAV))
    """
    return max(actual_cost_per_unit, min(fmv, sale_nav))
