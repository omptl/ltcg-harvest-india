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
from .stocks import StocksAdjustment
from .timing import RedemptionAdvisory, compute_advisory

DEFAULT_REPORT_DIR = Path("reports")  # cwd-relative; gitignored at repo root

DISCLAIMER = (
    "[bold yellow]Disclaimer:[/] for personal analysis only. Verify with a CA before "
    "transacting. NAV at execution will differ from NAV at analysis. Tax rules summarised "
    "here reflect Indian Income Tax Act as understood at build time; confirm latest "
    "provisions yourself."
)


def render_plan(plan: HarvestPlan, loss_candidates: list[LossCandidate],
                console: Console | None = None,
                advisory: RedemptionAdvisory | None = None) -> None:
    console = console or Console()

    if advisory and plan.lines:
        # Show the redemption-window advisory FIRST so the user sees it before
        # the action table. Color the border by status.
        color = "green" if advisory.status == "GREEN" else "yellow"
        body = advisory.headline + "\n\n" + "\n".join(f"• {d}" for d in advisory.details)
        console.print(Panel(body, title="Redemption window", border_style=color))

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


def write_markdown_report(plan: HarvestPlan, loss_candidates: list[LossCandidate],
                          report_dir: Path = DEFAULT_REPORT_DIR,
                          stocks: StocksAdjustment | None = None,
                          cli_already_realized: float | None = None,
                          advisory: RedemptionAdvisory | None = None,
                          safety_buffer_pct: float = 0.0,
                          safety_buffer_amount: float = 0.0) -> Path:
    """Write a one-page Markdown summary that a non-developer can act on.

    The JSON report carries the full state for programmatic use; this Markdown
    report carries the bottom line: what to sell, how much LTCG it books, what
    to spot-check, and the warnings worth knowing. Opens in any editor or
    GitHub viewer.

    `stocks` + `cli_already_realized` are optional; when present, the Budget
    table breaks `plan.already_realized_ltcg` into its constituent inputs
    (MF gains booked earlier in FY vs stocks LTCG vs CSV ledger) so the user
    can see why the budget shrank.
    """
    report_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = report_dir / f"harvest_summary_{plan.fy_label}_{ts}.md"
    out_path.write_text(
        _render_markdown(plan, loss_candidates, stocks=stocks,
                         cli_already_realized=cli_already_realized,
                         advisory=advisory,
                         safety_buffer_pct=safety_buffer_pct,
                         safety_buffer_amount=safety_buffer_amount),
        encoding="utf-8",
    )
    return out_path


