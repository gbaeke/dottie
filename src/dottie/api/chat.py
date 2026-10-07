"""Talking to a dottie: conversations, messages, the user's inbox, and a view of the dottie-to-dottie traffic."""

from datetime import UTC, datetime

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, update

from ..db import SessionDep
from ..engine import bus, checkpoints
from ..models import Conversation, Dottie, Message
from .errors import ApiError, get_or_404
from .util import build

router = APIRouter(tags=["chat"])


class ConversationIn(BaseModel):
    title: str = Field(default="", max_length=200)


class ConversationOut(BaseModel):
    id: str
    dottie_id: int
    kind: str  # chat | schedule | dottie
    title: str
    peer_name: str | None
    preview: str
    unread: int
    updated_at: datetime


class MessageIn(BaseModel):
    body: str = Field(min_length=1, max_length=20000)


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    conversation_id: str
    sender_kind: str  # user | dottie | scheduler | system
    sender_id: int | None
    sender_name: str | None
    recipient_id: int | None
    body: str
    status: str
    read_at: datetime | None
    created_at: datetime


class InboxItem(BaseModel):
    message: MessageOut
    dottie_id: int
    dottie_name: str
    dottie_hue: int
    conversation_title: str


class BusItem(BaseModel):
    message: MessageOut
    recipient_name: str


def _names(session, ids: set[int | None]) -> dict[int, str]:
    wanted = {i for i in ids if i is not None}
    return dict(session.execute(select(Dottie.id, Dottie.name).where(Dottie.id.in_(wanted))).all()) if wanted else {}


def _messages_out(session, rows: list[Message]) -> list[MessageOut]:
    names = _names(session, {m.sender_id for m in rows})
    return [build(MessageOut, m, sender_name=names.get(m.sender_id or 0)) for m in rows]


@router.get("/dotties/{dottie_id}/conversations")
def list_conversations(dottie_id: int, session: SessionDep) -> list[ConversationOut]:
    get_or_404(session, Dottie, dottie_id)
    conversations = session.scalars(
        select(Conversation).where(Conversation.dottie_id == dottie_id).order_by(Conversation.updated_at.desc())
    ).all()
    peers = _names(session, {c.peer_id for c in conversations})
    unread = dict(
        session.execute(
            select(Message.conversation_id, func.count())
            .where(Message.recipient_id.is_(None), Message.read_at.is_(None), Message.sender_id == dottie_id)
            .group_by(Message.conversation_id)
        ).all()
    )
    out: list[ConversationOut] = []
    for c in conversations:
        last = session.scalar(
            select(Message.body).where(Message.conversation_id == c.id).order_by(Message.id.desc()).limit(1)
        )
        out.append(
            ConversationOut(
                id=c.id,
                dottie_id=c.dottie_id,
                kind=c.kind,
                title=c.title or "New chat",
                peer_name=peers.get(c.peer_id or 0),
                preview=(last or "")[:140],
                unread=unread.get(c.id, 0),
                updated_at=c.updated_at,
            )
        )
    return out


@router.post("/dotties/{dottie_id}/conversations", status_code=201)
def create_conversation(dottie_id: int, data: ConversationIn, session: SessionDep) -> ConversationOut:
    get_or_404(session, Dottie, dottie_id)
    c = bus.new_conversation(session, dottie_id, "chat", data.title)
    session.commit()
    return ConversationOut(
        id=c.id, dottie_id=dottie_id, kind="chat", title=c.title or "New chat", peer_name=None, preview="", unread=0,
        updated_at=c.updated_at,
    )  # fmt: skip


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: str, session: SessionDep, request: Request) -> None:
    session.delete(get_or_404(session, Conversation, conversation_id))
    session.commit()
    checkpoints.delete_thread(request.app.state.settings, conversation_id)


@router.get("/conversations/{conversation_id}/messages")
def list_messages(conversation_id: str, session: SessionDep, after: int = 0) -> list[MessageOut]:
    get_or_404(session, Conversation, conversation_id)
    rows = session.scalars(
        select(Message).where(Message.conversation_id == conversation_id, Message.id > after).order_by(Message.id)
    ).all()
    return _messages_out(session, list(rows))


@router.post("/conversations/{conversation_id}/messages", status_code=201)
def send_message(conversation_id: str, data: MessageIn, session: SessionDep) -> MessageOut:
    conversation = get_or_404(session, Conversation, conversation_id)
    if conversation.kind == "dottie":
        raise ApiError("not_allowed", "That is a conversation between dotties; start a chat to talk to them.", 409)
    message = bus.post(
        session, conversation, sender_kind="user", sender_id=None, recipient_id=conversation.dottie_id, body=data.body
    )
    if not conversation.title:
        conversation.title = data.body.strip().splitlines()[0][:60]
    session.commit()
    return _messages_out(session, [message])[0]


@router.post("/conversations/{conversation_id}/read", status_code=204)
def mark_read(conversation_id: str, session: SessionDep) -> None:
    session.execute(
        update(Message)
        .where(Message.conversation_id == conversation_id, Message.recipient_id.is_(None), Message.read_at.is_(None))
        .values(read_at=datetime.now(UTC))
    )
    session.commit()


@router.get("/inbox")
def inbox(session: SessionDep, limit: int = 50) -> list[InboxItem]:
    """What dotties have written to the user, newest first: replies, finished scheduled tasks, anything volunteered."""
    rows = session.execute(
        select(Message, Dottie, Conversation)
        .join(Dottie, Dottie.id == Message.sender_id)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(Message.recipient_id.is_(None), Message.sender_kind.in_(["dottie", "system"]))
        .order_by(Message.id.desc())
        .limit(limit)
    ).all()
    return [
        InboxItem(
            message=_messages_out(session, [m])[0],
            dottie_id=d.id,
            dottie_name=d.name,
            dottie_hue=d.hue,
            conversation_title=c.title,
        )
        for m, d, c in rows
    ]


@router.post("/inbox/read", status_code=204)
def read_inbox(session: SessionDep) -> None:
    session.execute(
        update(Message)
        .where(Message.recipient_id.is_(None), Message.read_at.is_(None))
        .values(read_at=datetime.now(UTC))
    )
    session.commit()


@router.get("/bus")
def traffic(session: SessionDep, limit: int = 40) -> list[BusItem]:
    """Messages between dotties, newest first (each shown once: as the recipient received it)."""
    rows = session.execute(
        select(Message)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(
            Message.sender_kind == "dottie",
            Message.recipient_id.is_not(None),
            Conversation.dottie_id == Message.recipient_id,
        )
        .order_by(Message.id.desc())
        .limit(limit)
    ).scalars()
    rows = list(rows)
    names = _names(session, {m.recipient_id for m in rows})
    return [
        BusItem(message=m, recipient_name=names.get(m.recipient_id or 0, "?")) for m in _messages_out(session, rows)
    ]
