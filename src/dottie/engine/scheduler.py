"""The clock: turns due schedules into messages, which wake the dottie like any other message.

A schedule lives outside the dottie. The dottie does not run a timer; this module is the only thing that is always
awake, and it does nothing but insert rows.
"""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Dottie, Schedule
from . import bus


def validate(cron: str | None, run_at: datetime | None, timezone: str) -> str | None:
    """Why this timing is not usable, or None when it is."""
    try:
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError, ValueError:
        return f"Unknown timezone {timezone!r} (use e.g. Europe/Brussels or UTC)."
    if (cron is None) == (run_at is None):
        return "Give either a cron expression (recurring) or a time to run once."
    if cron is not None and not croniter.is_valid(cron):
        return f"{cron!r} is not a valid cron expression (five fields, e.g. '0 8 * * 1-5')."
    return None


def next_run(schedule: Schedule, after: datetime) -> datetime | None:
    """The next firing after `after`; None when a one-off has gone."""
    if schedule.cron:
        local = after.astimezone(ZoneInfo(schedule.timezone))
        return croniter(schedule.cron, local).get_next(datetime).astimezone(UTC)
    if schedule.run_at and schedule.run_at > after:
        return schedule.run_at
    return None


def arm(schedule: Schedule, now: datetime | None = None) -> None:
    """Set `next_run_at` from the schedule's timing (after creating or editing it)."""
    schedule.next_run_at = next_run(schedule, now or datetime.now(UTC)) if schedule.enabled else None


def fire(session: Session, schedule: Schedule, now: datetime) -> None:
    """Deliver one firing: a message from the clock in the schedule's own thread, so each run builds on the last."""
    dottie = session.get(Dottie, schedule.dottie_id)
    if dottie is None:
        return
    conversation = session.get(bus.Conversation, schedule.conversation_id) if schedule.conversation_id else None
    if conversation is None:
        conversation = bus.new_conversation(session, dottie.id, "schedule", schedule.title)
        schedule.conversation_id = conversation.id
    bus.post(
        session,
        conversation,
        sender_kind="scheduler",
        sender_id=None,
        recipient_id=dottie.id,
        body=f"Scheduled task: {schedule.title}\n\n{schedule.prompt}",
    )
    schedule.last_run_at = now


def fire_due(session: Session, now: datetime | None = None) -> int:
    """Fire everything due. A schedule that missed several firings (the app was down) fires once, then moves on."""
    now = now or datetime.now(UTC)
    due = session.scalars(
        select(Schedule)
        .where(Schedule.enabled, Schedule.next_run_at <= now)
        .order_by(Schedule.next_run_at)
        .with_for_update(skip_locked=True)
    ).all()
    for schedule in due:
        fire(session, schedule, now)
        schedule.next_run_at = next_run(schedule, now)
        if schedule.next_run_at is None:
            schedule.enabled = False  # a one-off, done
    return len(due)
