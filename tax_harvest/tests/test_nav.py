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


# --- regression: snapshot_date should be the mode date, not the last-row date ---
# Real AMFI feeds mix in stale dates from interval / FMP / wound-up schemes, which
# sort to the bottom. Picking the last-seen date misreports the snapshot's freshness.

MIXED_DATE_AMFI = """
Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Net Asset Value;Date
118989;INF179KA1AB1;-;HDFC Top 100 Fund - Direct Plan - Growth;1234.5678;21-May-2026
119000;INF179KA1XX2;-;HDFC Mid-Cap Opportunities Fund - Direct Plan - Growth;567.8901;21-May-2026
120000;INF999AA0001;-;ABC Liquid Fund - Direct - Growth;1500.000;21-May-2026
110021;INF789F01HA3;-;UTI Quarterly Interval Fund - III -Regular Plan - IDCW;11.0613;25-Mar-2025
"""


def test_snapshot_date_uses_mode_not_last_row():
    idx = NavIndex.from_text(MIXED_DATE_AMFI)
    assert idx.snapshot_date == "21-May-2026"


# --- regression: historical FMV feed has an 8-column layout (Code;Name;ISIN_G;ISIN_R;
# NAV;Repurchase;Sale;Date) — different from the daily 6-col feed. Parsing it with
# the daily layout misreads the date column and breaks by_name lookups. ---

SAMPLE_HISTORICAL = """
Scheme Code;Scheme Name;ISIN Div Payout/ISIN Growth;ISIN Div Reinvestment;Net Asset Value;Repurchase Price;Sale Price;Date

Open Ended Schemes ( Income )

Aditya Birla Sun Life Mutual Fund
120704;Aditya Birla Sun Life MIP - Direct Plan - Growth;INF209K01XB7;;46.7762;46.3084;46.7762;31-Jan-2018
100970;Aditya Birla Sun Life MIP - Regular Plan - Growth;INF209K01694;;45.2981;44.8451;45.2981;31-Jan-2018
"""


def test_historical_parser_reads_date_column_correctly():
    idx = NavIndex.from_historical_text(SAMPLE_HISTORICAL)
    assert idx.snapshot_date == "31-Jan-2018"


def test_historical_parser_indexes_by_name():
    idx = NavIndex.from_historical_text(SAMPLE_HISTORICAL)
    s = Scheme(folio="x", scheme_name="Aditya Birla Sun Life MIP - Direct Plan - Growth", amc="ABSL")
    assert idx.lookup(s) == 46.7762


def test_historical_parser_indexes_by_isin():
    idx = NavIndex.from_historical_text(SAMPLE_HISTORICAL)
    s = Scheme(folio="x", scheme_name="anything", amc="ABSL", isin="INF209K01694")
    assert idx.lookup(s) == 45.2981


# --- regression: a zero-byte cache file (left by a crashed prior write) must be
# treated as stale, not as a fresh-enough cache. Without this, every subsequent
# run inside the 24h window silently returns zero NAVs. ---


def test_empty_cache_file_triggers_refetch(tmp_path, monkeypatch):
    from tax_harvest import nav as nav_module

    cache = tmp_path / "nav_cache.txt"
    cache.write_bytes(b"")  # empty file, mtime = now
    assert cache.exists() and cache.stat().st_size == 0

    fetched = {"count": 0}

    class FakeResp:
        text = MIXED_DATE_AMFI

        def raise_for_status(self):
            return None

    def fake_get(url, timeout):
        fetched["count"] += 1
        return FakeResp()

    monkeypatch.setattr(nav_module.requests, "get", fake_get)
    idx = nav_module.load_nav_index(cache_file=cache, force_refresh=False)
    assert fetched["count"] == 1
    assert idx.snapshot_date == "21-May-2026"
