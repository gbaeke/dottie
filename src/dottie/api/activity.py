"""What dotties did while awake: the activity feed and the list of wakings."""

from datetime import datetime
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from ..auth import UserDep
from ..db import SessionDep
from ..models import Dottie, Event, Run
from .access import owned_dottie
from .util import build

router = APIRouter(tags=["activity"])


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    dottie_id: int
    dottie_name: str
    run_id: int | None
    kind: str  # wake | tool | tool_result | sent | schedule | wiki | sleep | error
    text: str
    data: dict[str, Any]
    created_at: datetime


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    dottie_id: int
    conversation_id: str | None
    trigger: str
    status: str
    summary: str
    started_at: datetime
    finished_at: datetime | None


def _events(
    session: SessionDep, user: UserDep, dottie_id: int | None, limit: int, before: int | None
) -> list[EventOut]:
    query = (
        select(Event, Dottie.name)
        .join(Dottie, Dottie.id == Event.dottie_id)
        .where(Dottie.owner_id == user.id)
        .order_by(Event.id.desc())
        .limit(limit)
    )
    if dottie_id is not None:
        query = query.where(Event.dottie_id == dottie_id)
    if before is not None:
        query = query.where(Event.id < before)
    return [build(EventOut, e, dottie_name=name) for e, name in session.execute(query)]


@router.get("/events")
def list_events(session: SessionDep, user: UserDep, limit: int = 60, before: int | None = None) -> list[EventOut]:
    """Everything every dottie did, newest first."""
    return _events(session, user, None, min(limit, 200), before)


@router.get("/dotties/{dottie_id}/events")
def list_dottie_events(
    dottie_id: int, session: SessionDep, user: UserDep, limit: int = 100, before: int | None = None
) -> list[EventOut]:
    owned_dottie(session, user, dottie_id)
    return _events(session, user, dottie_id, min(limit, 300), before)


@router.get("/dotties/{dottie_id}/runs")
def list_runs(dottie_id: int, session: SessionDep, user: UserDep, limit: int = 30) -> list[RunOut]:
    owned_dottie(session, user, dottie_id)
    rows = session.scalars(select(Run).where(Run.dottie_id == dottie_id).order_by(Run.id.desc()).limit(min(limit, 100)))
    return [RunOut.model_validate(r) for r in rows]
