"""Tests for AMFI NAV index parsing and lookup."""

from __future__ import annotations

from tax_harvest.models import Scheme
from tax_harvest.nav import NavIndex


SAMPLE_AMFI = """
Open Ended Schemes ( Equity Scheme - Large Cap Fund )

HDFC Mutual Fund

Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Net Asset Value;Date
118989;INF179KA1AB1;-;HDFC Top 100 Fund - Direct Plan - Growth Option;1234.5678;21-May-2026
119000;INF179KA1XX2;INF179KA1XX3;HDFC Mid-Cap Opportunities Fund - Regular Plan - Growth;567.8901;21-May-2026

Open Ended Schemes ( Debt Scheme - Liquid Fund )

ABC AMC

Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Net Asset Value;Date
120000;INF999AA0001;-;ABC Liquid Fund - Direct - Growth;1500.000;21-May-2026
"""


def test_navindex_parses_amfi_text():
    idx = NavIndex.from_text(SAMPLE_AMFI)
    assert idx.by_isin["INF179KA1AB1"] == 1234.5678
    assert idx.by_code["119000"] == 567.8901
    assert idx.snapshot_date == "21-May-2026"


def test_lookup_by_isin_wins():
    idx = NavIndex.from_text(SAMPLE_AMFI)
    s = Scheme(folio="x", scheme_name="HDFC Top 100 Fund - Direct Plan - Growth Option",
               amc="HDFC", isin="INF179KA1AB1")
    assert idx.lookup(s) == 1234.5678


def test_lookup_by_amfi_code():
    idx = NavIndex.from_text(SAMPLE_AMFI)
    s = Scheme(folio="x", scheme_name="HDFC Mid-Cap Opportunities Fund - Regular Plan - Growth",
               amc="HDFC", scheme_code="119000")
    assert idx.lookup(s) == 567.8901


def test_lookup_unmatched_appends_to_unmatched():
    idx = NavIndex.from_text(SAMPLE_AMFI)
    s = Scheme(folio="x", scheme_name="Nonexistent Fund - Direct - Growth", amc="XYZ")
    assert idx.lookup(s) is None
    assert "Nonexistent Fund - Direct - Growth" in idx.unmatched
