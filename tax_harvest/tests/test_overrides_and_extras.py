"""Tests for ISIN overrides, suspended-scheme handling, NRI/joint detection,
and configurable exit-load."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from tax_harvest.classifier import (
    classify_scheme,
    load_overrides,
    load_suspended_isins,
)
from tax_harvest.lots import evaluate_lots
from tax_harvest.models import Scheme, SchemeCategory, Transaction, TxnType
from tax_harvest.parser import _from_casparser_dict


TODAY = date(2026, 5, 21)


def _txn(d: date, t: TxnType, units: float, nav: float) -> Transaction:
    return Transaction(date=d, txn_type=t, units=units, nav=nav, amount=units * nav)


# --- ISIN overrides ---------------------------------------------------------

def test_override_beats_name_heuristic():
    # Name would classify as equity; override forces debt.
    s = Scheme(folio="F", scheme_name="Some Equity Fund", amc="A",
               isin="INF000XYZ001")
    overrides = {"INF000XYZ001": SchemeCategory.DEBT_PRE_APR_2023}
    assert classify_scheme(s, overrides=overrides) == SchemeCategory.DEBT_PRE_APR_2023


def test_override_ignored_when_isin_missing():
    s = Scheme(folio="F", scheme_name="Some Equity Fund", amc="A", isin=None)
    overrides = {"INF000XYZ001": SchemeCategory.DEBT_PRE_APR_2023}
    assert classify_scheme(s, overrides=overrides) == SchemeCategory.EQUITY


def test_load_overrides_from_file(tmp_path: Path):
    f = tmp_path / "ov.json"
    f.write_text(json.dumps({"overrides": {"INF000A": "equity", "INF000B": "elss"}}))
    out = load_overrides(extra_file=f)
    assert out["INF000A"] == SchemeCategory.EQUITY
    assert out["INF000B"] == SchemeCategory.ELSS


def test_load_overrides_rejects_invalid_category(tmp_path: Path):
    f = tmp_path / "ov.json"
    f.write_text(json.dumps({"overrides": {"INF000A": "nope_not_real"}}))
    with pytest.raises(ValueError, match="Invalid category"):
        load_overrides(extra_file=f)


def test_load_overrides_accepts_bare_dict(tmp_path: Path):
    f = tmp_path / "ov.json"
    f.write_text(json.dumps({"INF000A": "arbitrage"}))
    out = load_overrides(extra_file=f)
    assert out["INF000A"] == SchemeCategory.ARBITRAGE


# --- Suspended schemes ------------------------------------------------------

def test_suspended_lot_excluded_even_when_nav_present():
    old = TODAY - timedelta(days=800)
    s = Scheme(folio="F", scheme_name="Wound Up Fund", amc="A",
               category=SchemeCategory.EQUITY, isin="INF999W",
               is_suspended=True,
               transactions=[_txn(old, TxnType.PURCHASE, 100, 10)])
    evals = evaluate_lots([s], nav_lookup=lambda _s: 100.0, today=TODAY)
    assert evals[0].excluded_reason and "suspended" in evals[0].excluded_reason.lower()


def test_suspended_lot_message_when_no_nav():
    old = TODAY - timedelta(days=800)
    s = Scheme(folio="F", scheme_name="Wound Up Fund", amc="A",
               category=SchemeCategory.EQUITY, isin="INF999W",
               is_suspended=True,
               transactions=[_txn(old, TxnType.PURCHASE, 100, 10)])
    evals = evaluate_lots([s], nav_lookup=lambda _s: None, today=TODAY)
    assert evals[0].excluded_reason and "suspended" in evals[0].excluded_reason.lower()


def test_missing_nav_alone_excludes_with_verification_hint():
    old = TODAY - timedelta(days=800)
    s = Scheme(folio="F", scheme_name="Mystery Fund", amc="A",
               category=SchemeCategory.EQUITY, isin="INF999M",
               transactions=[_txn(old, TxnType.PURCHASE, 100, 10)])
    evals = evaluate_lots([s], nav_lookup=lambda _s: None, today=TODAY)
    assert evals[0].excluded_reason and "AMFI" in evals[0].excluded_reason


def test_load_suspended_isins_from_user_file(tmp_path: Path):
    f = tmp_path / "sus.json"
    f.write_text(json.dumps({"suspended": {"INF111": "test wound up"}}))
    out = load_suspended_isins(extra_file=f)
    assert "INF111" in out


# --- NRI / joint-holding detection in parser --------------------------------

def test_parser_detects_nri_from_investor_address():
    raw = {
        "investor_info": {"name": "X", "address": "Resident: NRI account holder, USA"},
        "folios": [],
    }
    cas = _from_casparser_dict(raw)
    assert cas.is_nri is True


def test_parser_detects_joint_holding_from_folio_text():
    raw = {
        "investor_info": {"name": "X", "address": "Mumbai"},
        "folios": [{
            "folio": "F1",
            "amc": "A",
            "mode_of_holding": "Anyone or Survivor",
            "schemes": [],
        }],
    }
    cas = _from_casparser_dict(raw)
    assert cas.has_joint_holdings is True


def test_parser_no_false_positive_for_plain_resident():
    raw = {
        "investor_info": {"name": "X", "address": "Resident of Bengaluru"},
        "folios": [{"folio": "F", "amc": "A", "schemes": []}],
    }
    cas = _from_casparser_dict(raw)
    assert cas.is_nri is False
    assert cas.has_joint_holdings is False


# --- Configurable exit-load window -----------------------------------------

def test_exit_load_window_configurable_to_zero_disables_check():
    # A 14-day-old equity lot with the default 365-day window is excluded for exit load
    # AND for holding-period (since <365d). With window=0 the exit-load test is bypassed,
    # but the holding-period check still excludes it. We just verify the exit_load flag.
    recent = TODAY - timedelta(days=14)
    s = Scheme(folio="F", scheme_name="Recent Equity", amc="A",
               category=SchemeCategory.EQUITY, isin="INF000R",
               transactions=[_txn(recent, TxnType.PURCHASE, 100, 10)])
    default = evaluate_lots([s], nav_lookup=lambda _s: 20.0, today=TODAY)
    zero_window = evaluate_lots([s], nav_lookup=lambda _s: 20.0,
                                 today=TODAY, equity_exit_load_days=0)
    assert default[0].has_exit_load is True
    assert zero_window[0].has_exit_load is False
