"""Telegram: a chat is linked with a code made in the app, the person picks the dottie, answers come back."""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from dottie.api.app import create_app
from dottie.engine.telegram import TelegramApi
from dottie.models import Run

from .fakes import ScriptedModel
from .test_multi_user import app, make, sign_in  # noqa: F401  (the fixture and the helpers for two signed-in users)

CHAT = 4242


class FakeTelegram(TelegramApi):
    """The Bot API without the network: every call is recorded."""

    def __init__(self):
        super().__init__("123:fake-token")
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.down = False

    def _call(self, method: str, **payload: Any) -> Any:
        if self.down:
            raise RuntimeError("Telegram is down")
        self.calls.append((method, payload))
        return {"username": "dottie_bot"} if method == "getMe" else True

    def texts(self, chat_id: int = CHAT) -> list[str]:
        return [p["text"] for m, p in self.calls if m == "sendMessage" and p["chat_id"] == chat_id]


@pytest.fixture
def telegram() -> FakeTelegram:
    return FakeTelegram()


@pytest.fixture
def tg(settings, scripts, telegram):
    """The app with the fake bot; `say` is a person typing in the Telegram chat."""

    queues = {}

    def model_for(_settings, dottie):
        queues.setdefault(dottie.slug, iter(scripts.get(dottie.slug, [AIMessage("Hello.")])))
        return ScriptedModel(messages=queues[dottie.slug])

    with TestClient(create_app(settings, model_factory=model_for, telegram=telegram)) as c:
        yield c


def say(client, text: str, chat: int = CHAT, secret: str | None = None, button: bool = False):
    """A person typing in the Telegram chat (or pressing a button, which sends its data)."""
    where = {"id": chat, "type": "private"}
    update = (
        {"callback_query": {"id": "cb", "data": text, "message": {"chat": where}}}
        if button
        else {"message": {"chat": where, "text": text}}
    )
    headers = {"X-Telegram-Bot-Api-Secret-Token": secret or client.app.state.telegram.webhook_secret}
    return client.post("/telegram/webhook", json=update, headers=headers)


def deliver(client) -> None:
    """Let the engine wake whoever has mail, then send what they answered."""
    engine = client.app.state.engine
    engine.tick()
    engine.wait_idle()
    engine.tick()
    engine.wait_idle()


def link(client, chat: int = CHAT) -> None:
    code = client.post("/api/telegram/codes").json()["code"]
    assert say(client, f"/start {code}", chat).status_code == 200


def test_telegram_is_off_without_a_bot(client):
    assert client.get("/api/telegram").json() == {"enabled": False, "chats": []}
    assert client.post("/api/telegram/codes").json()["error"]["code"] == "not_configured"
    assert client.post("/telegram/webhook", json={}).status_code == 401


def test_only_telegram_may_call_the_webhook(tg):
    assert say(tg, "hi", secret="wrong").status_code == 401
    assert tg.post("/telegram/webhook", json={}).status_code == 401


def test_a_chat_is_linked_with_a_code_that_works_once(tg, telegram):
    made = tg.post("/api/telegram/codes")
    assert made.status_code == 201 and made.json()["link"] == f"https://t.me/dottie_bot?start={made.json()['code']}"
    say(tg, f"/start {made.json()['code']}")
    assert "Linked" in telegram.texts()[-1]
    assert [c["dottie_name"] for c in tg.get("/api/telegram").json()["chats"]] == [None]
    say(tg, f"/start {made.json()['code']}", chat=7)  # used up
    assert "not valid" in telegram.texts(7)[-1]
    say(tg, "/start nonsense", chat=8)
    assert "not valid" in telegram.texts(8)[-1]


def test_an_unlinked_chat_cannot_talk_to_anyone(tg, telegram):
    make(tg, "Ada")
    say(tg, "hello")
    assert "not linked" in telegram.texts()[-1]
    assert tg.get("/api/dotties/1/conversations").json() == []


