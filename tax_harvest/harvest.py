"""Core harvesting algorithm.

Given a list of LotEvaluation objects and a target LTCG budget, produce a HarvestPlan
that maximizes basis reset by greedily selecting lots with the highest gain-per-unit
first. A single fractional lot is allowed at the tail to land exactly on the budget.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from .models import HarvestPlan, LotEvaluation, PlanLine

LTCG_EXEMPTION_LIMIT = 125_000.0  # Section 112A, FY 2024-25 onwards


def build_plan(
    evaluations: Iterable[LotEvaluation],
    fy_label: str,
    already_realized_ltcg: float = 0.0,
    carry_forward_losses: float = 0.0,
    warnings: list[str] | None = None,
) -> HarvestPlan:
    """Greedily select lots to harvest until the effective LTCG budget is filled.

    A carry-forward LT loss increases the budget (extra harvestable gain that nets to
    the same taxable LTCG). Already-realized LTCG in this FY shrinks the budget.
    """
    evals = list(evaluations)

    effective_budget = max(
        0.0,
        LTCG_EXEMPTION_LIMIT - already_realized_ltcg + carry_forward_losses,
    )

    plan = HarvestPlan(
        fy_label=fy_label,
        budget_total=LTCG_EXEMPTION_LIMIT,
        already_realized_ltcg=already_realized_ltcg,
        carry_forward_losses=carry_forward_losses,
        effective_budget=effective_budget,
        warnings=warnings or [],
    )

    harvestable = [e for e in evals if e.is_harvestable]
    plan.excluded_lots = [e for e in evals if e.excluded_reason is not None]
    plan.loss_candidates = [e for e in evals
                            if e.excluded_reason is None and e.unrealized_gain <= 0]

    # Sort by gain_per_unit desc — maximizes basis reset for the same gain budget.
    harvestable.sort(key=lambda e: e.gain_per_unit, reverse=True)

    # Aggregate selected fractions per (folio, scheme, isin) so multiple lots in the
    # same scheme collapse into one redemption instruction.
    selected: dict[tuple[str, str, str | None], dict] = {}
    remaining = effective_budget
    total_harvested = 0.0

    for ev in harvestable:
        if remaining <= 1.0:  # less than 1 INR of budget — stop
            break
        if ev.gain_per_unit <= 0:
            continue

        # Full lot fits?
        if ev.unrealized_gain <= remaining + 1e-6:
            units = ev.lot.units_remaining
            gain = ev.unrealized_gain
        else:
            # Take the exact unit fraction that lands on `remaining`.
            units = remaining / ev.gain_per_unit
            # Round down to 4 decimal places — fund houses transact at 4dp.
            units = max(0.0, _floor_to(units, 4))
            gain = units * ev.gain_per_unit
            if units <= 0:
                continue

        key = (ev.scheme.folio, ev.scheme.scheme_name, ev.scheme.isin)
        bucket = selected.setdefault(key, {
            "scheme": ev.scheme,
            "current_nav": ev.current_nav,
            "units": 0.0,
            "gain": 0.0,
            "cost_basis": 0.0,
            "purchase_dates": [],
        })
        bucket["units"] += units
        bucket["gain"] += gain
        bucket["cost_basis"] += units * ev.lot.cost_per_unit
        bucket["purchase_dates"].append(ev.lot.purchase_date)

        remaining -= gain
        total_harvested += gain

    for bucket in selected.values():
        s = bucket["scheme"]
        plan.lines.append(PlanLine(
            scheme_name=s.scheme_name,
            folio=s.folio,
            amc=s.amc,
            isin=s.isin,
            units_to_redeem=round(bucket["units"], 4),
            estimated_ltcg=round(bucket["gain"], 2),
            current_nav=round(bucket["current_nav"], 4),
            cost_basis_redeemed=round(bucket["cost_basis"], 2),
            purchase_dates=sorted(set(bucket["purchase_dates"])),
        ))

    # Order plan lines by harvested gain desc for readability.
    plan.lines.sort(key=lambda ln: ln.estimated_ltcg, reverse=True)
    plan.total_ltcg_harvested = round(total_harvested, 2)
    plan.budget_remaining = round(max(0.0, remaining), 2)
    return plan


def _floor_to(value: float, decimals: int) -> float:
    factor = 10 ** decimals
    return int(value * factor) / factor
