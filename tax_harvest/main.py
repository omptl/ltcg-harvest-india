"""CLI entry point for the tax-harvest tool.

Usage:
    tax-harvest path/to/cas.pdf [--fy 2026-27] [--already-realized 0]
                                 [--carry-forward-loss 0] [--no-cache]
                                 [--password $CAS_PWD]
"""

from __future__ import annotations

import argparse
import getpass
import sys
from datetime import date
from pathlib import Path

from rich.console import Console

from .harvest import build_plan
from .lots import evaluate_lots
from .loss_harvest import find_loss_candidates
from .nav import load_nav_index
from .parser import parse_cas
from .report import render_plan, write_json_report
from .models import SchemeCategory


def cli(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    console = Console()

    fy_label = args.fy or _current_fy_label(date.today())

    password = args.password or getpass.getpass("CAS PDF password: ")
    try:
        cas = parse_cas(args.cas_pdf, password)
    except RuntimeError as exc:
        console.print(f"[red]Error:[/] {exc}")
        return 2

    if not cas.schemes:
        console.print("[yellow]No schemes found in CAS. Is this an empty statement?[/]")
        return 1

    nav_index = load_nav_index(force_refresh=args.no_cache)

    warnings: list[str] = []
    if nav_index.snapshot_date:
        warnings.append(f"NAVs from AMFI snapshot dated {nav_index.snapshot_date}")
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

    evaluations = evaluate_lots(cas.schemes, nav_lookup=nav_index.lookup, today=date.today())

    if nav_index.unmatched:
        for name in sorted(set(nav_index.unmatched)):
            warnings.append(f"NAV not matched on AMFI feed: {name}")

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
