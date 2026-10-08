"""Telegram: linking a chat to the signed-in user (in the app), and the webhook Telegram calls (no sign-in; it carries
the bot's own secret instead)."""

import logging
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Header, Request
from pydantic import BaseModel
from sqlalchemy import select

from ..auth import UserDep
from ..db import SessionDep
from ..engine import telegram
from ..models import Dottie, TelegramLink
from .errors import ApiError

log = logging.getLogger(__name__)
router = APIRouter(prefix="/telegram", tags=["telegram"])
webhook_router = APIRouter()  # outside /api and outside the sign-in: see auth.PUBLIC_PATHS


class TelegramChat(BaseModel):
    id: int
    dottie_name: str | None
    created_at: datetime


class TelegramStatus(BaseModel):
    enabled: bool
    chats: list[TelegramChat]


class TelegramCode(BaseModel):
    code: str
    link: str  # opens the bot with the code filled in


def _api(request: Request) -> telegram.TelegramApi:
    api: telegram.TelegramApi | None = request.app.state.telegram
    if api is None:
        raise ApiError("not_configured", "Telegram is not set up: TELEGRAM_BOT_TOKEN is empty.", 503)
    return api


@router.get("")
def telegram_status(session: SessionDep, request: Request, user: UserDep) -> TelegramStatus:
    rows = session.execute(
        select(TelegramLink, Dottie.name)
        .outerjoin(Dottie, Dottie.id == TelegramLink.dottie_id)
        .where(TelegramLink.owner_id == user.id, TelegramLink.chat_id.is_not(None))
        .order_by(TelegramLink.id)
    ).all()
    chats = [TelegramChat(id=link.id, dottie_name=name, created_at=link.created_at) for link, name in rows]
    return TelegramStatus(enabled=request.app.state.telegram is not None, chats=chats)


@router.post("/codes", status_code=201)
def make_code(session: SessionDep, request: Request, user: UserDep) -> TelegramCode:
    api = _api(request)
    code = telegram.new_code(session, user.id).code or ""
    session.commit()
    try:
        username = api.bot_username()
    except Exception as e:
        raise ApiError("telegram_unreachable", f"Could not reach Telegram: {e}", 502) from e
    return TelegramCode(code=code, link=f"https://t.me/{username}?start={code}")


@router.delete("/chats/{link_id}", status_code=204)
def unlink_chat(link_id: int, session: SessionDep, user: UserDep) -> None:
    link = session.get(TelegramLink, link_id)
    if link is None or link.owner_id != user.id:
        raise ApiError("not_found", f"Chat {link_id} not found", 404)
    session.delete(link)
    session.commit()


@webhook_router.post("/telegram/webhook", include_in_schema=False)
def webhook(
    update: dict[str, Any],
    request: Request,
    secret: Annotated[str | None, Header(alias="X-Telegram-Bot-Api-Secret-Token")] = None,
) -> dict[str, bool]:
    api: telegram.TelegramApi | None = request.app.state.telegram
    if api is None or not api.accepts(secret):
        raise ApiError("unauthorized", "Not Telegram.", 401)
    try:
        if telegram.handle_update(request.app.state.session_factory, api, update):
            request.app.state.engine.nudge()
    except Exception:  # an error answered with 5xx makes Telegram resend the same update for hours
        log.exception("could not handle a Telegram update")
    return {"ok": True}