def test_the_person_picks_the_dottie_and_the_answer_comes_back(tg, telegram, scripts):
    make(tg, "Ada")
    make(tg, "Bo")
    scripts["bo"] = [AIMessage("Bo here.")]
    link(tg)
    say(tg, "hello")  # two dotties and none chosen: it asks
    sent = [p for m, p in telegram.calls if m == "sendMessage"][-1]
    assert [b[0]["text"] for b in sent["reply_markup"]["inline_keyboard"]] == ["Ada", "Bo"]
    say(tg, "/dottie bo", button=True)  # a button press
    assert "talking to Bo" in telegram.texts()[-1]
    say(tg, "hello Bo")
    deliver(tg)
    assert telegram.texts()[-1] == "Bo here."
    assert tg.get("/api/telegram").json()["chats"][0]["dottie_name"] == "Bo"
    deliver(tg)
    assert telegram.texts().count("Bo here.") == 1  # not twice


def test_one_dottie_needs_no_choosing_and_new_starts_a_fresh_conversation(tg, telegram):
    ada = make(tg, "Ada")
    link(tg)
    say(tg, "hello")
    first = tg.get(f"/api/dotties/{ada['id']}/conversations").json()
    assert [c["title"] for c in first] == ["Telegram"]
    say(tg, "/new")
    assert len(tg.get(f"/api/dotties/{ada['id']}/conversations").json()) == 2


def test_an_answer_from_before_switching_is_not_sent_to_the_new_dottie_chat(tg, telegram):
    make(tg, "Ada")
    make(tg, "Bo")
    link(tg)
    say(tg, "/dottie ada")
    say(tg, "hello")
    tg.app.state.engine.tick()
    tg.app.state.engine.wait_idle()
    say(tg, "/dottie bo")  # Ada's answer is waiting, but the chat has moved on
    deliver(tg)
    assert "Hello." not in telegram.texts()


def test_long_answers_are_split_and_a_failure_is_retried(tg, telegram, scripts):
    make(tg, "Ada")
    scripts["ada"] = [AIMessage("x" * 5000)]
    link(tg)
    say(tg, "hello")
    telegram.down = True
    deliver(tg)  # the answer is ready but cannot be sent
    telegram.down = False
    deliver(tg)  # ...and is sent on the next pass
    assert [len(t) for t in telegram.texts()[-2:]] == [4096, 904]


def test_groups_are_ignored(tg, telegram):
    make(tg, "Ada")
    update = {"message": {"chat": {"id": -5, "type": "group"}, "text": "/start x"}}
    headers = {"X-Telegram-Bot-Api-Secret-Token": telegram.webhook_secret}
    assert tg.post("/telegram/webhook", json=update, headers=headers).status_code == 200
    assert telegram.texts(-5) == []


def test_chats_belong_to_a_user(app):  # noqa: F811
    telegram = FakeTelegram()
    app.state.telegram = telegram
    ann, bob = sign_in(app, "ann"), sign_in(app, "bob")
    make(ann, "Ada")
    make(bob, "Bea")
    link(ann, 1)
    link(bob, 2)
    assert len(ann.get("/api/telegram").json()["chats"]) == 1 and len(bob.get("/api/telegram").json()["chats"]) == 1
    say(ann, "/dottie bea", chat=1)  # Bob's dottie does not exist for Ann's chat
    assert "no dottie called bea" in telegram.texts(1)[-1]
    chat_id = ann.get("/api/telegram").json()["chats"][0]["id"]
    assert bob.delete(f"/api/telegram/chats/{chat_id}").status_code == 404
    assert ann.delete(f"/api/telegram/chats/{chat_id}").status_code == 204
    say(ann, "hello", chat=1)
    assert "not linked" in telegram.texts(1)[-1]


def call_send_telegram(message: str) -> AIMessage:
    return AIMessage("", tool_calls=[{"name": "send_telegram", "args": {"message": message}, "id": "t1"}])


