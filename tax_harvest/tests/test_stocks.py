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


def test_csv_filters_by_fy_and_long_term_eligibility(tmp_path):
    """LTCG-eligible (>365d) rows whose sell_date is in FY → counted (whether
    gain or loss). STCG/STCL → ignored (Sec 111A, not 112A). Out-of-FY → ignored."""
    csv_path = tmp_path / "stocks.csv"
    csv_path.write_text(
        "isin,symbol,buy_date,sell_date,quantity,buy_value,sell_value\n"
        # In-FY LTCG gain (held ~2 years, sold 2026-06-15)
        "INE001A01036,RELIANCE,2024-06-01,2026-06-15,10,200000,230000\n"
        # In-FY STCG → ignored (Sec 111A)
        "INE002A01018,TCS,2026-01-01,2026-04-11,5,15000,18000\n"
        # In-FY LTCL → counted as a loss (sets off against LTCG)
        "INE003A01024,INFY,2024-01-01,2026-05-01,5,10000,8000\n"
        # LTCG but sold in PRIOR FY → ignored
        "INE004A01030,HDFC,2023-01-01,2025-06-01,3,9000,15000\n"
        # LTCG sold in NEXT FY → ignored
        "INE005A01047,ITC,2024-01-01,2027-04-15,3,9000,15000\n",
        encoding="utf-8",
    )
    adj = load_stocks_adjustment(flat_ltcg=None, ledger_path=csv_path, fy_label=FY)
    assert adj.realized_ltcg == 30_000  # RELIANCE only
    assert adj.realized_ltcl == 2_000   # INFY loss
    assert adj.net_ltcg == 28_000
    # Both LTCG-eligible in-FY rows kept (gain + loss); STCG / out-of-FY dropped
    assert len(adj.lines) == 2
    assert {ln.symbol for ln in adj.lines} == {"RELIANCE", "INFY"}


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


def test_ltcl_flag_only():
    """Flat-only LTCL with no gains → net is negative; budget should expand."""
    adj = load_stocks_adjustment(flat_ltcg=None, flat_ltcl=20_000,
                                  ledger_path=None, fy_label=FY)
    assert adj.realized_ltcg == 0
    assert adj.realized_ltcl == 20_000
    assert adj.net_ltcg == -20_000


def test_ltcg_and_ltcl_combine_via_flags():
    adj = load_stocks_adjustment(flat_ltcg=30_000, flat_ltcl=20_000,
                                  ledger_path=None, fy_label=FY)
    assert adj.net_ltcg == 10_000


def test_csv_separates_ltcg_and_ltcl_within_eligible_rows(tmp_path):
    """All rows held >365d. Tool should sum gains and losses separately and
    net them — not silently drop the loss rows like the earlier version did."""
    csv_path = tmp_path / "stocks.csv"
    csv_path.write_text(
        "isin,symbol,buy_date,sell_date,quantity,buy_value,sell_value\n"
        # LTCG rows (gain)
        "INE001,WINNER1,2024-06-01,2026-06-15,10,100000,130000\n"
        "INE002,WINNER2,2024-06-01,2026-06-15,5,50000,56000\n"
        # LTCL rows (loss but still long-term)
        "INE003,LOSER1,2024-06-01,2026-06-15,10,100000,80000\n"
        "INE004,LOSER2,2024-06-01,2026-06-15,5,30000,25000\n"
        # STCL ignored (short-term — Sec 111A, not 112A)
        "INE005,SHORTTERMLOSS,2026-01-01,2026-05-01,5,10000,3000\n",
        encoding="utf-8",
    )
    adj = load_stocks_adjustment(flat_ltcg=None, ledger_path=csv_path, fy_label=FY)
    assert adj.realized_ltcg == 36_000  # 30k + 6k
    assert adj.realized_ltcl == 25_000  # 20k + 5k
    assert adj.net_ltcg == 11_000
    # All four LTCG-eligible rows kept (was a bug: pre-net-off code only kept
    # positive gains, hiding the offsetting losses)
    assert len(adj.lines) == 4


def test_loss_heavy_year_produces_negative_net(tmp_path):
    """User's real-world case: losses > gains → net negative → budget should
    expand by abs(net)."""
    csv_path = tmp_path / "stocks.csv"
    csv_path.write_text(
        "isin,symbol,buy_date,sell_date,quantity,buy_value,sell_value\n"
        "INE001,SMALLGAIN,2024-06-01,2026-06-15,1,100,200\n"
        "INE002,BIGLOSS,2024-06-01,2026-06-15,1,1000,200\n",
        encoding="utf-8",
    )
    adj = load_stocks_adjustment(flat_ltcg=None, ledger_path=csv_path, fy_label=FY)
    assert adj.realized_ltcg == 100
    assert adj.realized_ltcl == 800
    assert adj.net_ltcg == -700


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
