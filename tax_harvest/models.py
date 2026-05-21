"""Pydantic data models for transactions, lots, schemes, and the redemption plan.

All currency values are in INR. All units are mutual fund units (4 decimal precision is
typical in the industry; we keep float and round at presentation time).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class TxnType(str, Enum):
    """Transaction types as they appear (normalized) in a CAS statement."""

    PURCHASE = "purchase"
    SIP = "sip"
    SWITCH_IN = "switch_in"
    SWITCH_OUT = "switch_out"
    REDEMPTION = "redemption"
    DIVIDEND_PAYOUT = "dividend_payout"
    DIVIDEND_REINVEST = "dividend_reinvest"
    BONUS = "bonus"
    STT = "stt"
    STAMP_DUTY = "stamp_duty"
    SEGREGATION = "segregation"
    REVERSAL = "reversal"
    OTHER = "other"


# Events that create new units (and therefore new cost-basis lots).
UNIT_CREATING_TYPES = {
    TxnType.PURCHASE,
    TxnType.SIP,
    TxnType.SWITCH_IN,
    TxnType.DIVIDEND_REINVEST,
    TxnType.BONUS,
}

# Events that deplete units (reduce existing lots FIFO).
UNIT_DEPLETING_TYPES = {
    TxnType.REDEMPTION,
    TxnType.SWITCH_OUT,
}


class SchemeCategory(str, Enum):
    """Tax-treatment-relevant scheme categories."""

    EQUITY = "equity"  # Sec 112A: LTCG > 12 months, 12.5% above 1.25L exemption
    ELSS = "elss"  # Equity for tax, 3-year per-lot lock-in
    EQUITY_HYBRID_AGGRESSIVE = "equity_hybrid_aggressive"  # >=65% equity, equity treatment
    ARBITRAGE = "arbitrage"  # equity for tax
    DEBT_PRE_APR_2023 = "debt_pre_apr_2023"  # LTCG >24m at 12.5% no indexation
    DEBT_POST_APR_2023 = "debt_post_apr_2023"  # Sec 50AA: always slab, treated as STCG
    HYBRID_CONSERVATIVE = "hybrid_conservative"  # treat as debt
    INTERNATIONAL = "international"  # ambiguous post-Apr 2025 budget; flag
    GOLD = "gold"  # special rules; flag
    SOLUTION_ORIENTED = "solution_oriented"  # 5-year lock-in OR goal age
    CLOSE_ENDED = "close_ended"
    FMP = "fmp"  # Fixed Maturity Plan
    UNKNOWN = "unknown"


# Categories whose lots get equity tax treatment.
EQUITY_LIKE_CATEGORIES = {
    SchemeCategory.EQUITY,
    SchemeCategory.ELSS,
    SchemeCategory.EQUITY_HYBRID_AGGRESSIVE,
    SchemeCategory.ARBITRAGE,
}


class Transaction(BaseModel):
    """A single CAS transaction line, normalized."""

    date: date
    txn_type: TxnType
    units: float  # signed: positive for unit-creating, negative for unit-depleting
    nav: float
    amount: float
    description: str = ""


class Scheme(BaseModel):
    """A scheme position within a folio. (folio, scheme) is the unique key for FIFO."""

    folio: str
    scheme_name: str
    amc: str
    isin: Optional[str] = None
    scheme_code: Optional[str] = None  # AMFI code if known
    category: SchemeCategory = SchemeCategory.UNKNOWN
    is_demat: bool = False
    transactions: list[Transaction] = Field(default_factory=list)

    @property
    def key(self) -> tuple[str, str]:
        return (self.folio, self.isin or self.scheme_name)


class Lot(BaseModel):
    """A single FIFO lot — one unit-creating event with residual units after depletion."""

    purchase_date: date
    units_original: float
    units_remaining: float
    cost_per_unit: float  # purchase NAV; 0 for bonus units
    source_txn_type: TxnType

    @property
    def cost_basis(self) -> float:
        return self.units_remaining * self.cost_per_unit


class LotEvaluation(BaseModel):
    """A lot evaluated against today's NAV and the current FY for harvesting."""

    scheme: Scheme
    lot: Lot
    current_nav: float
    unrealized_gain: float  # for units_remaining
    gain_per_unit: float
    holding_days: int
    is_ltcg_eligible: bool
    is_locked_in: bool
    locked_reason: Optional[str] = None
    has_exit_load: bool = False
    exit_load_reason: Optional[str] = None
    excluded_reason: Optional[str] = None  # set if lot can't be harvested

    @property
    def is_harvestable(self) -> bool:
        return self.excluded_reason is None and self.unrealized_gain > 0


class PlanLine(BaseModel):
    """One row of the recommended redemption plan."""

    scheme_name: str
    folio: str
    amc: str
    isin: Optional[str]
    units_to_redeem: float
    estimated_ltcg: float
    current_nav: float
    cost_basis_redeemed: float
    purchase_dates: list[date]  # lots being touched


class HarvestPlan(BaseModel):
    """The full output of a harvesting run."""

    fy_label: str  # e.g. "2026-27"
    budget_total: float  # 1.25L base
    already_realized_ltcg: float
    carry_forward_losses: float
    effective_budget: float  # 1.25L - already_realized + carry_forward
    lines: list[PlanLine] = Field(default_factory=list)
    total_ltcg_harvested: float = 0.0
    budget_remaining: float = 0.0
    excluded_lots: list[LotEvaluation] = Field(default_factory=list)
    loss_candidates: list[LotEvaluation] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class CASData(BaseModel):
    """Top-level container for a parsed CAS statement."""

    investor_name: str = ""
    pan_masked: str = ""
    email_masked: str = ""
    is_nri: bool = False
    schemes: list[Scheme] = Field(default_factory=list)
    statement_period_from: Optional[date] = None
    statement_period_to: Optional[date] = None
