"""Tests for the optional stocks-side LTCG adjustment to the Sec 112A budget."""

from __future__ import annotations

import pytest

from tax_harvest.stocks import load_stocks_adjustment


FY = "2026-27"  # Apr 1 2026 → Mar 31 2027


def test_flat_amount_passes_through():
    adj = load_stocks_adjustment(flat_ltcg=40_000, ledger_path=None, fy_label=FY)
    assert adj.realized_ltcg == 40_000
    assert adj.lines == []
    assert any("flat input" in s for s in adj.sources)


def test_none_inputs_produce_empty_adjustment():
    adj = load_stocks_adjustment(flat_ltcg=None, ledger_path=None, fy_label=FY)
    assert adj.is_empty()
    assert adj.realized_ltcg == 0
    assert adj.lines == []


def test_csv_sums_ltcg_only_for_in_fy_sales(tmp_path):
    """LTCG (>365d) rows whose sell_date is in FY → counted.
    STCG, losses, and out-of-FY rows → ignored."""
    csv_path = tmp_path / "stocks.csv"
    csv_path.write_text(
        "isin,symbol,buy_date,sell_date,quantity,buy_value,sell_value\n"
        # In-FY LTCG (held ~2 years, sold 2026-06-15) → counted (gain 30,000)
        "INE001A01036,RELIANCE,2024-06-01,2026-06-15,10,200000,230000\n"
        # In-FY STCG (held 100 days) → ignored
        "INE002A01018,TCS,2026-01-01,2026-04-11,5,15000,18000\n"
        # In-FY LTCG with loss → ignored (sec 112A counts only positive gains)
        "INE003A01024,INFY,2024-01-01,2026-05-01,5,10000,8000\n"
        # LTCG but sold in PRIOR FY → ignored
        "INE004A01030,HDFC,2023-01-01,2025-06-01,3,9000,15000\n"
        # LTCG sold in NEXT FY → ignored
        "INE005A01047,ITC,2024-01-01,2027-04-15,3,9000,15000\n",
        encoding="utf-8",
    )
    adj = load_stocks_adjustment(flat_ltcg=None, ledger_path=csv_path, fy_label=FY)
    assert adj.realized_ltcg == 30_000
    assert len(adj.lines) == 1
    assert adj.lines[0].symbol == "RELIANCE"


def test_flat_and_csv_inputs_sum(tmp_path):
    csv_path = tmp_path / "stocks.csv"
    csv_path.write_text(
        "isin,symbol,buy_date,sell_date,quantity,buy_value,sell_value\n"
        "INE001A01036,RELIANCE,2024-06-01,2026-06-15,10,200000,225000\n",
        encoding="utf-8",
    )
    adj = load_stocks_adjustment(flat_ltcg=10_000, ledger_path=csv_path, fy_label=FY)
    assert adj.realized_ltcg == 35_000  # 25k from CSV + 10k flat


def test_missing_columns_raises_clear_error(tmp_path):
    csv_path = tmp_path / "bad.csv"
    csv_path.write_text("isin,symbol,quantity\nINE001,RELIANCE,10\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing required column"):
        load_stocks_adjustment(flat_ltcg=None, ledger_path=csv_path, fy_label=FY)


def test_missing_file_raises_filenotfounderror(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_stocks_adjustment(flat_ltcg=None,
                                ledger_path=tmp_path / "nope.csv",
                                fy_label=FY)


def test_date_format_flexibility(tmp_path):
    """Accept YYYY-MM-DD, DD-MM-YYYY, DD/MM/YYYY, DD-Mon-YYYY."""
    csv_path = tmp_path / "stocks.csv"
    csv_path.write_text(
        "isin,symbol,buy_date,sell_date,quantity,buy_value,sell_value\n"
        "INE001,A,01-06-2024,15-06-2026,1,100,150\n"
        "INE002,B,01/06/2024,15/06/2026,1,100,160\n"
        "INE003,C,01-Jun-2024,15-Jun-2026,1,100,170\n",
        encoding="utf-8",
    )
    adj = load_stocks_adjustment(flat_ltcg=None, ledger_path=csv_path, fy_label=FY)
    assert len(adj.lines) == 3
    assert adj.realized_ltcg == 50 + 60 + 70


def test_blank_sell_date_treated_as_open_position(tmp_path):
    csv_path = tmp_path / "stocks.csv"
    csv_path.write_text(
        "isin,symbol,buy_date,sell_date,quantity,buy_value,sell_value\n"
        "INE001,STILL_HELD,2024-06-01,,10,200000,0\n"
        "INE002,SOLD,2024-06-01,2026-06-15,10,200000,250000\n",
        encoding="utf-8",
    )
    adj = load_stocks_adjustment(flat_ltcg=None, ledger_path=csv_path, fy_label=FY)
    assert len(adj.lines) == 1
    assert adj.lines[0].symbol == "SOLD"
