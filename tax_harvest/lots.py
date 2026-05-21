"""FIFO lot construction and lock-in / exit-load evaluation.

The unit of work is (folio, scheme). We process transactions in chronological order,
append a Lot for each unit-creating event, and deplete from the head of the queue for
each unit-depleting event. Bonus units carry zero cost basis; switch-ins use their NAV.
"""

from __future__ import annotations

from collections import deque
from datetime import date, timedelta
from typing import Iterable

from .classifier import classify_lot_for_tax
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
                     equity_exit_load_days: int = 365) -> tuple[bool, str | None]:
    """Default heuristic: 1% exit load if under 365 days for equity-like funds.

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


def evaluate_lots(schemes: Iterable[Scheme], nav_lookup, today: date) -> list[LotEvaluation]:
    """Build lots for every scheme and evaluate each against today's NAV.

    `nav_lookup(scheme) -> float | None` returns the current NAV for a scheme. If
    the NAV is unknown, the lot is excluded with a clear reason.
    """
    out: list[LotEvaluation] = []
    for scheme in schemes:
        lots = build_lots(scheme)
        if not lots:
            continue
        nav = nav_lookup(scheme)
        for lot in lots:
            excluded: str | None = None
            if nav is None:
                excluded = "NAV unavailable — verify scheme code/ISIN against AMFI"
                cur_nav = 0.0
                gain = 0.0
            else:
                cur_nav = float(nav)
                gain = (cur_nav - lot.cost_per_unit) * lot.units_remaining

            locked, lock_reason = _lockin_check(scheme, lot, today)
            has_load, load_reason = _exit_load_check(scheme, lot, today)
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
            ))
    return out
