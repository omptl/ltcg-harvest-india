"""Loss-harvesting candidate identification.

We don't recommend an action — just surface lots that are currently in loss and
categorize them as STCL (settable against STCG + LTCG) vs LTCL (only against LTCG).
The user decides whether to act.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .lots import DEBT_LTCG_DAYS, EQUITY_LTCG_DAYS
from .models import EQUITY_LIKE_CATEGORIES, LotEvaluation, SchemeCategory


@dataclass
class LossCandidate:
    evaluation: LotEvaluation
    loss_type: str  # "STCL" or "LTCL"
    notes: str = ""


def find_loss_candidates(evaluations: Iterable[LotEvaluation]) -> list[LossCandidate]:
    """Return all lots with non-positive unrealized gain, tagged STCL/LTCL.

    A lot in a locked-in scheme is still flagged — the user might be inside the
    lock-in window, but knowing the unrealized loss is still informative.
    """
    out: list[LossCandidate] = []
    for ev in evaluations:
        if ev.unrealized_gain >= 0:
            continue
        loss_type, note = _classify_loss(ev)
        out.append(LossCandidate(evaluation=ev, loss_type=loss_type, notes=note))
    out.sort(key=lambda c: c.evaluation.unrealized_gain)  # biggest losses first
    return out


def _classify_loss(ev: LotEvaluation) -> tuple[str, str]:
    cat = ev.scheme.category
    days = ev.holding_days
    if cat in EQUITY_LIKE_CATEGORIES:
        return ("LTCL", "") if days > EQUITY_LTCG_DAYS else ("STCL", "")
    if cat == SchemeCategory.DEBT_POST_APR_2023:
        return ("STCL", "Sec 50AA — always short-term irrespective of holding period")
    return ("LTCL", "") if days > DEBT_LTCG_DAYS else ("STCL", "")