def _render_markdown(plan: HarvestPlan, loss_candidates: list[LossCandidate],
                     stocks: StocksAdjustment | None = None,
                     cli_already_realized: float | None = None,
                     advisory: RedemptionAdvisory | None = None,
                     safety_buffer_pct: float = 0.0,
                     safety_buffer_amount: float = 0.0) -> str:
    lines: list[str] = []
    lines.append(f"# LTCG Harvest Plan — FY {plan.fy_label}")
    lines.append("")
    lines.append(f"_Generated {datetime.now().strftime('%Y-%m-%d %H:%M')} — "
                 "personal analysis only, verify with a CA before transacting._")
    lines.append("")

    # --- Redemption window (timing advisory) --------------------------------
    # Surfaced first because it changes whether the user should act now or
    # tomorrow, before they even look at the action table below.
    if advisory:
        emoji = "🟢" if advisory.status == "GREEN" else "🟡"
        lines.append(f"## {emoji} Redemption window — when to place the order")
        lines.append("")
        lines.append(f"**{advisory.headline}**")
        lines.append("")
        for d in advisory.details:
            lines.append(f"- {d}")
        lines.append("")

    # --- Budget block --------------------------------------------------------
    lines.append("## Budget")
    lines.append("")
    lines.append("| Item | Amount |")
    lines.append("| --- | ---: |")
    lines.append(f"| Sec 112A exemption (LTCG tax-free per FY) | ₹{plan.budget_total:,.2f} |")
    # If the caller broke `already_realized` into MF + stocks pieces, surface both
    # so the user can audit where the budget shrink came from. Otherwise show the
    # single rolled-up number.
    mf_realized = (cli_already_realized
                   if cli_already_realized is not None
                   else plan.already_realized_ltcg)
    if stocks and not stocks.is_empty():
        lines.append(f"| MF LTCG already booked this FY (subtracted) | ₹{mf_realized:,.2f} |")
        lines.append(f"| Stocks LTCG booked this FY (added to pool) | ₹{stocks.realized_ltcg:,.2f} |")
        lines.append(f"| Stocks LTCL booked this FY (offsets pool) | −₹{stocks.realized_ltcl:,.2f} |")
        sign = "subtracted" if stocks.net_ltcg >= 0 else "EXPANDS budget"
        lines.append(f"| **Net stocks position** ({sign}) | **₹{stocks.net_ltcg:,.2f}** |")
    else:
        lines.append(f"| Already realised LTCG this FY (subtracted) | ₹{plan.already_realized_ltcg:,.2f} |")
    lines.append(f"| Carry-forward LTCL from prior FYs (added) | ₹{plan.carry_forward_losses:,.2f} |")
    if safety_buffer_amount > 0:
        lines.append(
            f"| Safety buffer @ {safety_buffer_pct:.2f}% (held back, no-overshoot guarantee) "
            f"| −₹{safety_buffer_amount:,.2f} |"
        )
    lines.append(f"| **Effective budget for this plan** | **₹{plan.effective_budget:,.2f}** |")
    lines.append("")
    if safety_buffer_amount > 0:
        lines.append(
            f"> **Safety buffer rationale**: Indian MFs are end-of-day priced; your "
            f"redemption transacts at a closing NAV that's not yet known. Holding "
            f"₹{safety_buffer_amount:,.2f} (~{safety_buffer_pct:.2f}% of base headroom) "
            f"back absorbs a typical mid-cap intraday move and guarantees the booked "
            f"LTCG stays under ₹1.25 L even if NAV ticks up between plan time and "
            f"execution. Trade-off: this much exemption goes unused unless you do a "
            f"top-up redemption tomorrow against the now-known NAV."
        )
        lines.append("")
    lines.append("> The ₹1.25 L Sec 112A exemption is **shared across listed equity shares, "
                 "equity mutual fund units, and equity business-trust units**. If you also "
                 "book stock LTCG this FY, pass `--stocks-ltcg <amount>` (or a CSV via "
                 "`--stocks-ledger`) so this plan shrinks to fit the remaining headroom.")
    lines.append("")

    # --- Action block --------------------------------------------------------
    lines.append("## What to sell")
    lines.append("")
    if not plan.lines:
        lines.append("_No eligible lots to harvest under the current budget._")
        lines.append("")
    else:
        lines.append("| # | Scheme | Folio | AMC | Units to sell | NAV | Cost basis | Est. proceeds | Est. LTCG booked |")
        lines.append("| ---: | --- | --- | --- | ---: | ---: | ---: | ---: | ---: |")
        for i, l in enumerate(plan.lines, 1):
            proceeds = l.units_to_redeem * l.current_nav
            lines.append(
                f"| {i} | {l.scheme_name} | `{l.folio}` | {l.amc} "
                f"| **{l.units_to_redeem:,.4f}** | ₹{l.current_nav:,.4f} "
                f"| ₹{l.cost_basis_redeemed:,.2f} | ₹{proceeds:,.2f} "
                f"| **₹{l.estimated_ltcg:,.2f}** |"
            )
        lines.append("")
        lines.append(f"**Total LTCG booked: ₹{plan.total_ltcg_harvested:,.2f}** "
                     f"&nbsp; · &nbsp; Budget remaining: ₹{plan.budget_remaining:,.2f}")
        lines.append("")

    # --- How to execute ------------------------------------------------------
    if plan.lines:
        lines.append("## How to execute")
        lines.append("")
        lines.append("1. Place redemption orders for the exact unit counts above "
                     "(AMC portals accept 4-decimal precision).")
        lines.append("2. After settlement (T+2 / T+3), reinvest the proceeds into the "
                     "**same scheme** or any equity fund — this resets your cost basis "
                     "higher so the next year's harvest works on the new base.")
        lines.append("3. Total LTCG booked is at or just under ₹1.25 L → falls inside "
                     "the Sec 112A exemption → **zero tax** on this realisation.")
        lines.append("4. NAV at execution will differ from the NAV in this plan; the "
                     "booked LTCG will shift by a few hundred rupees in either direction.")
        lines.append("")

    # --- Spot-check ---------------------------------------------------------
    if plan.lines:
        lines.append("## Spot-check before you click Sell")
        lines.append("")
        for l in plan.lines:
            avg_cost = l.cost_basis_redeemed / l.units_to_redeem if l.units_to_redeem else 0
            lines.append(
                f"- **{l.scheme_name}** (folio `{l.folio}`): confirm on your AMC portal "
                f"that you hold at least **{l.units_to_redeem:,.4f} units**. "
                f"Average cost in this plan = ₹{avg_cost:,.2f}/unit."
            )
        lines.append("")

    # --- Stocks-side detail (read-only) -------------------------------------
    if stocks and stocks.lines:
        lines.append("## Stocks LTCG / LTCL folded into this FY's Sec 112A pool")
        lines.append("")
        lines.append("Per the Sec 112A rule, current-FY long-term gains and losses on "
                     "listed equity / equity MF / business-trust units are netted before "
                     "the ₹1.25 L exemption applies. Negative net → extra MF harvest "
                     "headroom this FY. The tool does not recommend stock buys or sells — "
                     "it only reads what you've already booked.")
        lines.append("")
        lines.append("| Symbol | ISIN | Buy | Sell | Qty | Buy value | Sell value | LTCG / (LTCL) |")
        lines.append("| --- | --- | --- | --- | ---: | ---: | ---: | ---: |")
        for ln in stocks.lines:
            gain_disp = (f"**₹{ln.gain:,.2f}**" if ln.gain >= 0
                         else f"_(₹{-ln.gain:,.2f})_")
            lines.append(
                f"| {ln.symbol} | {ln.isin} | {ln.buy_date.isoformat()} "
                f"| {ln.sell_date.isoformat()} | {ln.quantity:g} "
                f"| ₹{ln.buy_value:,.2f} | ₹{ln.sell_value:,.2f} "
                f"| {gain_disp} |"
            )
        lines.append(
            f"| | | | | | | **LTCG total** | **₹{stocks.realized_ltcg:,.2f}** |"
        )
        lines.append(
            f"| | | | | | | **LTCL total** | **(₹{stocks.realized_ltcl:,.2f})** |"
        )
        lines.append(
            f"| | | | | | | **Net** | **₹{stocks.net_ltcg:,.2f}** |"
        )
        lines.append("")

    # --- Loss candidates -----------------------------------------------------
    if loss_candidates:
        lines.append("## Loss-harvesting candidates (optional)")
        lines.append("")
        lines.append("These lots are currently underwater. Booking the loss creates a "
                     "capital loss you can set off against this FY's capital gains, or "
                     "carry forward up to 8 FYs. **Not** part of the ₹1.25 L plan above.")
        lines.append("")
        lines.append("| Scheme | Folio | Purchase | Units | Loss | Type |")
        lines.append("| --- | --- | --- | ---: | ---: | --- |")
        for c in loss_candidates[:10]:
            ev = c.evaluation
            lines.append(
                f"| {ev.scheme.scheme_name} | `{ev.scheme.folio}` "
                f"| {ev.lot.purchase_date.isoformat()} | {ev.lot.units_remaining:,.4f} "
                f"| ₹{ev.unrealized_gain:,.2f} | {c.loss_type} |"
            )
        if len(loss_candidates) > 10:
            lines.append(f"| _…and {len(loss_candidates) - 10} more in the JSON report_ | | | | | |")
        lines.append("")

    # --- Warnings ------------------------------------------------------------
    if plan.warnings:
        lines.append("## Warnings to review")
        lines.append("")
        for w in plan.warnings:
            lines.append(f"- {w}")
        lines.append("")

    # --- Disclaimer ----------------------------------------------------------
    lines.append("---")
    lines.append("")
    lines.append("**Disclaimer**: This is automated analysis from your own CAS PDF "
                 "running locally — not tax advice. Tax rules summarised here reflect "
                 "the Indian Income Tax Act as understood at build time (post-Budget "
                 "2024). Confirm with a CA before transacting, and re-check NAV at "
                 "execution.")
    lines.append("")
    return "\n".join(lines)


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