def test_a_schedule_can_send_to_telegram(tg, telegram, scripts):
    from datetime import UTC, datetime, timedelta

    from dottie.engine import scheduler

    ada = make(tg, "Ada")
    link(tg)
    scripts["ada"] = [call_send_telegram("Good morning!"), AIMessage("Sent it.")]
    soon = (datetime.now(UTC) + timedelta(seconds=1)).isoformat()
    tg.post(
        f"/api/dotties/{ada['id']}/schedules",
        json={"title": "Morning", "prompt": "Send good morning to Telegram.", "run_at": soon},
    )
    with tg.app.state.session_factory() as s:
        scheduler.fire_due(s, datetime.now(UTC) + timedelta(seconds=5))
        s.commit()
    tg.app.state.engine.tick()
    tg.app.state.engine.wait_idle()
    assert "Ada: Good morning!" in telegram.texts()  # the chat was not talking to Ada yet: it is told who writes


def test_without_a_linked_chat_the_tool_says_so(tg, telegram, scripts):
    ada = make(tg, "Ada")
    scripts["ada"] = [call_send_telegram("Hello"), AIMessage("Could not.")]
    conversation = tg.post(f"/api/dotties/{ada['id']}/conversations", json={}).json()
    tg.post(f"/api/conversations/{conversation['id']}/messages", json={"body": "Tell me on Telegram."})
    tg.app.state.engine.tick()
    tg.app.state.engine.wait_idle()
    feed = tg.get(f"/api/dotties/{ada['id']}/events").json()
    assert any("no Telegram chat is linked" in e["text"] for e in feed)
    assert telegram.texts() == []


def test_the_tool_writes_only_to_the_chats_of_the_dottie_s_owner(app):  # noqa: F811
    from dottie.engine.tools import RunContext, build_tools

    telegram = FakeTelegram()
    ann, bob = sign_in(app, "ann"), sign_in(app, "bob")
    ada, bea = make(ann, "Ada"), make(bob, "Bea")
    app.state.telegram = telegram
    link(bob, 2)  # only Bob has a chat
    sent = len(telegram.texts(2))

    def send_as(dottie: dict, message: str) -> str:
        with app.state.session_factory() as s:
            run = Run(dottie_id=dottie["id"], trigger="user")
            s.add(run)
            s.commit()
            run_id = run.id
        ctx = RunContext(app.state.session_factory, dottie["id"], run_id, 0, 5, telegram)
        return next(t for t in build_tools(ctx, ["messaging"]) if t.__name__ == "send_telegram")(message)

    assert "no Telegram chat is linked" in send_as(ada, "for Ann")  # Ann has none: nothing goes to Bob's
    assert len(telegram.texts(2)) == sent
    assert send_as(bea, "for Bob") == "Sent on Telegram (1 chat)."
    assert telegram.texts(2)[-1] == "Bea: for Bob"


def test_a_message_the_dottie_sent_is_in_the_chat_and_a_reply_continues_from_it(tg, telegram, scripts):
    from dottie.engine import runs
    from dottie.models import Message

    ada = make(tg, "Ada")
    make(tg, "Bo")
    link(tg)
    say(tg, "/dottie bo")  # the chat talks to Bo...
    scripts["ada"] = [call_send_telegram("Your report is ready."), AIMessage("Done.")]
    conversation = tg.post(f"/api/dotties/{ada['id']}/conversations", json={}).json()
    tg.post(f"/api/conversations/{conversation['id']}/messages", json={"body": "Send me the report news."})
    deliver(tg)
    assert telegram.texts()[-1] == "Ada: Your report is ready."  # ...so it is told Ada wrote
    deliver(tg)
    assert telegram.texts().count("Ada: Your report is ready.") == 1 and "Your report is ready." not in telegram.texts()
    say(tg, "Thanks, and the totals?")  # the chat now talks to Ada, who knows what it just said
    with tg.app.state.session_factory() as s:
        reply = s.query(Message).filter(Message.body == "Thanks, and the totals?").one()
        assert reply.recipient_id == ada["id"]
        text, _, _ = runs.describe(s, [reply])
    assert text == "[You wrote to them on Telegram: Your report is ready.]\n\nThanks, and the totals?"
