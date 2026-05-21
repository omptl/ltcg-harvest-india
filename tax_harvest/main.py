"""CLI entry point for the tax-harvest tool.

Usage:
    tax-harvest path/to/cas.pdf [--fy 2026-27] [--already-realized 0]
                                 [--carry-forward-loss 0] [--no-cache]
                                 [--password $CAS_PWD]
                                 [--nri] [--joint-holdings]
                                 [--overrides path/to/file.json]
                                 [--suspended path/to/file.json]
                                 [--equity-exit-load-days 365]
                                 [--no-grandfathering]
"""

from __future__ import annotations

import argparse
import getpass
import sys
from datetime import date
from pathlib import Path

from rich.console import Console

from .classifier import load_overrides, load_suspended_isins
from .fmv_2018 import load_fmv_index
from .harvest import build_plan
from .lots import evaluate_lots
from .loss_harvest import find_loss_candidates
from .models import SchemeCategory
from .nav import load_nav_index
from .parser import parse_cas
from .report import render_plan, write_json_report, write_markdown_report
from .stocks import load_stocks_adjustment
from .timing import compute_advisory


def cli(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    console = Console()

    fy_label = args.fy or _current_fy_label(date.today())

    try:
        overrides = load_overrides(extra_file=args.overrides)
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[red]Overrides error:[/] {exc}")
        return 2

    try:
        suspended = load_suspended_isins(extra_file=args.suspended)
    except FileNotFoundError as exc:
        console.print(f"[red]Suspended-schemes file error:[/] {exc}")
        return 2

    try:
        stocks = load_stocks_adjustment(
            flat_ltcg=args.stocks_ltcg,
            flat_ltcl=args.stocks_ltcl,
            ledger_path=args.stocks_ledger,
            fy_label=fy_label,
        )
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[red]Stocks ledger error:[/] {exc}")
        return 2

    password = args.password or getpass.getpass("CAS PDF password: ")
    try:
        cas = parse_cas(args.cas_pdf, password,
                        overrides=overrides, suspended_isins=suspended)
    except RuntimeError as exc:
        console.print(f"[red]Error:[/] {exc}")
        return 2

    if not cas.schemes:
        console.print("[yellow]No schemes found in CAS. Is this an empty statement?[/]")
        return 1

    if args.nri:
        cas.is_nri = True
    if args.joint_holdings:
        cas.has_joint_holdings = True

    nav_index = load_nav_index(force_refresh=args.no_cache)

    fmv_index = None
    if not args.no_grandfathering:
        fmv_index = load_fmv_index(force_refresh=args.refresh_fmv)
        if fmv_index.snapshot_date is None:
            console.print(
                "[yellow]Note:[/] 31-Jan-2018 FMV snapshot could not be loaded — "
                "pre-2018 equity lots will use actual cost (gain may be overstated)."
            )

    warnings: list[str] = []
    if nav_index.snapshot_date:
        warnings.append(f"NAVs from AMFI snapshot dated {nav_index.snapshot_date}")
    if fmv_index and fmv_index.snapshot_date:
        warnings.append(f"FMVs from 31-Jan-2018 snapshot ({fmv_index.snapshot_date})")
    if cas.is_nri:
        warnings.append("NRI status detected/asserted — TDS rules differ; verify with CA")
    if cas.has_joint_holdings:
        warnings.append("Joint holding(s) detected/asserted — confirm primary-holder tax liability")

    for s in cas.schemes:
        if s.category == SchemeCategory.UNKNOWN:
            warnings.append(f"Unclassified scheme — verify manually: {s.scheme_name}")
        if s.category == SchemeCategory.INTERNATIONAL:
            warnings.append(
                f"International/global FoF — confirm equity vs debt treatment for: {s.scheme_name}")
        if s.category == SchemeCategory.GOLD:
            warnings.append(
                f"Gold/silver scheme — confirm post-Budget-2024 treatment for: {s.scheme_name}")
        if s.is_demat:
            warnings.append(f"Demat-held units may be missing from CAS for: {s.scheme_name}")
        if s.is_suspended:
            warnings.append(f"Known suspended/wound-up scheme: {s.scheme_name}")

    evaluations = evaluate_lots(
        cas.schemes,
        nav_lookup=nav_index.lookup,
        today=date.today(),
        fmv_lookup=(fmv_index.lookup if fmv_index else None),
        equity_exit_load_days=args.equity_exit_load_days,
    )

    if nav_index.unmatched:
        for name in sorted(set(nav_index.unmatched)):
            warnings.append(f"NAV not matched on AMFI feed: {name}")
    if fmv_index and fmv_index.unmatched:
        for name in sorted(set(fmv_index.unmatched)):
            warnings.append(f"31-Jan-2018 FMV not matched (pre-2018 equity lot): {name}")

    # Dedupe while preserving first-seen order. The per-scheme loop above emits the
    # same warning string once per folio holding the scheme — collapse to a single
    # line so the warnings panel stays readable.
    seen: set[str] = set()
    warnings = [w for w in warnings if not (w in seen or seen.add(w))]

    # Stocks LTCG (if any provided) folds into the same Sec 112A bucket as MF LTCG.
    # The ₹1.25 L exemption is aggregate across listed shares + equity MF + business
    # trust units — see PROJECT_OVERVIEW §"Tax-rule cheat sheet".
    #
    # Per the same rule, current-FY LTCL is set off against current-FY LTCG BEFORE
    # the exemption applies. So we use the NET figure: positive net shrinks the
    # budget (already-realized); negative net (loss-heavy stock year) expands the
    # budget (treat as bonus carry-forward equivalent since the loss can absorb
    # this FY's MF harvest gains tax-free before the exemption is even touched).
    stocks_net = stocks.net_ltcg
    effective_already_realized = args.already_realized + max(0.0, stocks_net)
    effective_carry_forward = args.carry_forward_loss + max(0.0, -stocks_net)
    if not stocks.is_empty():
        warnings.append(
            f"Stocks LTCG ₹{stocks.realized_ltcg:,.2f} / LTCL ₹{stocks.realized_ltcl:,.2f} "
            f"→ net ₹{stocks_net:,.2f} folded into the Sec 112A budget"
        )
        for src in stocks.sources:
            warnings.append(f"  source — {src}")

    plan = build_plan(
        evaluations,
        fy_label=fy_label,
        already_realized_ltcg=effective_already_realized,
        carry_forward_losses=effective_carry_forward,
        warnings=warnings,
    )
    losses = find_loss_candidates(evaluations)

    # Redemption-window advisory uses real wall-clock time in IST and the NAV
    # snapshot date from the AMFI feed to tell the user whether to act now or
    # rerun tomorrow against a fresher NAV.
    advisory = compute_advisory(nav_index.snapshot_date)

    render_plan(plan, losses, console=console, advisory=advisory)

    if not args.no_report:
        out = write_json_report(plan, losses)
        console.print(f"[dim]JSON report written to {out}[/]")
        md_out = write_markdown_report(plan, losses, stocks=stocks,
                                       cli_already_realized=args.already_realized,
                                       advisory=advisory)
        console.print(f"[dim]Markdown summary written to {md_out}[/]")

    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="tax-harvest",
        description="Personal LTCG harvesting plan for Indian mutual fund investors.",
    )
    p.add_argument("cas_pdf", type=Path, help="Path to CAS PDF (CAMS/KFintech/MF Central).")
    p.add_argument("--fy", default=None,
                   help="Financial year label, e.g. 2026-27. Defaults to current FY.")
    p.add_argument("--password", default=None,
                   help="CAS PDF password. Omit to be prompted (recommended).")
    p.add_argument("--already-realized", type=float, default=0.0,
                   help="LTCG already booked this FY (reduces budget).")
    p.add_argument("--carry-forward-loss", type=float, default=0.0,
                   help="Carry-forward LT capital losses (increases budget).")
    p.add_argument("--no-cache", action="store_true",
                   help="Force AMFI NAV refresh even if cache is fresh.")
    p.add_argument("--no-report", action="store_true",
                   help="Skip writing a JSON report file.")
    p.add_argument("--nri", action="store_true",
                   help="Assert NRI status even if heuristic didn't pick it up.")
    p.add_argument("--joint-holdings", action="store_true",
                   help="Assert joint-holding presence even if heuristic missed it.")
    p.add_argument("--overrides", type=Path, default=None,
                   help="Path to JSON file mapping ISIN -> SchemeCategory overrides.")
    p.add_argument("--suspended", type=Path, default=None,
                   help="Path to JSON file listing additional suspended/wound-up ISINs.")
    p.add_argument("--equity-exit-load-days", type=int, default=365,
                   help="Days under which an equity lot is assumed to attract exit load.")
    p.add_argument("--stocks-ltcg", type=float, default=None,
                   help="Flat stocks LTCG (Rs, positive) already booked this FY — paste "
                        "the total from your broker's tax P&L. Sec 112A pools this with "
                        "MF LTCG before the ₹1.25L exemption.")
    p.add_argument("--stocks-ltcl", type=float, default=None,
                   help="Flat stocks LTCL (Rs, positive number for losses) already booked "
                        "this FY. Sets off against current-FY LTCG before the exemption, "
                        "so a loss-heavy stocks year can EXPAND the MF harvest budget.")
    p.add_argument("--stocks-ledger", type=Path, default=None,
                   help="Path to a CSV file of stock sells. Columns: isin, symbol, "
                        "buy_date, sell_date, quantity, buy_value, sell_value. Tool "
                        "filters by FY (on sell_date), keeps only LTCG-eligible (>365d) "
                        "rows, sums gains and losses separately, nets them, folds into "
                        "the budget.")
    p.add_argument("--no-grandfathering", action="store_true",
                   help="Skip Sec 112A grandfathering for pre-2018 equity lots.")
    p.add_argument("--refresh-fmv", action="store_true",
                   help="Force re-fetch of the 31-Jan-2018 FMV snapshot.")
    return p.parse_args(argv)


def _current_fy_label(today: date) -> str:
    """Indian FY: Apr 1 to Mar 31. FY 2026-27 = Apr 1 2026 .. Mar 31 2027."""
    if today.month >= 4:
        start, end = today.year, today.year + 1
    else:
        start, end = today.year - 1, today.year
    return f"{start}-{str(end)[-2:]}"


if __name__ == "__main__":
    sys.exit(cli())
