"""What a run is made of, and how it ends: shared by the in-app runner and the agent that runs in a sandbox."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ..models import Conversation, Dottie, Message, Run
from . import bus


def describe(s: Session, messages: list[Message]) -> tuple[str, str, str]:
    """What the dottie is told (the messages as one input), why it woke (for its prompt), and the same for a person
    reading the activity feed."""
    first = messages[0]
    body = "\n\n".join(m.body for m in messages)
    if first.sender_kind == "dottie":
        sender = s.get(Dottie, first.sender_id) if first.sender_id else None
        who = f"{sender.name} ({sender.slug})" if sender else "another dottie"
        return (
            f"Message from {who}:\n\n{body}",
            f"You were woken by a message from another dottie, {who}. Reply with send_message if it needs one.",
            f"Woke up for a message from {who}.",
        )
    if first.sender_kind == "scheduler":
        return (
            body,
            "You were woken by one of your schedules; the task is the message below.",
            "Woke up for a scheduled task.",
        )
    return body, "You were woken by a message from the person you work for.", "Woke up for a message from you."


def complete_run(sessions: sessionmaker[Session], run_id: int, status: str, reply: str) -> bool:
    """End a run: deliver the answer, settle its messages, close the run. Only the first call does anything (the agent
    in a sandbox reports its own end, and the app does too when that agent dies or runs out of time)."""
    with sessions() as s:
        run = s.get(Run, run_id, with_for_update=True)
        if run is None or run.status != "running":
            return False
        conversation = s.get(Conversation, run.conversation_id) if run.conversation_id else None
        if conversation is not None and conversation.kind != "dottie" and reply:
            # a dottie's answer to another dottie is not delivered: it uses send_message
            bus.post(
                s,
                conversation,
                sender_kind="dottie" if status == "done" else "system",
                sender_id=run.dottie_id,
                recipient_id=None,
                body=reply,
            )
        bus.finish(list(s.scalars(select(Message).where(Message.run_id == run_id))), status)
        run.status, run.summary, run.finished_at = status, reply[:500], datetime.now(UTC)
        s.commit()
        return True
