"""Scheme classification — determines tax treatment for each scheme.

We classify on scheme name (and optionally type metadata from casparser) using a
priority-ordered keyword match. A misclassification here changes tax treatment, so
when in doubt we tag UNKNOWN and surface a warning rather than guess.
"""

from __future__ import annotations

import json
import re
from datetime import date
from importlib.resources import files
from pathlib import Path
from typing import Optional

from .models import Scheme, SchemeCategory

# Cutoff for the Section 50AA "specified mutual fund" rule. Units of debt schemes
# acquired on or after this date are taxed at slab rates regardless of holding period.
DEBT_50AA_CUTOFF = date(2023, 4, 1)


# Each pattern is (compiled regex, category). Order matters — earlier wins.
# Patterns are matched against the scheme name (lower-cased).
_PATTERNS: list[tuple[re.Pattern[str], SchemeCategory]] = [
    # Solution-oriented (5-year lock-in or goal-age)
    (re.compile(r"\b(retirement|children'?s?\s*gift|child\s*plan|children\s*fund)\b"),
     SchemeCategory.SOLUTION_ORIENTED),

    # ELSS / tax saver — 3-year per-lot lock-in
    (re.compile(r"\b(elss|tax\s*saver|tax\s*plan|long\s*term\s*equity)\b"),
     SchemeCategory.ELSS),

    # Fixed Maturity Plans
    (re.compile(r"\b(fmp|fixed\s*maturity)\b"), SchemeCategory.FMP),

    # Arbitrage — equity for tax
    (re.compile(r"\barbitrage\b"), SchemeCategory.ARBITRAGE),

    # Aggressive hybrid / equity-oriented hybrid
    (re.compile(r"\b(aggressive\s*hybrid|equity\s*savings|balanced\s*advantage|"
                r"dynamic\s*asset|equity\s*hybrid|balanced\s*fund|balanced\s*equity)\b"),
     SchemeCategory.EQUITY_HYBRID_AGGRESSIVE),

    # Conservative hybrid / debt-oriented hybrid -> debt treatment
    (re.compile(r"\b(conservative\s*hybrid|monthly\s*income|mip|debt\s*hybrid|"
                r"income\s*plus)\b"),
     SchemeCategory.HYBRID_CONSERVATIVE),

    # International / foreign equity FoFs — flag (post-Apr-2025 rules need verification)
    (re.compile(r"\b(international|global|us\s*equity|nasdaq|s&?p\s*500|"
                r"hang\s*seng|emerging\s*markets?|world|overseas)\b"),
     SchemeCategory.INTERNATIONAL),

    # Gold / silver
    (re.compile(r"\b(gold|silver|precious\s*metal)\b"), SchemeCategory.GOLD),

    # Debt fund identifiers
    (re.compile(r"\b(liquid|overnight|ultra\s*short|low\s*duration|money\s*market|"
                r"short\s*duration|medium\s*duration|long\s*duration|corporate\s*bond|"
                r"banking\s*and?\s*psu|credit\s*risk|gilt|dynamic\s*bond|"
                r"floating\s*rate|debt\s*fund|income\s*fund|bond\s*fund|psu\s*bond)\b"),
     SchemeCategory.DEBT_PRE_APR_2023),  # date-refined later

    # Equity fund identifiers (broad)
    (re.compile(r"\b(equity|large\s*cap|mid\s*cap|small\s*cap|multi\s*cap|"
                r"flexi\s*cap|focused|value|contra|dividend\s*yield|"
                r"sectoral|thematic|infrastructure|banking|pharma|technology|"
                r"consumption|fmcg|esg|quant|bluechip|nifty|sensex|index)\b"),
     SchemeCategory.EQUITY),
]

# Close-ended markers in scheme name (series numbers, "series", etc.). Treat carefully.
_CLOSE_ENDED_PATTERN = re.compile(r"\bseries\s*[-\s]?\d+|\bclose\s*ended\b")


