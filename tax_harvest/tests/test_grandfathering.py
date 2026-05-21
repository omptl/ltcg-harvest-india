"""Tests for Sec 112A grandfathering applied during lot evaluation."""

from __future__ import annotations

from datetime import date

import pytest

from tax_harvest.fmv_2018 import compute_grandfathered_cost
from tax_harvest.lots import evaluate_lots
from tax_harvest.models import Scheme, SchemeCategory, Transaction, TxnType


TODAY = date(2026, 5, 21)


def _eq(name: str, txns: list[Transaction]) -> Scheme:
    return Scheme(folio="F", scheme_name=name, amc="A",
                  category=SchemeCategory.EQUITY, transactions=txns, isin=f"ISIN-{name}")


def _txn(d: date, t: TxnType, units: float, nav: float) -> Transaction:
    return Transaction(date=d, txn_type=t, units=units, nav=nav, amount=units * nav)


# Formula: effective_COA = max(actual, min(FMV, sale_NAV))

def test_grandfather_formula_basic_uplift():
    # actual=10, FMV=50, sale=80 -> effective = max(10, min(50, 80)) = 50
    assert compute_grandfathered_cost(10.0, 50.0, 80.0) == 50.0


def test_grandfather_formula_actual_higher_than_fmv():
    # actual=100, FMV=50, sale=120 -> effective = max(100, min(50, 120)) = 100
    assert compute_grandfathered_cost(100.0, 50.0, 120.0) == 100.0


def test_grandfather_formula_sale_below_fmv_caps_cost_at_sale():
    # actual=10, FMV=50, sale=30 -> effective = max(10, min(50, 30)) = 30 (zero gain)
    assert compute_grandfathered_cost(10.0, 50.0, 30.0) == 30.0


def test_grandfathering_applied_for_pre_2018_equity_lot():
    s = _eq("OLD", [_txn(date(2015, 6, 1), TxnType.PURCHASE, 100, 10.0)])
    # FMV at 31-Jan-2018 was 50; today's NAV 100. Without grandfathering gain = 9000.
    # With grandfathering: effective cost = 50, gain = (100-50)*100 = 5000.
    evals = evaluate_lots(
        [s],
        nav_lookup=lambda _s: 100.0,
        today=TODAY,
        fmv_lookup=lambda _s: 50.0,
    )
    ev = evals[0]
    assert ev.grandfathered is True
    assert ev.effective_cost_per_unit == 50.0
    assert ev.unrealized_gain == pytest.approx(5000.0)


def test_grandfathering_skipped_when_fmv_lookup_disabled():
    s = _eq("OLD", [_txn(date(2015, 6, 1), TxnType.PURCHASE, 100, 10.0)])
    evals = evaluate_lots([s], nav_lookup=lambda _s: 100.0, today=TODAY)
    ev = evals[0]
    assert ev.grandfathered is False
    assert ev.unrealized_gain == pytest.approx(9000.0)
    assert ev.grandfathering_note and "not applied" in ev.grandfathering_note


def test_grandfathering_skipped_for_post_2018_lot():
    s = _eq("NEW", [_txn(date(2020, 6, 1), TxnType.PURCHASE, 100, 10.0)])
    evals = evaluate_lots(
        [s],
        nav_lookup=lambda _s: 100.0,
        today=TODAY,
        fmv_lookup=lambda _s: 50.0,  # would be uplift, but lot is post-cutoff
    )
    ev = evals[0]
    assert ev.grandfathered is False
    assert ev.unrealized_gain == pytest.approx(9000.0)


def test_grandfathering_skipped_for_debt_scheme_even_if_pre_2018():
    s = Scheme(folio="F", scheme_name="Old Debt", amc="A",
               category=SchemeCategory.DEBT_PRE_APR_2023, isin="ISIN-D",
               transactions=[_txn(date(2015, 6, 1), TxnType.PURCHASE, 100, 10.0)])
    evals = evaluate_lots(
        [s],
        nav_lookup=lambda _s: 100.0,
        today=TODAY,
        fmv_lookup=lambda _s: 50.0,
    )
    assert evals[0].grandfathered is False


def test_pre_2018_lot_without_fmv_match_warns_and_uses_actual_cost():
    s = _eq("OLD", [_txn(date(2015, 6, 1), TxnType.PURCHASE, 100, 10.0)])
    evals = evaluate_lots(
        [s],
        nav_lookup=lambda _s: 100.0,
        today=TODAY,
        fmv_lookup=lambda _s: None,
    )
    ev = evals[0]
    assert ev.grandfathered is False
    assert ev.unrealized_gain == pytest.approx(9000.0)
    assert ev.grandfathering_note and "unavailable" in ev.grandfathering_note
