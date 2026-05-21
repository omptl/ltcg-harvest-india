"""Tests for the harvesting algorithm."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from tax_harvest.harvest import LTCG_EXEMPTION_LIMIT, build_plan
from tax_harvest.lots import evaluate_lots
from tax_harvest.models import Scheme, SchemeCategory, Transaction, TxnType


TODAY = date(2026, 5, 21)
OLD = TODAY - timedelta(days=400)


def _scheme(name: str, txns: list[Transaction],
            category: SchemeCategory = SchemeCategory.EQUITY,
            folio: str = "F1") -> Scheme:
    return Scheme(folio=folio, scheme_name=name, amc="AMC", category=category,
                  transactions=txns, isin=f"ISIN-{name}")


def _txn(d: date, t: TxnType, units: float, nav: float) -> Transaction:
    return Transaction(date=d, txn_type=t, units=units, nav=nav, amount=units * nav)


def _evals(schemes, nav_map):
    return evaluate_lots(schemes, nav_lookup=lambda s: nav_map.get(s.isin), today=TODAY)


def test_plan_fills_budget_and_does_not_exceed_it():
    # Two equity lots, each with enough gain to over-fill the 1.25L budget on its own.
    s1 = _scheme("A", [_txn(OLD, TxnType.PURCHASE, 10_000, 50)])
    s2 = _scheme("B", [_txn(OLD, TxnType.PURCHASE, 10_000, 50)])
    evals = _evals([s1, s2], {"ISIN-A": 100.0, "ISIN-B": 150.0})

    plan = build_plan(evals, fy_label="2026-27")
    assert plan.total_ltcg_harvested <= LTCG_EXEMPTION_LIMIT + 1e-6
    assert plan.total_ltcg_harvested == pytest.approx(LTCG_EXEMPTION_LIMIT, rel=1e-4)


def test_already_realized_ltcg_shrinks_budget():
    s = _scheme("A", [_txn(OLD, TxnType.PURCHASE, 1000, 10)])
    evals = _evals([s], {"ISIN-A": 200.0})
    plan = build_plan(evals, fy_label="2026-27", already_realized_ltcg=50_000)
    assert plan.effective_budget == pytest.approx(75_000)
    assert plan.total_ltcg_harvested == pytest.approx(75_000, rel=1e-4)


def test_carry_forward_loss_expands_budget():
    s = _scheme("A", [_txn(OLD, TxnType.PURCHASE, 10000, 10)])
    evals = _evals([s], {"ISIN-A": 110.0})  # huge gain per unit
    plan = build_plan(evals, fy_label="2026-27", carry_forward_losses=25_000)
    assert plan.effective_budget == pytest.approx(150_000)
    assert plan.total_ltcg_harvested == pytest.approx(150_000, rel=1e-4)


def test_plan_prefers_higher_gain_per_unit_lot_first():
    s_lo = _scheme("LOW", [_txn(OLD, TxnType.PURCHASE, 10, 50)])
    s_hi = _scheme("HIGH", [_txn(OLD, TxnType.PURCHASE, 10, 10)])
    # Tiny budget: only one lot's-worth fits.
    evals = _evals([s_lo, s_hi], {"ISIN-LOW": 60.0, "ISIN-HIGH": 60.0})
    plan = build_plan(evals, fy_label="2026-27", already_realized_ltcg=124_400)
    # 600 INR budget; HIGH lot gain/unit=50, LOW lot gain/unit=10. We expect HIGH first.
    assert plan.lines and plan.lines[0].scheme_name == "HIGH"


def test_no_lots_means_empty_plan_but_no_crash():
    plan = build_plan([], fy_label="2026-27")
    assert plan.lines == []
    assert plan.total_ltcg_harvested == 0.0


def test_locked_lot_excluded_from_plan_and_listed():
    # ELSS lot less than 3 years old — should be excluded.
    recent = TODAY - timedelta(days=200)
    s = _scheme("ELSS Saver", [_txn(recent, TxnType.SIP, 100, 20)],
                category=SchemeCategory.ELSS)
    evals = _evals([s], {"ISIN-ELSS Saver": 80.0})
    plan = build_plan(evals, fy_label="2026-27")
    assert plan.lines == []
    assert plan.excluded_lots and "lock-in" in plan.excluded_lots[0].excluded_reason


def test_loss_lots_appear_as_candidates_not_in_plan():
    s_loss = _scheme("LOSER", [_txn(OLD, TxnType.PURCHASE, 100, 200)])
    s_gain = _scheme("WINNER", [_txn(OLD, TxnType.PURCHASE, 100, 50)])
    evals = _evals([s_loss, s_gain], {"ISIN-LOSER": 100.0, "ISIN-WINNER": 100.0})
    plan = build_plan(evals, fy_label="2026-27")
    plan_schemes = {ln.scheme_name for ln in plan.lines}
    assert "LOSER" not in plan_schemes
    assert any(c.scheme.scheme_name == "LOSER" for c in plan.loss_candidates)


def test_marginal_lot_truncated_to_exact_budget():
    # One large lot whose total gain far exceeds budget — verify we cut it precisely.
    s = _scheme("BIG", [_txn(OLD, TxnType.PURCHASE, 10_000, 100)])
    evals = _evals([s], {"ISIN-BIG": 200.0})  # gain/unit = 100
    plan = build_plan(evals, fy_label="2026-27")
    # 1.25L / 100 = 1250 units expected (4dp floor)
    assert plan.lines[0].units_to_redeem == pytest.approx(1250.0, abs=1e-3)
    assert plan.total_ltcg_harvested <= LTCG_EXEMPTION_LIMIT + 1e-6


def test_aggregates_multiple_lots_of_same_scheme_into_one_line():
    s = _scheme("MULTI", [
        _txn(OLD, TxnType.SIP, 10, 50),
        _txn(OLD - timedelta(days=30), TxnType.SIP, 10, 40),
        _txn(OLD - timedelta(days=60), TxnType.SIP, 10, 30),
    ])
    evals = _evals([s], {"ISIN-MULTI": 200.0})
    plan = build_plan(evals, fy_label="2026-27", already_realized_ltcg=120_000)
    lines_for_scheme = [l for l in plan.lines if l.scheme_name == "MULTI"]
    assert len(lines_for_scheme) == 1
    assert len(lines_for_scheme[0].purchase_dates) >= 1


def test_markdown_report_renders_safety_buffer_row(tmp_path):
    """When a safety buffer is applied, the Budget table must surface it as a
    distinct row and the rationale blockquote must explain the trade-off."""
    from tax_harvest.report import write_markdown_report

    s = _scheme("BUF", [_txn(OLD, TxnType.PURCHASE, 100, 100)])
    evals = _evals([s], {"ISIN-BUF": 1500.0})
    plan = build_plan(evals, fy_label="2026-27")

    out = write_markdown_report(plan, loss_candidates=[], report_dir=tmp_path,
                                 safety_buffer_pct=1.5,
                                 safety_buffer_amount=1875.0)
    body = out.read_text(encoding="utf-8")
    assert "Safety buffer @ 1.50%" in body
    assert "₹1,875.00" in body
    assert "no-overshoot" in body or "Indian MFs are end-of-day priced" in body


def test_markdown_report_omits_buffer_row_when_pct_zero(tmp_path):
    """Default path (no buffer) must not render the row to avoid noise."""
    from tax_harvest.report import write_markdown_report

    s = _scheme("NOBUF", [_txn(OLD, TxnType.PURCHASE, 100, 100)])
    evals = _evals([s], {"ISIN-NOBUF": 1500.0})
    plan = build_plan(evals, fy_label="2026-27")

    out = write_markdown_report(plan, loss_candidates=[], report_dir=tmp_path,
                                 safety_buffer_pct=0.0,
                                 safety_buffer_amount=0.0)
    body = out.read_text(encoding="utf-8")
    assert "Safety buffer" not in body


def test_markdown_report_renders_plan_action_block(tmp_path):
    """Markdown summary must call out the schemes to sell, units, and total LTCG."""
    from tax_harvest.report import write_markdown_report

    s = _scheme("HARVESTABLE", [_txn(OLD, TxnType.PURCHASE, 100, 100)])
    evals = _evals([s], {"ISIN-HARVESTABLE": 1500.0})
    plan = build_plan(evals, fy_label="2026-27")

    out = write_markdown_report(plan, loss_candidates=[], report_dir=tmp_path)
    assert out.exists() and out.suffix == ".md"
    body = out.read_text(encoding="utf-8")
    assert "FY 2026-27" in body
    assert "HARVESTABLE" in body
    assert "Total LTCG booked" in body
    # Cross-asset disclosure is load-bearing — without it users miss that stock
    # LTCG eats into the same ₹1.25 L bucket. Pin it so a future refactor can't
    # silently drop the warning.
    assert "listed equity shares" in body
    assert "--stocks-ltcg" in body


def test_json_report_does_not_embed_full_transaction_history_per_lot(tmp_path):
    """Regression: each excluded_lot used to re-embed the full Scheme including
    every transaction, blowing up the JSON to 100+MB on SIP-heavy portfolios."""
    from tax_harvest.report import write_json_report

    sip_dates = [OLD - timedelta(days=30 * i) for i in range(200)]
    s = _scheme("SIPPY", [_txn(d, TxnType.SIP, 1.0, 100.0) for d in sip_dates])
    evals = _evals([s], {"ISIN-SIPPY": 50.0})  # underwater → excluded as loss
    plan = build_plan(evals, fy_label="2026-27")

    out = write_json_report(plan, loss_candidates=[], report_dir=tmp_path)
    import json
    payload = json.loads(out.read_text(encoding="utf-8"))
    for ev in payload["plan"]["excluded_lots"]:
        assert "transactions" not in ev["scheme"], \
            "Scheme.transactions must be stripped from per-lot dumps to keep reports small"
