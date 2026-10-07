"""What this installation can do, and a live stream that tells the UI when to look again."""

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sse_starlette.sse import EventSourceResponse

from ..auth import UserDep
from ..models import Conversation, Dottie, Event, Message, Run, WikiPage

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


def _signature(request: Request, user_id: str) -> dict[str, str]:
    """One cheap value per kind of thing that changes, for this user's dotties only; when a value moves, the UI
    refetches that kind."""
    with request.app.state.session_factory() as s:
        mine = select(Dottie.id).where(Dottie.owner_id == user_id)
        chats = select(Conversation.id).where(Conversation.dottie_id.in_(mine))
        waiting = select(func.count()).where(Message.status == "pending", Message.recipient_id.in_(mine))
        running = select(func.count()).where(Run.status == "running", Run.dottie_id.in_(mine))
        newest = {
            "messages": select(func.max(Message.id)).where(Message.conversation_id.in_(chats)),
            "events": select(func.max(Event.id)).where(Event.dottie_id.in_(mine)),
            "runs": select(func.max(Run.id)).where(Run.dottie_id.in_(mine)),
            "wiki": select(func.max(WikiPage.updated_at)).where(WikiPage.dottie_id.in_(mine)),
        }
        mine_awake = select(func.count()).where(Dottie.owner_id == user_id, Dottie.sandbox_awake)
        counts = {
            "messages": waiting,
            "runs": running,
            "dotties": select(func.count()).where(Dottie.owner_id == user_id),
        }
        found = {kind: str(s.scalar(query)) for kind, query in newest.items()}
        for kind, query in counts.items():
            found[kind] = found.get(kind, "") + f":{s.scalar(query)}"
        found["dotties"] += f":{s.scalar(mine_awake)}"
        return found


@router.get("/stream")
async def stream(request: Request, user: UserDep) -> EventSourceResponse:
    """Server-sent events: `{"changed": ["messages", "events"]}` whenever those move. The data itself is fetched
    through the normal endpoints, so there is one way to read everything."""

    async def changes() -> AsyncIterator[dict[str, str]]:
        last: dict[str, str] = {}
        while not await request.is_disconnected():
            now = await asyncio.to_thread(_signature, request, user.id)
            moved = [k for k, v in now.items() if last and last.get(k) != v]
            if moved:
                yield {"event": "changed", "data": json.dumps({"changed": moved})}
            last = now
            await asyncio.sleep(1)

    return EventSourceResponse(changes(), ping=15)
