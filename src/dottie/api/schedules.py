"""Schedules: what a dottie should do, and when. The clock (engine/scheduler.py) wakes it."""

from datetime import UTC, datetime

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from ..db import SessionDep
from ..engine import scheduler
from ..models import Dottie, Schedule
from .errors import ApiError, get_or_404
from .util import build

router = APIRouter(tags=["schedules"])


class ScheduleIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    prompt: str = Field(min_length=1, max_length=8000)
    cron: str | None = Field(default=None, max_length=100)  # recurring, or...
    run_at: datetime | None = None  # ...once
    timezone: str = "UTC"


class SchedulePatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    prompt: str | None = Field(default=None, min_length=1, max_length=8000)
    cron: str | None = None
    run_at: datetime | None = None
    timezone: str | None = None
    enabled: bool | None = None


class ScheduleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    dottie_id: int
    dottie_name: str
    title: str
    prompt: str
    cron: str | None
    run_at: datetime | None
    timezone: str
    enabled: bool
    next_run_at: datetime | None
    last_run_at: datetime | None
    conversation_id: str | None
    created_by: str


def _out(session: SessionDep, schedule: Schedule) -> ScheduleOut:
    dottie = session.get_one(Dottie, schedule.dottie_id)
    return build(ScheduleOut, schedule, dottie_name=dottie.name)


def _check(cron: str | None, run_at: datetime | None, timezone: str) -> None:
    problem = scheduler.validate(cron, run_at, timezone)
    if problem:
        raise ApiError("invalid_schedule", problem, 422)


@router.get("/schedules")
def list_all(session: SessionDep) -> list[ScheduleOut]:
    rows = session.scalars(select(Schedule).order_by(Schedule.enabled.desc(), Schedule.next_run_at, Schedule.id))
    return [_out(session, s) for s in rows]


@router.get("/dotties/{dottie_id}/schedules")
def list_schedules(dottie_id: int, session: SessionDep) -> list[ScheduleOut]:
    get_or_404(session, Dottie, dottie_id)
    rows = session.scalars(select(Schedule).where(Schedule.dottie_id == dottie_id).order_by(Schedule.id))
    return [_out(session, s) for s in rows]


@router.post("/dotties/{dottie_id}/schedules", status_code=201)
def create_schedule(dottie_id: int, data: ScheduleIn, session: SessionDep) -> ScheduleOut:
    get_or_404(session, Dottie, dottie_id)
    _check(data.cron, data.run_at, data.timezone)
    schedule = Schedule(dottie_id=dottie_id, enabled=True, **data.model_dump())
    scheduler.arm(schedule)
    session.add(schedule)
    session.commit()
    return _out(session, schedule)


@router.patch("/schedules/{schedule_id}")
def update_schedule(schedule_id: int, data: SchedulePatch, session: SessionDep) -> ScheduleOut:
    schedule = get_or_404(session, Schedule, schedule_id)
    changes = data.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(schedule, field, value)
    if {"cron", "run_at", "timezone"} & changes.keys():
        _check(schedule.cron, schedule.run_at, schedule.timezone)
    scheduler.arm(schedule)
    session.commit()
    return _out(session, schedule)


@router.post("/schedules/{schedule_id}/run", status_code=202)
def run_now(schedule_id: int, session: SessionDep) -> ScheduleOut:
    """Fire it now, in addition to its normal timing."""
    schedule = get_or_404(session, Schedule, schedule_id)
    scheduler.fire(session, schedule, datetime.now(UTC))
    session.commit()
    return _out(session, schedule)


@router.delete("/schedules/{schedule_id}", status_code=204)
def delete_schedule(schedule_id: int, session: SessionDep) -> None:
    session.delete(get_or_404(session, Schedule, schedule_id))
    session.commit()
