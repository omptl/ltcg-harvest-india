"""Redemption-window advisory based on the AMC NAV cut-off in IST.

SEBI rule for equity mutual fund redemption (the only kind this tool harvests):
the applicable NAV is the closing NAV of the day the AMC receives the redemption
request, IF received before the 3:00 PM IST cut-off. After cut-off, you get the
next business day's closing NAV.

Two things matter for the user:

1. **Should they place orders now, or wait until tomorrow?** Driven purely by
   IST wall-clock — does the next ~3 PM IST cut-off fall today or tomorrow?
2. **How stale is the NAV in the plan vs the NAV they'll actually transact at?**
   The plan uses yesterday's AMFI snapshot. If they redeem today, their actual
   booked LTCG will be ±1–2% off the plan estimate (mid-cap intraday range).

Holidays / NSE non-trading days are NOT modelled — the advisory uses "next
weekday" not "next trading day". When the next IST weekday is a public
holiday, the user has to bump expectations by one more day. We surface this
caveat in the advisory text instead of shipping a (constantly stale) holiday
calendar.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

IST = timezone(timedelta(hours=5, minutes=30))
CUTOFF_HOUR = 15  # 3:00 PM IST — SEBI equity-MF redemption cutoff
CUTOFF_MIN = 0


@dataclass
class RedemptionAdvisory:
    status: str  # "GREEN" or "AMBER"
    now_ist: datetime
    cutoff_ist: datetime          # the next cut-off the order would qualify for
    applicable_nav_date: date      # the closing NAV your redemption will be priced at
    plan_nav_date: Optional[date]  # the date of the NAV snapshot used in the plan
    headline: str                  # one-line summary for the panel header
    details: list[str]             # bullet-point reasoning


def compute_advisory(plan_nav_date_str: Optional[str],
                     now_utc: Optional[datetime] = None) -> RedemptionAdvisory:
    """Build a redemption-window advisory.

    `plan_nav_date_str` is whatever NavIndex.snapshot_date returned (string in
    "DD-Mon-YYYY" form from AMFI). Optional — None means "couldn't determine
    plan-NAV freshness".

    `now_utc` is injectable for tests; defaults to the real clock.
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    now_ist = now_utc.astimezone(IST)
    plan_date = _parse_amfi_date(plan_nav_date_str) if plan_nav_date_str else None

    is_weekend = now_ist.weekday() >= 5  # Sat=5, Sun=6
    today_cutoff = now_ist.replace(hour=CUTOFF_HOUR, minute=CUTOFF_MIN,
                                    second=0, microsecond=0)
    before_today_cutoff = now_ist < today_cutoff

    if not is_weekend and before_today_cutoff:
        # GREEN — orders placed before today's 3 PM IST get today's NAV.
        applicable_date = now_ist.date()
        cutoff = today_cutoff
        time_left = cutoff - now_ist
        hh, mm = _hhmm(time_left)
        headline = (
            f"🟢 GREEN — place redemption orders within ~{hh}h{mm}m "
            f"(by {cutoff.strftime('%H:%M IST today, %a %d-%b-%Y')}) to "
            f"transact at today's closing NAV."
        )
        details = [
            f"Current time: {now_ist.strftime('%H:%M IST, %a %d-%b-%Y')}.",
            f"SEBI cut-off for equity MF redemption: 15:00 IST. Orders placed before "
            f"that get the SAME-day closing NAV (declared by AMC ~21:00–23:00 IST tonight).",
            f"Your redemption will be priced at the closing NAV of "
            f"**{applicable_date.strftime('%a %d-%b-%Y')}** — not the "
            f"{plan_date.strftime('%d-%b-%Y') if plan_date else 'snapshot'} NAV "
            f"shown in the plan.",
        ]
    else:
        # AMBER — too late today, or weekend. Next NAV-producing day is the
        # next weekday on/after tomorrow.
        next_biz = _next_weekday(now_ist.date() + timedelta(days=1))
        cutoff = datetime.combine(next_biz, time(CUTOFF_HOUR, CUTOFF_MIN), tzinfo=IST)
        applicable_date = next_biz
        wait_until = cutoff - timedelta(hours=1)  # rerun ~1h before cutoff
        why = ("weekend — no NAV declared on Sat/Sun"
               if is_weekend
               else f"past today's 15:00 IST cut-off ({now_ist.strftime('%H:%M IST')})")
        headline = (
            f"🟡 AMBER — wait. {why.capitalize()}. "
            f"Next applicable NAV is from **{next_biz.strftime('%a %d-%b-%Y')}** EOD."
        )
        details = [
            f"Current time: {now_ist.strftime('%H:%M IST, %a %d-%b-%Y')}.",
            f"Reason: {why}.",
            f"Next NAV-producing day (assuming no public holiday): "
            f"**{next_biz.strftime('%a %d-%b-%Y')}**. NAV will publish ~21:00 IST that night.",
            f"Recommended workflow: rerun this tool on {next_biz.strftime('%a %d-%b-%Y')} "
            f"morning (before {cutoff.strftime('%H:%M IST')}) so it fetches the fresh "
            f"NAV snapshot and rebuilds the plan against current prices, THEN place orders.",
            "Public holidays (Diwali, Republic Day, etc.) shift this further — verify "
            "against NSE / AMC calendar before transacting.",
        ]
        status = "AMBER"

    # NAV-staleness gap — independent of status. Useful even on GREEN.
    if plan_date:
        gap_days = (applicable_date - plan_date).days
        if gap_days >= 2:
            details.append(
                f"⚠ NAV staleness: the plan was built from the "
                f"{plan_date.strftime('%d-%b-%Y')} NAV snapshot — your transaction "
                f"will price at the {applicable_date.strftime('%d-%b-%Y')} closing NAV, "
                f"a **{gap_days}-day** gap. Mid-cap funds typically move ±1–2% per "
                f"day. Consider rerunning with `--no-cache` to refresh AMFI prices "
                f"before placing orders."
            )
        elif gap_days == 1:
            details.append(
                f"NAV staleness: plan uses {plan_date.strftime('%d-%b-%Y')} NAV; "
                f"transaction will use {applicable_date.strftime('%d-%b-%Y')} NAV. "
                f"Expect the booked LTCG to land within roughly ±1–2% of the plan "
                f"estimate (typical mid-cap intraday move)."
            )

    return RedemptionAdvisory(
        status="GREEN" if (not is_weekend and before_today_cutoff) else "AMBER",
        now_ist=now_ist,
        cutoff_ist=cutoff,
        applicable_nav_date=applicable_date,
        plan_nav_date=plan_date,
        headline=headline,
        details=details,
    )


def _next_weekday(d: date) -> date:
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def _hhmm(td: timedelta) -> tuple[int, int]:
    total_minutes = max(0, int(td.total_seconds() // 60))
    return divmod(total_minutes, 60)


def _parse_amfi_date(value: str) -> Optional[date]:
    """Accept the formats AMFI ships in NAVAll.txt: '21-May-2026', '21-MAY-2026', etc."""
    for fmt in ("%d-%b-%Y", "%d-%B-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None
