"""Tests for FIFO lot construction and evaluation."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from tax_harvest.lots import (
    DEBT_LTCG_DAYS,
    ELSS_LOCKIN_DAYS,
    EQUITY_LTCG_DAYS,
    build_lots,
    evaluate_lots,
)
from tax_harvest.models import Scheme, SchemeCategory, Transaction, TxnType


def _scheme(name: str, category: SchemeCategory, txns: list[Transaction]) -> Scheme:
    return Scheme(folio="1234", scheme_name=name, amc="Test AMC",
                  category=category, transactions=txns)


def _txn(d: date, t: TxnType, units: float, nav: float = 100.0,
         amount: float | None = None) -> Transaction:
    return Transaction(date=d, txn_type=t, units=units, nav=nav,
                       amount=amount if amount is not None else units * nav)


def test_fifo_depletes_oldest_lot_first():
    s = _scheme("X Equity Fund", SchemeCategory.EQUITY, [
        _txn(date(2020, 1, 1), TxnType.PURCHASE, units=100, nav=10),
        _txn(date(2021, 1, 1), TxnType.PURCHASE, units=100, nav=20),
        _txn(date(2022, 1, 1), TxnType.REDEMPTION, units=-150, nav=30),
    ])
    lots = build_lots(s)
    assert len(lots) == 1
    assert lots[0].purchase_date == date(2021, 1, 1)
    assert lots[0].units_remaining == pytest.approx(50.0)
    assert lots[0].cost_per_unit == 20


def test_bonus_units_have_zero_cost_basis():
    s = _scheme("X Equity Fund", SchemeCategory.EQUITY, [
        _txn(date(2020, 1, 1), TxnType.PURCHASE, units=100, nav=10),
        _txn(date(2021, 1, 1), TxnType.BONUS, units=10, nav=0, amount=0),
    ])
    lots = build_lots(s)
    bonus = [l for l in lots if l.source_txn_type == TxnType.BONUS][0]
    assert bonus.cost_per_unit == 0.0
    assert bonus.purchase_date == date(2021, 1, 1)


def test_switch_in_creates_lot_and_switch_out_depletes():
    s_dest = _scheme("Dest Fund", SchemeCategory.EQUITY, [
        _txn(date(2022, 6, 1), TxnType.SWITCH_IN, units=50, nav=40),
        _txn(date(2024, 1, 1), TxnType.SWITCH_OUT, units=-20, nav=60),
    ])
    lots = build_lots(s_dest)
    assert len(lots) == 1
    assert lots[0].units_remaining == pytest.approx(30.0)
    assert lots[0].cost_per_unit == 40


def test_dividend_reinvest_creates_lot_at_reinvest_nav():
    s = _scheme("Dividend Fund", SchemeCategory.EQUITY, [
        _txn(date(2020, 1, 1), TxnType.PURCHASE, units=100, nav=10),
        _txn(date(2021, 6, 1), TxnType.DIVIDEND_REINVEST, units=5, nav=15),
    ])
    lots = build_lots(s)
    assert len(lots) == 2
    reinvest = lots[1]
    assert reinvest.cost_per_unit == 15
    assert reinvest.units_remaining == 5


def test_evaluate_excludes_elss_lot_inside_lockin():
    today = date(2026, 5, 21)
    in_lockin = today - timedelta(days=ELSS_LOCKIN_DAYS - 30)
    out_of_lockin = today - timedelta(days=ELSS_LOCKIN_DAYS + 30)
    s = _scheme("Tax Saver ELSS", SchemeCategory.ELSS, [
        _txn(in_lockin, TxnType.SIP, units=10, nav=20),
        _txn(out_of_lockin, TxnType.SIP, units=10, nav=15),
    ])
    evals = evaluate_lots([s], nav_lookup=lambda _s: 50.0, today=today)
    by_date = {e.lot.purchase_date: e for e in evals}
    assert by_date[in_lockin].excluded_reason and "lock-in" in by_date[in_lockin].excluded_reason
    assert by_date[out_of_lockin].excluded_reason is None


def test_evaluate_excludes_debt_post_apr_2023_lot():
    today = date(2026, 5, 21)
    s = _scheme("Bharat Debt Fund", SchemeCategory.DEBT_POST_APR_2023, [
        _txn(date(2023, 5, 1), TxnType.PURCHASE, units=100, nav=10),
    ])
    evals = evaluate_lots([s], nav_lookup=lambda _s: 12.0, today=today)
    assert len(evals) == 1
    assert evals[0].excluded_reason and "Sec 50AA" in evals[0].excluded_reason


def test_debt_pre_apr_2023_lot_ltcg_eligible_after_24_months():
    today = date(2026, 5, 21)
    # Purchase pre-Apr-2023 and held >24 months: LTCG-eligible at 12.5% no indexation.
    pre_cutoff_old = date(2022, 1, 1)
    s = _scheme("Old Debt", SchemeCategory.DEBT_PRE_APR_2023, [
        _txn(pre_cutoff_old, TxnType.PURCHASE, units=100, nav=10),
    ])
    evals = evaluate_lots([s], nav_lookup=lambda _s: 14.0, today=today)
    assert evals[0].excluded_reason is None
    assert evals[0].unrealized_gain == pytest.approx(400.0)


def test_equity_under_one_year_excluded():
    today = date(2026, 5, 21)
    s = _scheme("Recent Equity", SchemeCategory.EQUITY, [
        _txn(today - timedelta(days=EQUITY_LTCG_DAYS - 5),
             TxnType.PURCHASE, units=100, nav=10),
    ])
    evals = evaluate_lots([s], nav_lookup=lambda _s: 15.0, today=today)
    # Either holding period or exit load reason fires — both legitimate exclusions.
    assert evals[0].excluded_reason is not None


def test_unknown_scheme_excluded_with_warning_message():
    today = date(2026, 5, 21)
    s = _scheme("?? Unmapped Scheme ??", SchemeCategory.UNKNOWN, [
        _txn(date(2020, 1, 1), TxnType.PURCHASE, units=100, nav=10),
    ])
    evals = evaluate_lots([s], nav_lookup=lambda _s: 25.0, today=today)
    assert evals[0].excluded_reason and "unknown" in evals[0].excluded_reason.lower()


def test_redemption_exceeding_holdings_does_not_crash():
    s = _scheme("X", SchemeCategory.EQUITY, [
        _txn(date(2020, 1, 1), TxnType.PURCHASE, units=10, nav=10),
        _txn(date(2021, 1, 1), TxnType.REDEMPTION, units=-50, nav=20),
    ])
    lots = build_lots(s)
    assert lots == []
