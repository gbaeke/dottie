"""Telegram as one more way to talk to dotties: a message from the chat is a message on the bus, and what a dottie
answers in that conversation is sent back to the chat.

One bot serves everyone. A chat proves who it belongs to with a one-time code made in the app (`/start <code>`), and
then the person picks which of their dotties the chat talks to (`/dottie`). Every dottie lookup goes through the link's
owner.
"""

import hashlib
import hmac
import logging
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from ..config import Settings
from ..models import Conversation, Dottie, Message, TelegramLink
from . import bus

log = logging.getLogger(__name__)

CODE_VALID_FOR = timedelta(hours=1)
MAX_LENGTH = 4096  # what Telegram accepts in one message
NOTED = "noted"  # status of a message a dottie sent to the chat on its own: in the conversation, not to be sent again

HELP = (
    "I connect you to your dotties.\n\n"
    "/dottie: choose which dottie you talk to\n"
    "/new: start a fresh conversation with the current dottie\n\n"
    "Anything else you write goes to the current dottie."
)


class TelegramApi:
    """The Bot API. `_call` is the only place that touches the network (tests replace it)."""

    def __init__(self, token: str):
        self.token = token
        self._username: str | None = None
        self._http = httpx.Client(timeout=15)  # one connection reused, instead of a new TLS handshake per message

    @classmethod
    def from_settings(cls, settings: Settings) -> TelegramApi | None:
        return cls(settings.telegram_bot_token.get_secret_value()) if settings.telegram_enabled else None

    @property
    def webhook_secret(self) -> str:
        """What Telegram sends back with every update, so only it can use the webhook. Derived from the token: one
        secret fewer to configure, and it changes when the token does."""
        return hashlib.sha256(f"dottie-telegram:{self.token}".encode()).hexdigest()[:48]

    def _call(self, method: str, **payload: Any) -> Any:
        res = self._http.post(f"https://api.telegram.org/bot{self.token}/{method}", json=payload)
        data = res.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram {method} failed: {data.get('description', res.status_code)}")
        return data["result"]

    def send(self, chat_id: int, text: str, buttons: list[tuple[str, str]] | None = None) -> None:
        """Send text (split to fit), with optional buttons: (label, what the bot is sent when it is pressed)."""
        chunks = [text[i : i + MAX_LENGTH] for i in range(0, len(text), MAX_LENGTH)] or ["(empty)"]
        for i, chunk in enumerate(chunks):
            extra: dict[str, Any] = {}
            if buttons and i == len(chunks) - 1:
                extra["reply_markup"] = {"inline_keyboard": [[{"text": t, "callback_data": d}] for t, d in buttons]}
            self._call("sendMessage", chat_id=chat_id, text=chunk, **extra)

    def answer_callback(self, callback_id: str) -> None:
        self._call("answerCallbackQuery", callback_query_id=callback_id)

    def set_webhook(self, url: str) -> None:
        self._call(
            "setWebhook", url=url, secret_token=self.webhook_secret, allowed_updates=["message", "callback_query"]
        )

    def accepts(self, given: str | None) -> bool:
        """Whether a webhook call carries the secret that only Telegram was given."""
        return given is not None and hmac.compare_digest(given, self.webhook_secret)

    def bot_username(self) -> str:
        if self._username is None:
            self._username = str(self._call("getMe")["username"])
        return self._username


def new_code(session: Session, owner_id: str) -> TelegramLink:
    """A pending link: its code is what the person sends the bot. Old unused codes are dropped."""
    session.execute(
        delete(TelegramLink).where(
            TelegramLink.chat_id.is_(None), TelegramLink.created_at < datetime.now(UTC) - CODE_VALID_FOR
        )
    )
    link = TelegramLink(owner_id=owner_id, code=secrets.token_urlsafe(16))
    session.add(link)
    session.flush()
    return link


# --- from the chat to the dotties ---


def handle_update(sessions: sessionmaker[Session], api: TelegramApi, update: dict[str, Any]) -> bool:
    """One update from Telegram. Returns whether a message was put on the bus (so the engine should look for work)."""
    if callback := update.get("callback_query"):  # a button under the dottie list
        api.answer_callback(callback["id"])
        chat, text = (callback.get("message") or {}).get("chat") or {}, callback.get("data") or ""
    else:
        message = update.get("message") or {}
        chat, text = message.get("chat") or {}, (message.get("text") or "").strip()
    if chat.get("type") != "private" or not text:  # a bot in a group would answer to strangers
        return False
    with sessions() as s:
        posted = _handle_text(s, api, chat["id"], text)
        s.commit()
    return posted


def _handle_text(s: Session, api: TelegramApi, chat_id: int, text: str) -> bool:
    command, _, arg = text.partition(" ")
    command, arg = command.split("@")[0].lower(), arg.strip()
    link = s.scalar(select(TelegramLink).where(TelegramLink.chat_id == chat_id))
    if command == "/start" and arg:
        api.send(chat_id, _claim(s, chat_id, arg))
        return False
    if link is None:
        api.send(
            chat_id, "This chat is not linked to a person yet. Open Dottie, go to Connect, and link Telegram there."
        )
        return False
    if command in ("/start", "/help"):
        api.send(chat_id, HELP)
    elif command == "/dottie":
        _choose(s, api, link, chat_id, arg)
    elif command == "/new":
        dottie = s.get(Dottie, link.dottie_id) if link.dottie_id else None
        if dottie is None:
            _choose(s, api, link, chat_id, "")
        else:
            _start_conversation(s, link, dottie)
            api.send(chat_id, f"A fresh conversation with {dottie.name}.")
    elif command.startswith("/"):
        api.send(chat_id, HELP)
    else:
        return _forward(s, api, link, chat_id, text)
    return False


