"""Output formatting: rich tables to the console and JSON reports to disk."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .loss_harvest import LossCandidate
from .models import HarvestPlan

DEFAULT_REPORT_DIR = Path("reports")  # cwd-relative; gitignored at repo root

DISCLAIMER = (
    "[bold yellow]Disclaimer:[/] for personal analysis only. Verify with a CA before "
    "transacting. NAV at execution will differ from NAV at analysis. Tax rules summarised "
    "here reflect Indian Income Tax Act as understood at build time; confirm latest "
    "provisions yourself."
)


def render_plan(plan: HarvestPlan, loss_candidates: list[LossCandidate],
                console: Console | None = None) -> None:
    console = console or Console()

    header = Table.grid(expand=True)
    header.add_column(justify="left")
    header.add_column(justify="right")
    header.add_row(
        f"[bold]LTCG Harvesting Plan — FY {plan.fy_label}[/]",
        f"₹1.25L exempt limit (Sec 112A)",
    )
    header.add_row(
        f"Already realized LTCG: ₹{plan.already_realized_ltcg:,.2f}    "
        f"Carry-forward LTCL: ₹{plan.carry_forward_losses:,.2f}",
        f"[bold]Effective budget: ₹{plan.effective_budget:,.2f}[/]",
    )
    console.print(Panel(header, border_style="cyan"))

    if not plan.lines:
        console.print("[yellow]No eligible lots to harvest under the current budget.[/]")
    else:
        t = Table(title="Recommended Redemptions", show_lines=False, expand=True)
        t.add_column("Scheme", overflow="fold")
        t.add_column("Folio")
        t.add_column("AMC", overflow="fold")
        t.add_column("Units", justify="right")
        t.add_column("NAV", justify="right")
        t.add_column("Cost basis", justify="right")
        t.add_column("Est. LTCG", justify="right", style="green")
        for line in plan.lines:
            t.add_row(
                line.scheme_name,
                line.folio,
                line.amc,
                f"{line.units_to_redeem:,.4f}",
                f"{line.current_nav:,.4f}",
                f"₹{line.cost_basis_redeemed:,.0f}",
                f"₹{line.estimated_ltcg:,.0f}",
            )
        console.print(t)

    summary = Table.grid(expand=True)
    summary.add_column(justify="left")
    summary.add_column(justify="right")
    summary.add_row(
        f"[bold]Total LTCG harvested:[/] ₹{plan.total_ltcg_harvested:,.2f}",
        f"[bold]Budget remaining:[/] ₹{plan.budget_remaining:,.2f}",
    )
    console.print(summary)

    if plan.warnings:
        console.print(Panel(
            "\n".join(f"• {w}" for w in plan.warnings),
            title="Warnings", border_style="yellow"))

    if plan.grandfathered_lots:
        gt = Table(title="Sec 112A Grandfathering Applied (pre-2018 equity lots)",
                   show_lines=False, expand=True)
        gt.add_column("Scheme", overflow="fold")
        gt.add_column("Purchase", justify="right")
        gt.add_column("Units", justify="right")
        gt.add_column("Actual cost/u", justify="right")
        gt.add_column("Effective cost/u", justify="right")
        gt.add_column("Note", overflow="fold")
        for ev in plan.grandfathered_lots:
            gt.add_row(
                ev.scheme.scheme_name,
                ev.lot.purchase_date.isoformat(),
                f"{ev.lot.units_remaining:,.4f}",
                f"₹{ev.lot.cost_per_unit:,.4f}",
                f"₹{(ev.effective_cost_per_unit or ev.lot.cost_per_unit):,.4f}",
                ev.grandfathering_note or "",
            )
        console.print(gt)

    if loss_candidates:
        lt = Table(title="Loss-Harvesting Candidates (review separately)",
                   show_lines=False, expand=True)
        lt.add_column("Scheme", overflow="fold")
        lt.add_column("Folio")
        lt.add_column("Purchase", justify="right")
        lt.add_column("Units", justify="right")
        lt.add_column("Cost/unit", justify="right")
        lt.add_column("NAV", justify="right")
        lt.add_column("Loss", justify="right", style="red")
        lt.add_column("Type")
        lt.add_column("Notes", overflow="fold")
        for c in loss_candidates[:50]:
            ev = c.evaluation
            lt.add_row(
                ev.scheme.scheme_name,
                ev.scheme.folio,
                ev.lot.purchase_date.isoformat(),
                f"{ev.lot.units_remaining:,.4f}",
                f"{ev.lot.cost_per_unit:,.4f}",
                f"{ev.current_nav:,.4f}",
                f"₹{ev.unrealized_gain:,.0f}",
                c.loss_type,
                c.notes,
            )
        console.print(lt)

    if plan.excluded_lots:
        et = Table(title="Excluded Lots (top 30 by would-be gain)",
                   show_lines=False, expand=True)
        et.add_column("Scheme", overflow="fold")
        et.add_column("Purchase", justify="right")
        et.add_column("Units", justify="right")
        et.add_column("Would-be gain", justify="right")
        et.add_column("Reason", overflow="fold")
        sorted_excl = sorted(plan.excluded_lots,
                             key=lambda e: e.unrealized_gain, reverse=True)
        for ev in sorted_excl[:30]:
            et.add_row(
                ev.scheme.scheme_name,
                ev.lot.purchase_date.isoformat(),
                f"{ev.lot.units_remaining:,.4f}",
                f"₹{ev.unrealized_gain:,.0f}",
                ev.excluded_reason or "",
            )
        console.print(et)

    console.print(DISCLAIMER)


def write_json_report(plan: HarvestPlan, loss_candidates: list[LossCandidate],
                      report_dir: Path = DEFAULT_REPORT_DIR) -> Path:
    """Write a timestamped JSON copy of the plan. Returns the path written."""
    report_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = report_dir / f"harvest_plan_{plan.fy_label}_{ts}.json"
    plan_dump = plan.model_dump(mode="json")
    # Strip the embedded scheme.transactions from each LotEvaluation in the
    # excluded_lots / loss_candidates / grandfathered_lots lists. The full
    # transaction history is already available via the source CAS and replaying
    # the entire SIP chain inside every excluded lot blows the report up to
    # 100MB+ on a heavily-SIP'd portfolio.
    for key in ("excluded_lots", "loss_candidates", "grandfathered_lots"):
        for ev in plan_dump.get(key, []) or []:
            scheme = ev.get("scheme")
            if isinstance(scheme, dict):
                scheme.pop("transactions", None)
    payload = {
        "plan": plan_dump,
        "loss_candidates": [
            {
                "loss_type": c.loss_type,
                "notes": c.notes,
                "scheme": c.evaluation.scheme.scheme_name,
                "folio": c.evaluation.scheme.folio,
                "purchase_date": c.evaluation.lot.purchase_date.isoformat(),
                "units_remaining": c.evaluation.lot.units_remaining,
                "cost_per_unit": c.evaluation.lot.cost_per_unit,
                "current_nav": c.evaluation.current_nav,
                "unrealized_loss": c.evaluation.unrealized_gain,
            }
            for c in loss_candidates
        ],
    }
    out_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return out_path
