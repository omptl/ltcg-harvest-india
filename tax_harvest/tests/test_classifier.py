"""Tests for scheme classification heuristics."""

from __future__ import annotations

from datetime import date

import pytest

from tax_harvest.classifier import (
    DEBT_50AA_CUTOFF,
    classify_lot_for_tax,
    classify_scheme,
    refine_debt_category,
)
from tax_harvest.models import Scheme, SchemeCategory


def _s(name: str) -> Scheme:
    return Scheme(folio="x", scheme_name=name, amc="")


@pytest.mark.parametrize("name,expected", [
    ("Axis Long Term Equity Fund - Growth", SchemeCategory.ELSS),
    ("Mirae Asset ELSS Tax Saver", SchemeCategory.ELSS),
    ("HDFC Retirement Savings Fund - Equity Plan", SchemeCategory.SOLUTION_ORIENTED),
    ("ICICI Prudential Children's Gift Fund", SchemeCategory.SOLUTION_ORIENTED),
    ("Nippon India Arbitrage Fund - Growth", SchemeCategory.ARBITRAGE),
    ("HDFC Balanced Advantage Fund", SchemeCategory.EQUITY_HYBRID_AGGRESSIVE),
    ("SBI Conservative Hybrid Fund", SchemeCategory.HYBRID_CONSERVATIVE),
    ("Motilal Oswal Nasdaq 100 FOF", SchemeCategory.INTERNATIONAL),
    ("Nippon India Gold Savings Fund", SchemeCategory.GOLD),
    ("HDFC Liquid Fund", SchemeCategory.DEBT_PRE_APR_2023),
    ("ICICI Prudential Corporate Bond Fund", SchemeCategory.DEBT_PRE_APR_2023),
    ("Axis Bluechip Fund - Growth", SchemeCategory.EQUITY),
    ("Parag Parikh Flexi Cap Fund", SchemeCategory.EQUITY),
    ("Nippon India Small Cap Fund", SchemeCategory.EQUITY),
    ("Some Random FMP Series 37", SchemeCategory.FMP),
])
def test_classifier_basic(name, expected):
    assert classify_scheme(_s(name)) == expected


def test_unknown_scheme_returns_unknown():
    assert classify_scheme(_s("Totally Made Up Vehicle 9000")) == SchemeCategory.UNKNOWN


def test_refine_debt_post_apr_2023():
    s = _s("HDFC Liquid Fund")
    s.category = SchemeCategory.DEBT_PRE_APR_2023
    assert refine_debt_category(s, date(2024, 1, 1)) == SchemeCategory.DEBT_POST_APR_2023
    assert refine_debt_category(s, date(2022, 1, 1)) == SchemeCategory.DEBT_PRE_APR_2023


def test_classify_lot_for_tax_per_lot_50aa():
    # Same scheme, different lot dates -> different effective category
    assert classify_lot_for_tax(SchemeCategory.DEBT_PRE_APR_2023,
                                DEBT_50AA_CUTOFF) == SchemeCategory.DEBT_POST_APR_2023
    assert classify_lot_for_tax(SchemeCategory.DEBT_PRE_APR_2023,
                                date(2023, 3, 31)) == SchemeCategory.DEBT_PRE_APR_2023
    # Equity is unchanged regardless of date
    assert classify_lot_for_tax(SchemeCategory.EQUITY,
                                date(2024, 1, 1)) == SchemeCategory.EQUITY
