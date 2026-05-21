"""Optional stocks LTCG adjustment to the Sec 112A budget.

The Sec 112A ₹1.25 lakh exemption is **aggregate** across listed equity shares,
equity-oriented mutual fund units, and equity business-trust units. This module
loads stock-side realised LTCG so it can be subtracted from the mutual-fund
harvest budget the same way `--already-realized` already does for MF gains
booked earlier in the FY.

Two input shapes are supported (use either or both — they sum):

1. A flat number (`--stocks-ltcg AMT`) — paste the LTCG total from your
   broker's tax P&L. Easiest, source-agnostic.
2. A per-trade canonical CSV (`--stocks-ledger FILE`) with columns
   `isin, symbol, buy_date, sell_date, quantity, buy_value, sell_value`.
   The tool filters by FY (sell_date inside Apr 1 → Mar 31), keeps only
   LTCG-eligible rows (holding > 365d) with positive gain, and sums them.

This module is read-only on stocks — it never recommends a stock sell or buy.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path


@dataclass
class StockLine:
    isin: str
    symbol: str
    buy_date: date
    sell_date: date
    quantity: float
    buy_value: float
    sell_value: float

    @property
    def gain(self) -> float:
        return self.sell_value - self.buy_value

    @property
    def holding_days(self) -> int:
        return (self.sell_date - self.buy_date).days

    @property
    def is_ltcg(self) -> bool:
        return self.holding_days > 365


@dataclass
class StocksAdjustment:
    realized_ltcg: float = 0.0  # sum of positive long-term gains in current FY
    realized_ltcl: float = 0.0  # sum of long-term losses (as a POSITIVE number) in current FY
    lines: list[StockLine] = field(default_factory=list)  # per-trade detail when CSV provided
    sources: list[str] = field(default_factory=list)  # human-readable provenance

    @property
    def net_ltcg(self) -> float:
        """LTCG minus LTCL — the figure that gets compared to the ₹1.25 L exemption.

        Per Sec 112A, current-FY LTCL on listed equity / equity MF / business trust
        units is set off against current-FY LTCG of the same class **before** the
        ₹1.25 L exemption applies. Positive value reduces the available budget;
        negative value (net loss) creates extra budget headroom because it can
        absorb MF harvest gains tax-free.
        """
        return self.realized_ltcg - self.realized_ltcl

    def is_empty(self) -> bool:
        return self.realized_ltcg == 0 and self.realized_ltcl == 0 and not self.lines


def _fy_bounds(fy_label: str) -> tuple[date, date]:
    """Indian FY: Apr 1 → Mar 31. '2026-27' → (2026-04-01, 2027-03-31)."""
    start_year, _ = fy_label.split("-")
    sy = int(start_year)
    return date(sy, 4, 1), date(sy + 1, 3, 31)


def load_stocks_adjustment(flat_ltcg: float | None,
                           ledger_path: Path | None,
                           fy_label: str,
                           flat_ltcl: float | None = None) -> StocksAdjustment:
    """Combine flat-number and CSV inputs into a single StocksAdjustment.

    `flat_ltcl` is the absolute value of long-term capital losses booked on
    listed equity in the current FY — passed as a positive number.
    """
    adj = StocksAdjustment()
    if flat_ltcg:
        adj.realized_ltcg += float(flat_ltcg)
        adj.sources.append(f"--stocks-ltcg flat input: ₹{flat_ltcg:,.2f}")
    if flat_ltcl:
        adj.realized_ltcl += float(flat_ltcl)
        adj.sources.append(f"--stocks-ltcl flat input: ₹{flat_ltcl:,.2f}")
    if ledger_path is not None:
        sub = _load_ledger_csv(Path(ledger_path), fy_label)
        adj.realized_ltcg += sub.realized_ltcg
        adj.realized_ltcl += sub.realized_ltcl
        adj.lines.extend(sub.lines)
        adj.sources.extend(sub.sources)
    return adj


_REQUIRED_COLS = ("isin", "symbol", "buy_date", "sell_date", "quantity", "buy_value", "sell_value")


def _load_ledger_csv(path: Path, fy_label: str) -> StocksAdjustment:
    if not path.exists():
        raise FileNotFoundError(f"Stocks ledger not found: {path}")
    fy_start, fy_end = _fy_bounds(fy_label)
    adj = StocksAdjustment()
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        header = {(n or "").strip() for n in (reader.fieldnames or [])}
        missing = [c for c in _REQUIRED_COLS if c not in header]
        if missing:
            raise ValueError(
                f"Stocks ledger {path} missing required column(s): {missing}. "
                f"Required columns: {list(_REQUIRED_COLS)}"
            )
        for row_no, raw in enumerate(reader, start=2):
            row = {k.strip(): (v or "").strip() for k, v in raw.items()}
            if not row.get("sell_date"):
                continue  # blank / open position — ignore
            try:
                line = StockLine(
                    isin=row["isin"],
                    symbol=row["symbol"],
                    buy_date=_parse_date(row["buy_date"]),
                    sell_date=_parse_date(row["sell_date"]),
                    quantity=float(row["quantity"]),
                    buy_value=float(row["buy_value"]),
                    sell_value=float(row["sell_value"]),
                )
            except (ValueError, KeyError) as exc:
                raise ValueError(f"Stocks ledger {path} row {row_no} invalid: {exc}") from exc
            # FY filter on sell_date — only sales that settled in this FY count
            # toward the current year's ₹1.25 L bucket.
            if not (fy_start <= line.sell_date <= fy_end):
                continue
            # Only LTCG-eligible rows participate in the Sec 112A netting. STCG /
            # STCL are governed by Sec 111A and are NOT pooled with LTCG for the
            # exemption, so we ignore them here.
            if not line.is_ltcg:
                continue
            if line.gain > 0:
                adj.realized_ltcg += line.gain
            elif line.gain < 0:
                adj.realized_ltcl += -line.gain
            adj.lines.append(line)
    adj.sources.append(
        f"--stocks-ledger {path.name}: {len(adj.lines)} LTCG-eligible row(s) "
        f"in FY {fy_label} → LTCG ₹{adj.realized_ltcg:,.2f}, "
        f"LTCL ₹{adj.realized_ltcl:,.2f}, net ₹{adj.net_ltcg:,.2f}"
    )
    return adj


def _parse_date(value: str) -> date:
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d-%b-%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unparseable date: {value!r}")