def _claim(s: Session, chat_id: int, code: str) -> str:
    link = s.scalar(select(TelegramLink).where(TelegramLink.code == code))
    if link is None or link.created_at < datetime.now(UTC) - CODE_VALID_FOR:
        return "That code is not valid (any more). Make a new one in Dottie, under Connect."
    s.execute(delete(TelegramLink).where(TelegramLink.chat_id == chat_id))  # a chat has one link: the newest
    link.chat_id, link.code = chat_id, None
    s.flush()
    return "Linked. Use /dottie to choose which dottie you talk to."


def _owned(s: Session, link: TelegramLink) -> list[Dottie]:
    return list(s.scalars(select(Dottie).where(Dottie.owner_id == link.owner_id).order_by(Dottie.name)))


def _choose(s: Session, api: TelegramApi, link: TelegramLink, chat_id: int, wanted: str) -> None:
    """Switch to the dottie named `wanted` (name or slug), or offer the choice."""
    dotties = _owned(s, link)
    if not dotties:
        api.send(chat_id, "You have no dotties yet. Make one in Dottie first.")
        return
    picked = next((d for d in dotties if wanted.lower() in (d.slug.lower(), d.name.lower())), None)
    if picked is None:
        title = f"There is no dottie called {wanted}. Which one?" if wanted else "Which dottie do you want to talk to?"
        api.send(chat_id, title, [(d.name, f"/dottie {d.slug}") for d in dotties])
        return
    if link.dottie_id != picked.id or link.conversation_id is None:
        _start_conversation(s, link, picked)
    api.send(chat_id, f"You are talking to {picked.name}.")


def _start_conversation(s: Session, link: TelegramLink, dottie: Dottie) -> None:
    link.dottie_id = dottie.id
    link.conversation_id = bus.new_conversation(s, dottie.id, "chat", "Telegram").id
    # what the previous dottie still says is not for this conversation: only what comes from now on is sent
    link.sent_up_to = s.execute(select(func.coalesce(func.max(Message.id), 0))).scalar_one()


def _forward(s: Session, api: TelegramApi, link: TelegramLink, chat_id: int, text: str) -> bool:
    conversation = s.get(Conversation, link.conversation_id) if link.conversation_id else None
    if conversation is None:
        dotties = _owned(s, link)
        if len(dotties) != 1:  # with one dottie there is nothing to choose
            _choose(s, api, link, chat_id, "")
            return False
        _start_conversation(s, link, dotties[0])
        conversation = s.get_one(Conversation, link.conversation_id)
    bus.post(s, conversation, sender_kind="user", sender_id=None, recipient_id=conversation.dottie_id, body=text)
    return True


# --- from the dotties to the chat ---


def record_outgoing(s: Session, link: TelegramLink, dottie: Dottie, message: str) -> None:
    """A dottie wrote to the chat on its own (send_telegram): put it in the chat's conversation, so it is there to read
    and the person's reply continues from it (`runs.describe` hands it to the dottie). The chat then talks to this
    dottie, whoever it talked to before: a reply is to the one that wrote."""
    conversation = s.get(Conversation, link.conversation_id) if link.conversation_id else None
    if link.dottie_id != dottie.id or conversation is None:
        _start_conversation(s, link, dottie)
        conversation = s.get_one(Conversation, link.conversation_id)
    bus.post(s, conversation, sender_kind="dottie", sender_id=dottie.id, recipient_id=None, body=message, status=NOTED)


def deliver(sessions: sessionmaker[Session], api: TelegramApi) -> int:
    """Send each linked chat what its dottie has written in the chat's conversation since last time. A failure stops
    that chat for now (the same messages are tried again on the next pass). Returns how many were sent."""
    sent = 0
    with sessions() as s:
        for link in s.scalars(select(TelegramLink).where(TelegramLink.chat_id.is_not(None))):
            if link.conversation_id is None or link.chat_id is None:
                continue
            rows = s.scalars(
                select(Message)
                .where(
                    Message.conversation_id == link.conversation_id,
                    Message.id > link.sent_up_to,
                    Message.recipient_id.is_(None),
                    Message.sender_kind.in_(["dottie", "system"]),
                    Message.status != NOTED,  # what a dottie sent with send_telegram already went out
                )
                .order_by(Message.id)
            ).all()
            for message in rows:
                try:
                    api.send(link.chat_id, message.body)
                except Exception:
                    log.exception("could not send to Telegram chat %s", link.chat_id)
                    break
                link.sent_up_to = message.id
                sent += 1
        s.commit()
    return sent


def register_webhook(api: TelegramApi | None, public_url: str) -> None:
    """Tell Telegram where to send updates. Best effort: without a public address the bot simply does not hear."""
    if api is None:
        return
    if not public_url:
        log.warning("TELEGRAM_BOT_TOKEN is set but neither TELEGRAM_WEBHOOK_URL nor PUBLIC_URL: no webhook")
        return
    try:
        api.set_webhook(f"{public_url.rstrip('/')}/telegram/webhook")
    except Exception:
        log.exception("could not register the Telegram webhook")
