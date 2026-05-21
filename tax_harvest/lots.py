"""FIFO lot construction and lock-in / exit-load evaluation.

The unit of work is (folio, scheme). We process transactions in chronological order,
append a Lot for each unit-creating event, and deplete from the head of the queue for
each unit-depleting event. Bonus units carry zero cost basis; switch-ins use their NAV.
"""

from __future__ import annotations

from collections import deque
from datetime import date, timedelta
from typing import Callable, Iterable, Optional

from .classifier import classify_lot_for_tax
from .fmv_2018 import compute_grandfathered_cost
from .models import (
    EQUITY_LIKE_CATEGORIES,
    Lot,
    LotEvaluation,
    Scheme,
    SchemeCategory,
    Transaction,
    TxnType,
    UNIT_CREATING_TYPES,
    UNIT_DEPLETING_TYPES,
)

EQUITY_LTCG_DAYS = 365  # > 12 months. We use strict >, see is_ltcg_eligible.
DEBT_LTCG_DAYS = 730  # > 24 months for pre-Apr-2023 debt
ELSS_LOCKIN_DAYS = 3 * 365 + 1  # 3 years, rounding via days; we add 1 to be conservative
SOLUTION_LOCKIN_DAYS = 5 * 365 + 1
GRANDFATHERING_CUTOFF = date(2018, 1, 31)  # Sec 112A: lots acquired on/before this date

NavLookup = Callable[[Scheme], Optional[float]]
FmvLookup = Callable[[Scheme], Optional[float]]


def build_lots(scheme: Scheme) -> list[Lot]:
    """Replay a scheme's transaction history into a FIFO lot list.

    Returns the surviving lots (units_remaining > 0) after applying all redemptions
    and switch-outs. Transactions are sorted by date before replay; ties are stable.
    """
    queue: deque[Lot] = deque()
    txns = sorted(scheme.transactions, key=lambda t: t.date)

    for txn in txns:
        if txn.txn_type in UNIT_CREATING_TYPES and txn.units > 0:
            cost = 0.0 if txn.txn_type == TxnType.BONUS else float(txn.nav)
            queue.append(Lot(
                purchase_date=txn.date,
                units_original=float(txn.units),
                units_remaining=float(txn.units),
                cost_per_unit=cost,
                source_txn_type=txn.txn_type,
            ))
        elif txn.txn_type in UNIT_DEPLETING_TYPES:
            # Units in CAS are signed; we treat magnitude.
            to_deplete = abs(float(txn.units))
            while to_deplete > 1e-6 and queue:
                head = queue[0]
                if head.units_remaining <= to_deplete + 1e-6:
                    to_deplete -= head.units_remaining
                    head.units_remaining = 0.0
                    queue.popleft()
                else:
                    head.units_remaining -= to_deplete
                    to_deplete = 0.0
            # If to_deplete > 0 here, CAS has inconsistent data (e.g., partial history);
            # we silently absorb — the caller can compare totals if needed.

    return [lot for lot in queue if lot.units_remaining > 1e-6]


def _lockin_check(scheme: Scheme, lot: Lot, today: date) -> tuple[bool, str | None]:
    """Return (is_locked, reason)."""
    cat = scheme.category
    age_days = (today - lot.purchase_date).days
    if cat == SchemeCategory.ELSS:
        if age_days < ELSS_LOCKIN_DAYS - 1:
            unlock = lot.purchase_date + timedelta(days=ELSS_LOCKIN_DAYS - 1)
            return True, f"ELSS 3-yr lock-in (unlocks {unlock.isoformat()})"
    if cat == SchemeCategory.SOLUTION_ORIENTED:
        if age_days < SOLUTION_LOCKIN_DAYS - 1:
            unlock = lot.purchase_date + timedelta(days=SOLUTION_LOCKIN_DAYS - 1)
            return True, (f"Solution-oriented 5-yr lock-in (unlocks {unlock.isoformat()}); "
                          f"also verify goal age is reached")
        return True, "Solution-oriented — confirm goal age reached before redeeming"
    if cat in (SchemeCategory.CLOSE_ENDED, SchemeCategory.FMP):
        return True, f"{cat.value} — locked till scheme maturity"
    return False, None


def _exit_load_check(scheme: Scheme, lot: Lot, today: date,
                     equity_exit_load_days: int) -> tuple[bool, str | None]:
    """Heuristic: 1% exit load if under `equity_exit_load_days` days for equity funds.

    For LTCG harvesting the lot must already be >365 days (equity), so this only
    flags weird cases. For debt funds we don't model exit load (varies widely).
    """
    age_days = (today - lot.purchase_date).days
    if scheme.category in EQUITY_LIKE_CATEGORIES and age_days < equity_exit_load_days:
        return True, f"Exit load may apply (<{equity_exit_load_days}d)"
    return False, None


