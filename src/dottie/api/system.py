"""What this installation can do, and a live stream that tells the UI when to look again."""

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sse_starlette.sse import EventSourceResponse

from ..models import Dottie, Event, Message, Run, WikiPage

router = APIRouter(tags=["system"])


class SystemOut(BaseModel):
    llm_configured: bool
    llm_model: str
    sandbox_backend: str
    engine_running: bool
    timezone: str


@router.get("/system")
def system(request: Request) -> SystemOut:
    settings = request.app.state.settings
    return SystemOut(
        llm_configured=settings.llm_configured,
        llm_model=settings.llm_model,
        sandbox_backend=settings.sandbox_backend,
        engine_running=settings.engine_enabled,
        timezone=settings.user_timezone,
    )


def _signature(request: Request) -> dict[str, str]:
    """One cheap value per kind of thing that changes; when a value moves, the UI refetches that kind."""
    with request.app.state.session_factory() as s:
        return {
            "messages": str(s.scalar(select(func.max(Message.id))))
            + str(s.scalar(select(func.count()).where(Message.status == "pending"))),
            "events": str(s.scalar(select(func.max(Event.id)))),
            "runs": str(s.scalar(select(func.max(Run.id))))
            + str(s.scalar(select(func.count()).where(Run.status == "running"))),
            "wiki": str(s.scalar(select(func.max(WikiPage.updated_at))))
            + str(s.scalar(select(func.count()).select_from(WikiPage))),
            "dotties": str(s.scalar(select(func.count()).select_from(Dottie))),
        }


@router.get("/stream")
async def stream(request: Request) -> EventSourceResponse:
    """Server-sent events: `{"changed": ["messages", "events"]}` whenever those move. The data itself is fetched
    through the normal endpoints, so there is one way to read everything."""

    async def changes() -> AsyncIterator[dict[str, str]]:
        last: dict[str, str] = {}
        while not await request.is_disconnected():
            now = await asyncio.to_thread(_signature, request)
            moved = [k for k, v in now.items() if last and last.get(k) != v]
            if moved:
                yield {"event": "changed", "data": json.dumps({"changed": moved})}
            last = now
            await asyncio.sleep(1)

    return EventSourceResponse(changes(), ping=15)
