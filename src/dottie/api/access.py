"""Who may see what: everything belongs to a user through its dottie, and a thing that is not yours does not exist.

Every lookup by id goes through here, and answers 404 (not 403) for someone else's: a stranger learns nothing about
what exists.
"""

from sqlalchemy.orm import Session

from ..auth import User
from ..models import Conversation, Dottie, Schedule
from .errors import ApiError


def owned_dottie(session: Session, user: User, dottie_id: int) -> Dottie:
    dottie = session.get(Dottie, dottie_id)
    if dottie is None or dottie.owner_id != user.id:
        raise ApiError("not_found", f"Dottie {dottie_id} not found", 404)
    return dottie


def owned_conversation(session: Session, user: User, conversation_id: str) -> Conversation:
    conversation = session.get(Conversation, conversation_id)
    if conversation is None or owned_or_none(session, user, conversation.dottie_id) is None:
        raise ApiError("not_found", f"Conversation {conversation_id} not found", 404)
    return conversation


def owned_schedule(session: Session, user: User, schedule_id: int) -> Schedule:
    schedule = session.get(Schedule, schedule_id)
    if schedule is None or owned_or_none(session, user, schedule.dottie_id) is None:
        raise ApiError("not_found", f"Schedule {schedule_id} not found", 404)
    return schedule


def owned_or_none(session: Session, user: User, dottie_id: int) -> Dottie | None:
    dottie = session.get(Dottie, dottie_id)
    return dottie if dottie is not None and dottie.owner_id == user.id else None
