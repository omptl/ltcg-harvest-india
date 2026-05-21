"""Tests for the redemption-window advisory (timing.py)."""

from __future__ import annotations

from datetime import datetime, timezone

from tax_harvest.timing import compute_advisory


def _utc(year, month, day, hour, minute):
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def test_green_weekday_morning_before_cutoff():
    """Friday 22-May-2026, 09:00 IST → place orders before 15:00 IST today."""
    now = _utc(2026, 5, 22, 3, 30)  # 09:00 IST
    a = compute_advisory(plan_nav_date_str="21-May-2026", now_utc=now)
    assert a.status == "GREEN"
    assert "🟢" in a.headline
    assert a.cutoff_ist.hour == 15
    assert a.applicable_nav_date == now.astimezone(a.cutoff_ist.tzinfo).date()


def test_amber_weekday_after_cutoff():
    """Friday 22-May-2026, 16:00 IST → next applicable NAV is Mon 25-May."""
    now = _utc(2026, 5, 22, 10, 30)  # 16:00 IST Friday
    a = compute_advisory(plan_nav_date_str="22-May-2026", now_utc=now)
    assert a.status == "AMBER"
    assert "🟡" in a.headline
    # Friday after cutoff → next weekday = Monday 25-May
    assert a.applicable_nav_date.weekday() == 0  # Monday
    assert a.applicable_nav_date.isoformat() == "2026-05-25"


def test_amber_saturday():
    now = _utc(2026, 5, 23, 6, 0)  # Sat 11:30 IST
    a = compute_advisory(plan_nav_date_str="22-May-2026", now_utc=now)
    assert a.status == "AMBER"
    assert a.applicable_nav_date.isoformat() == "2026-05-25"  # Monday
    assert any("weekend" in d.lower() for d in a.details)


def test_amber_sunday_evening():
    now = _utc(2026, 5, 24, 18, 0)  # Sun 23:30 IST
    a = compute_advisory(plan_nav_date_str="22-May-2026", now_utc=now)
    assert a.status == "AMBER"
    assert a.applicable_nav_date.isoformat() == "2026-05-25"


def test_green_at_14_59_ist_just_before_cutoff():
    now = _utc(2026, 5, 22, 9, 29)  # 14:59 IST Friday
    a = compute_advisory(plan_nav_date_str="21-May-2026", now_utc=now)
    assert a.status == "GREEN"


def test_amber_at_15_00_ist_cutoff_exactly():
    now = _utc(2026, 5, 22, 9, 30)  # 15:00 IST exactly
    a = compute_advisory(plan_nav_date_str="22-May-2026", now_utc=now)
    # At/after cutoff → AMBER
    assert a.status == "AMBER"


def test_stale_nav_warning_appears_when_gap_large():
    """Plan built from 21-May-2026 NAV, transaction will price at 25-May-2026 → 4-day gap."""
    now = _utc(2026, 5, 23, 6, 0)  # Sat → next biz day Mon 25-May
    a = compute_advisory(plan_nav_date_str="21-May-2026", now_utc=now)
    assert any("staleness" in d.lower() and "4-day" in d for d in a.details)


def test_one_day_stale_message_mentions_intraday_range():
    """Plan from yesterday, transacting today → typical case, 1-day gap."""
    now = _utc(2026, 5, 22, 3, 0)  # 08:30 IST Friday
    a = compute_advisory(plan_nav_date_str="21-May-2026", now_utc=now)
    # GREEN today; plan NAV is yesterday → 1-day gap
    one_day_msgs = [d for d in a.details if "1-2%" in d or "intraday" in d.lower()]
    assert one_day_msgs, "Expected an intraday-range note for the 1-day NAV gap"


def test_no_plan_nav_date_still_returns_valid_advisory():
    """Some runs may not have a snapshot_date (offline mode). Don't crash."""
    now = _utc(2026, 5, 22, 3, 0)
    a = compute_advisory(plan_nav_date_str=None, now_utc=now)
    assert a.status in {"GREEN", "AMBER"}
    assert a.plan_nav_date is None
