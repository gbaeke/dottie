"""Dottie as an MCP server (at /mcp): other agents, such as Claude Code, can talk to your dotties and read their wikis.

The tools only use the same messaging layer as everything else: `ask_dottie` is a user message that wakes the dottie and
waits (a while) for its answer.
"""

import asyncio
import time
from collections.abc import Callable

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from .engine import bus
from .models import Conversation, Dottie, Message, WikiPage

Sessions = Callable[[], sessionmaker[Session]]  # a function: the database only exists once the app has started


def _find(s: Session, name: str) -> Dottie:
    found = s.scalar(select(Dottie).where(Dottie.slug == name.strip().lower()))
    if found is None:
        raise ValueError(f"No dottie {name!r}. Use list_dotties to see their names.")
    return found


def _send(sessions: Sessions, name: str, message: str, conversation_id: str) -> tuple[str, int]:
    """Post the message (a new conversation unless one is given); returns the conversation and the id to wait after."""
    with sessions()() as s:
        target = _find(s, name)
        conversation = s.get(Conversation, conversation_id) if conversation_id else None
        conversation = conversation or bus.new_conversation(s, target.id, "chat", f"MCP: {message[:50]}")
        if message.strip():
            after = bus.post(
                s, conversation, sender_kind="user", sender_id=None, recipient_id=target.id, body=message
            ).id
        else:  # collecting an earlier answer
            latest = select(Message.id).where(Message.conversation_id == conversation.id, Message.sender_kind == "user")
            after = s.scalar(latest.order_by(Message.id.desc()).limit(1)) or 0
        s.commit()
        return conversation.id, after


def _reply_after(sessions: Sessions, conversation: str, after: int) -> str | None:
    with sessions()() as s:
        query = select(Message.body).where(
            Message.conversation_id == conversation, Message.id > after, Message.recipient_id.is_(None)
        )
        return s.scalar(query.order_by(Message.id).limit(1))


def build_mcp(sessions: Sessions) -> FastMCP:
    mcp = FastMCP(
        "Dottie",
        instructions="Persistent agents ('dotties') with their own memory: list them, ask one, read what it knows.",
        streamable_http_path="/",
        stateless_http=True,  # no session to keep: every call stands alone
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),  # the ingress fronts us
    )

    @mcp.tool()
    def list_dotties() -> str:
        """The dotties that exist: their name (use it to address them) and what each is for."""
        with sessions()() as s:
            rows = s.scalars(select(Dottie).order_by(Dottie.name)).all()
            return "\n".join(f"- {d.slug}: {d.name}, {d.role}" for d in rows) or "There are no dotties yet."

    @mcp.tool()
    async def ask_dottie(dottie: str, message: str, conversation_id: str = "", wait_seconds: int = 120) -> str:
        """Send a message to a dottie and wait for its answer. Returns the answer, or, when it is still working after
        `wait_seconds`, its conversation id: call again with that `conversation_id` and an empty message to collect it
        later. Pass a `conversation_id` to continue a conversation."""
        conversation, after = await asyncio.to_thread(_send, sessions, dottie, message, conversation_id)
        deadline = time.monotonic() + max(1, min(wait_seconds, 600))
        while time.monotonic() < deadline:
            answer = await asyncio.to_thread(_reply_after, sessions, conversation, after)
            if answer is not None:
                return answer
            await asyncio.sleep(1)
        return f"{dottie} is still working. Call ask_dottie again with conversation_id={conversation} and no message."

    @mcp.tool()
    def read_wiki(dottie: str, path: str = "index.md") -> str:
        """Read a page of a dottie's wiki (start with index.md, the table of contents)."""
        with sessions()() as s:
            target = _find(s, dottie)
            query = select(WikiPage).where(WikiPage.dottie_id == target.id, WikiPage.path == path.strip("/"))
            page = s.scalar(query)
            if page is not None:
                return page.content
            paths = s.scalars(select(WikiPage.path).where(WikiPage.dottie_id == target.id).order_by(WikiPage.path))
            return f"No page {path!r}. Pages: {', '.join(paths)}"

    return mcp