def classify_scheme(scheme: Scheme,
                    overrides: Optional[dict[str, SchemeCategory]] = None) -> SchemeCategory:
    """Determine the SchemeCategory for a scheme.

    `overrides` (keyed by ISIN) wins over name heuristics — used to correct
    schemes the regexes misclassify. Returns UNKNOWN if no pattern matches;
    callers should surface this to the user.
    """
    if overrides and scheme.isin and scheme.isin in overrides:
        return overrides[scheme.isin]

    name = scheme.scheme_name.lower()

    if _CLOSE_ENDED_PATTERN.search(name):
        # An FMP match later still wins; but a generic close-ended close-ended series
        # without other markers we mark close-ended.
        for pattern, cat in _PATTERNS:
            if pattern.search(name) and cat in (SchemeCategory.FMP,):
                return cat
        return SchemeCategory.CLOSE_ENDED

    for pattern, cat in _PATTERNS:
        if pattern.search(name):
            return cat

    return SchemeCategory.UNKNOWN


def load_overrides(extra_file: Optional[Path] = None) -> dict[str, SchemeCategory]:
    """Load ISIN -> SchemeCategory overrides.

    The packaged `data/category_overrides.json` is always loaded; an optional
    user file is merged on top (user wins on conflicts).
    """
    out: dict[str, SchemeCategory] = {}

    try:
        packaged = files("tax_harvest.data").joinpath("category_overrides.json")
        raw = json.loads(packaged.read_text())
        out.update(_parse_override_dict(raw.get("overrides", {})))
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    if extra_file is not None:
        path = Path(extra_file)
        if not path.exists():
            raise FileNotFoundError(f"Overrides file not found: {path}")
        raw = json.loads(path.read_text())
        # Accept either {"overrides": {...}} or just the bare dict.
        if "overrides" in raw and isinstance(raw["overrides"], dict):
            out.update(_parse_override_dict(raw["overrides"]))
        else:
            out.update(_parse_override_dict(raw))

    return out


def _parse_override_dict(d: dict) -> dict[str, SchemeCategory]:
    """Validate and coerce {ISIN: category-string} into {ISIN: SchemeCategory}."""
    valid = {c.value for c in SchemeCategory}
    out: dict[str, SchemeCategory] = {}
    for isin, cat_str in d.items():
        if not isinstance(cat_str, str) or cat_str not in valid:
            raise ValueError(
                f"Invalid category '{cat_str}' for ISIN {isin}. "
                f"Allowed: {sorted(valid)}"
            )
        out[isin] = SchemeCategory(cat_str)
    return out


def load_suspended_isins(extra_file: Optional[Path] = None) -> dict[str, str]:
    """Return ISIN -> note for known suspended/wound-up schemes."""
    out: dict[str, str] = {}
    try:
        packaged = files("tax_harvest.data").joinpath("suspended_schemes.json")
        raw = json.loads(packaged.read_text())
        out.update(raw.get("suspended", {}) or {})
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    if extra_file is not None:
        path = Path(extra_file)
        if not path.exists():
            raise FileNotFoundError(f"Suspended-schemes file not found: {path}")
        raw = json.loads(path.read_text())
        out.update(raw.get("suspended", raw) or {})

    return out


def refine_debt_category(scheme: Scheme, first_purchase_date: date | None) -> SchemeCategory:
    """For debt schemes, split into pre- vs post-Apr-2023 based on first purchase.

    This is a coarse split at the scheme level. In reality the cutoff is per-acquisition,
    so a single scheme can have lots in both buckets — we handle that lot-by-lot in
    the harvest filter. This function exists so the scheme display label is informative.
    """
    if scheme.category != SchemeCategory.DEBT_PRE_APR_2023:
        return scheme.category
    if first_purchase_date is None:
        return scheme.category
    return (SchemeCategory.DEBT_POST_APR_2023
            if first_purchase_date >= DEBT_50AA_CUTOFF
            else SchemeCategory.DEBT_PRE_APR_2023)


def classify_lot_for_tax(category: SchemeCategory, purchase_date: date) -> SchemeCategory:
    """Determine the effective tax category for a single lot.

    For debt schemes, the per-lot acquisition date decides Sec 50AA applicability.
    For everything else, the scheme-level category applies directly.
    """
    if category in (SchemeCategory.DEBT_PRE_APR_2023, SchemeCategory.DEBT_POST_APR_2023,
                    SchemeCategory.HYBRID_CONSERVATIVE):
        if purchase_date >= DEBT_50AA_CUTOFF:
            return SchemeCategory.DEBT_POST_APR_2023
        return SchemeCategory.DEBT_PRE_APR_2023
    return category
