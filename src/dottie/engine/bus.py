"""The messaging layer: conversations and a durable inbox in PostgreSQL.

Everything that can wake a dottie (a person typing, the scheduler, another dottie) is a `pending` message here. The
dispatcher watches for them, so there is exactly one path into a sleeping dottie. To move to Azure Service Bus later,
only `post` and `claim` change.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..models import Conversation, Dottie, Message


def new_conversation(
    session: Session, dottie_id: int, kind: str, title: str = "", peer_id: int | None = None
) -> Conversation:
    conversation = Conversation(id=uuid.uuid4().hex, dottie_id=dottie_id, kind=kind, title=title, peer_id=peer_id)
    session.add(conversation)
    session.flush()
    return conversation


def peer_conversation(session: Session, owner: Dottie, peer: Dottie) -> Conversation:
    """The thread `owner` has with another dottie: one per pair, created on first contact."""
    found = session.scalar(
        select(Conversation).where(
            Conversation.dottie_id == owner.id, Conversation.kind == "dottie", Conversation.peer_id == peer.id
        )
    )
    return found or new_conversation(session, owner.id, "dottie", f"With {peer.name}", peer.id)


def post(
    session: Session,
    conversation: Conversation,
    *,
    sender_kind: str,
    sender_id: int | None,
    recipient_id: int | None,
    body: str,
    depth: int = 0,
    status: str | None = None,
) -> Message:
    """Put a message in a conversation. One addressed to a dottie is `pending` until the dottie has handled it."""
    message = Message(
        conversation_id=conversation.id,
        sender_kind=sender_kind,
        sender_id=sender_id,
        recipient_id=recipient_id,
        body=body,
        depth=depth,
        status=status or ("pending" if recipient_id is not None else "done"),
    )
    session.add(message)
    conversation.updated_at = datetime.now(UTC)
    session.flush()
    return message


def send_between(session: Session, sender: Dottie, recipient: Dottie, body: str, depth: int) -> Message:
    """A dottie writes to another one. The recipient's copy wakes it; the sender keeps a record in its own thread."""
    post(
        session,
        peer_conversation(session, sender, recipient),
        sender_kind="dottie",
        sender_id=sender.id,
        recipient_id=recipient.id,
        body=body,
        depth=depth,
        status="done",
    )
    return post(
        session,
        peer_conversation(session, recipient, sender),
        sender_kind="dottie",
        sender_id=sender.id,
        recipient_id=recipient.id,
        body=body,
        depth=depth,
    )


def dotties_with_mail(session: Session) -> list[int]:
    """Who has something pending, longest-waiting first."""
    rows = session.scalars(
        select(Message.recipient_id)
        .where(Message.status == "pending", Message.recipient_id.is_not(None))
        .group_by(Message.recipient_id)
        .order_by(func.min(Message.id))
    )
    return [r for r in rows if r is not None]


def claim(session: Session, dottie_id: int) -> list[Message]:
    """Take the oldest conversation's pending messages for processing (so a second worker cannot take them too)."""
    first = session.scalar(
        select(Message.conversation_id)
        .where(Message.recipient_id == dottie_id, Message.status == "pending")
        .order_by(Message.id)
        .limit(1)
    )
    if first is None:
        return []
    ids = list(
        session.scalars(
            select(Message.id)
            .where(Message.recipient_id == dottie_id, Message.status == "pending", Message.conversation_id == first)
            .order_by(Message.id)
            .with_for_update(skip_locked=True)
        )
    )
    if ids:
        session.execute(update(Message).where(Message.id.in_(ids)).values(status="processing"))
    return list(session.scalars(select(Message).where(Message.id.in_(ids)).order_by(Message.id)))


def finish(messages: list[Message], status: str) -> None:
    for m in messages:
        m.status = status


def requeue_orphans(session: Session) -> None:
    """After a crash: messages that were being processed go back in the inbox."""
    session.execute(update(Message).where(Message.status == "processing").values(status="pending"))
