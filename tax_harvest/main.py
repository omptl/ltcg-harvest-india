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
from .report import render_plan, write_json_report


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

    plan = build_plan(
        evaluations,
        fy_label=fy_label,
        already_realized_ltcg=args.already_realized,
        carry_forward_losses=args.carry_forward_loss,
        warnings=warnings,
    )
    losses = find_loss_candidates(evaluations)

    render_plan(plan, losses, console=console)

    if not args.no_report:
        out = write_json_report(plan, losses)
        console.print(f"[dim]JSON report written to {out}[/]")

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