def _ltcg_eligible(scheme: Scheme, lot: Lot, today: date) -> bool:
    """Whether the lot's gain would be classified as LTCG today."""
    age_days = (today - lot.purchase_date).days
    effective_cat = classify_lot_for_tax(scheme.category, lot.purchase_date)
    if effective_cat in EQUITY_LIKE_CATEGORIES:
        return age_days > EQUITY_LTCG_DAYS
    if effective_cat == SchemeCategory.DEBT_POST_APR_2023:
        # Sec 50AA: always slab-rate STCG. Never LTCG-eligible.
        return False
    if effective_cat == SchemeCategory.DEBT_PRE_APR_2023:
        return age_days > DEBT_LTCG_DAYS
    if effective_cat in (SchemeCategory.INTERNATIONAL, SchemeCategory.GOLD):
        # Post-Budget-2024 these are 12.5% LTCG after 24 months; flag separately.
        return age_days > DEBT_LTCG_DAYS
    return False


def _apply_grandfathering(scheme: Scheme, lot: Lot, cur_nav: float,
                          fmv_lookup: Optional[FmvLookup]
                          ) -> tuple[float, bool, Optional[str]]:
    """Return (effective_cost_per_unit, grandfathered_flag, note).

    Only applies to equity-like lots acquired on or before 31-Jan-2018. If FMV is
    unavailable for such a lot, we conservatively fall back to actual cost and
    surface a note so the user knows to verify.
    """
    if scheme.category not in EQUITY_LIKE_CATEGORIES:
        return lot.cost_per_unit, False, None
    if lot.purchase_date > GRANDFATHERING_CUTOFF:
        return lot.cost_per_unit, False, None

    if fmv_lookup is None:
        return (
            lot.cost_per_unit,
            False,
            "Pre-2018 equity lot — Sec 112A grandfathering not applied "
            "(FMV lookup disabled); gain may be overstated",
        )

    fmv = fmv_lookup(scheme)
    if fmv is None or fmv <= 0:
        return (
            lot.cost_per_unit,
            False,
            "Pre-2018 equity lot — 31-Jan-2018 FMV unavailable; gain may be overstated. "
            "Look up the FMV manually and adjust.",
        )

    effective = compute_grandfathered_cost(lot.cost_per_unit, fmv, cur_nav)
    if abs(effective - lot.cost_per_unit) < 1e-6:
        return effective, False, None
    return effective, True, (
        f"Grandfathered cost: actual ₹{lot.cost_per_unit:.4f}/u → "
        f"effective ₹{effective:.4f}/u (FMV 31-Jan-2018: ₹{fmv:.4f}/u)"
    )


def evaluate_lots(schemes: Iterable[Scheme],
                  nav_lookup: NavLookup,
                  today: date,
                  fmv_lookup: Optional[FmvLookup] = None,
                  equity_exit_load_days: int = 365) -> list[LotEvaluation]:
    """Build lots for every scheme and evaluate each against today's NAV.

    `nav_lookup(scheme)` returns the current NAV for a scheme; `None` means the
    lot is excluded with a clear reason. `fmv_lookup(scheme)` returns the
    31-Jan-2018 NAV for grandfathering; `None` (the default) disables
    grandfathering — gain will be computed against actual cost.
    """
    out: list[LotEvaluation] = []
    for scheme in schemes:
        lots = build_lots(scheme)
        if not lots:
            continue
        nav = nav_lookup(scheme)
        for lot in lots:
            excluded: str | None = None
            cur_nav = 0.0
            if nav is None:
                if scheme.is_suspended:
                    excluded = "Scheme suspended/wound-up — cannot transact"
                else:
                    excluded = ("NAV unavailable on AMFI feed — scheme may be suspended, "
                                "wound-up, or the ISIN/scheme code is wrong. Verify manually.")
            else:
                cur_nav = float(nav)

            if scheme.is_suspended and excluded is None:
                excluded = "Scheme suspended/wound-up — cannot transact"

            effective_cost, grandfathered, gf_note = _apply_grandfathering(
                scheme, lot, cur_nav, fmv_lookup
            )
            gain = (cur_nav - effective_cost) * lot.units_remaining if nav is not None else 0.0

            locked, lock_reason = _lockin_check(scheme, lot, today)
            has_load, load_reason = _exit_load_check(scheme, lot, today, equity_exit_load_days)
            ltcg = _ltcg_eligible(scheme, lot, today)

            if excluded is None:
                effective_cat = classify_lot_for_tax(scheme.category, lot.purchase_date)
                if locked:
                    excluded = lock_reason
                elif effective_cat == SchemeCategory.DEBT_POST_APR_2023:
                    excluded = "Debt unit acquired on/after 1-Apr-2023 — Sec 50AA, slab-rate STCG only"
                elif scheme.category == SchemeCategory.UNKNOWN:
                    excluded = "Scheme category unknown — manual verification required"
                elif not ltcg:
                    excluded = "Holding period not yet LTCG-eligible"
                elif has_load:
                    excluded = load_reason

            out.append(LotEvaluation(
                scheme=scheme,
                lot=lot,
                current_nav=cur_nav,
                unrealized_gain=gain,
                gain_per_unit=(gain / lot.units_remaining) if lot.units_remaining else 0.0,
                holding_days=(today - lot.purchase_date).days,
                is_ltcg_eligible=ltcg,
                is_locked_in=locked,
                locked_reason=lock_reason,
                has_exit_load=has_load,
                exit_load_reason=load_reason,
                excluded_reason=excluded,
                grandfathered=grandfathered,
                effective_cost_per_unit=effective_cost if grandfathered else None,
                grandfathering_note=gf_note,
            ))
    return out
