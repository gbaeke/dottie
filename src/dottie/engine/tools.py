"""What a dottie can do besides read and write files: the toolkits a user switches on in its settings.

Tools run in the app, never in the sandbox: they use the database and the network with credentials the agent must not
see. Every toolkit is a function that takes the run's context and returns plain functions the agent calls.
"""

import ipaddress
import socket
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ..models import Conversation, Dottie, Event, Schedule
from . import bus, scheduler

TOOLKITS: dict[str, str] = {
    "messaging": "Write to other dotties and the user",
    "schedule": "Set its own reminders and recurring tasks",
    "web": "Read web pages",
    "shell": "A computer of its own: shell commands and working files",
}
DEFAULT_TOOLKITS = ["messaging", "schedule", "web", "shell"]
MAX_SENDS_PER_RUN = 5
MAX_FETCH_CHARS = 20_000


@dataclass
class RunContext:
    """Who is acting and why: what tools need to know about the current waking."""

    sessions: sessionmaker[Session]
    dottie_id: int
    run_id: int
    depth: int  # of the message that woke the dottie
    max_depth: int
    sends: int = 0
    notes: list[str] = field(default_factory=list)


def record(sessions: sessionmaker[Session], dottie_id: int, run_id: int | None, kind: str, text: str = "", **data: Any):
    """Add a line to the dottie's activity feed."""
    with sessions() as s:
        s.add(Event(dottie_id=dottie_id, run_id=run_id, kind=kind, text=text[:2000], data=data))
        s.commit()


def messaging(ctx: RunContext) -> list[Callable[..., str]]:
    def list_dotties() -> str:
        """List the other dotties you can write to, with what each one is for."""
        with ctx.sessions() as s:
            me = s.get_one(Dottie, ctx.dottie_id)
            mine = Dottie.owner_id == me.owner_id  # a dottie knows only dotties of the same user
            others = s.scalars(select(Dottie).where(Dottie.id != ctx.dottie_id, mine).order_by(Dottie.name)).all()
            return "\n".join(f"- {d.slug}: {d.name}, {d.role}" for d in others) or "There are no other dotties."

    def send_message(to: str, message: str) -> str:
        """Send a message to another dottie (by its slug). It is woken to read it and answers by writing back to you.
        Use it for a task that is theirs, not yours, and say everything they need: they cannot see your conversation.
        Do not send thanks or acknowledgements: every message wakes the other dottie and costs something."""
        if ctx.depth + 1 > ctx.max_depth:
            return (
                f"Not sent: this conversation has already passed through {ctx.depth} messages between dotties. "
                "Put the result in your answer to the user instead."
            )
        if ctx.sends >= MAX_SENDS_PER_RUN:
            return f"Not sent: at most {MAX_SENDS_PER_RUN} messages per waking."
        with ctx.sessions() as s:
            sender = s.get_one(Dottie, ctx.dottie_id)
            slug = to.strip().lower().removeprefix("@")
            recipient = s.scalar(select(Dottie).where(Dottie.slug == slug, Dottie.owner_id == sender.owner_id))
            if recipient is None:
                return f"No dottie called {to!r}. Use list_dotties to see who exists."
            if recipient.id == sender.id:
                return "That is you. Write it in your wiki instead."
            bus.send_between(s, sender, recipient, message, depth=ctx.depth + 1)
            s.commit()
            name = recipient.name
        ctx.sends += 1
        record(ctx.sessions, ctx.dottie_id, ctx.run_id, "sent", f"To {name}: {message}", to=to)
        return f"Sent to {name}. They will wake up and read it; any reply arrives as a new message from them."

    def tell_user(message: str) -> str:
        """Write to the person you work for outside of a normal answer: to pass on what another dottie sent you, or
        to report a result when no one is waiting for an answer. It appears in their inbox, in your latest
        conversation with them. (When they wrote to you or a schedule woke you, your answer already goes to them: do
        not repeat it.)"""
        with ctx.sessions() as s:
            latest = select(Conversation).where(Conversation.dottie_id == ctx.dottie_id, Conversation.kind == "chat")
            conversation = s.scalar(latest.order_by(Conversation.updated_at.desc()).limit(1))
            conversation = conversation or bus.new_conversation(s, ctx.dottie_id, "chat", "Updates")
            bus.post(s, conversation, sender_kind="dottie", sender_id=ctx.dottie_id, recipient_id=None, body=message)
            s.commit()
        record(ctx.sessions, ctx.dottie_id, ctx.run_id, "sent", f"To you: {message}", to="user")
        return "Delivered to the user's inbox."

    return [list_dotties, send_message, tell_user]


def schedule(ctx: RunContext) -> list[Callable[..., str]]:
    def list_schedules() -> str:
        """List your own schedules (recurring and one-off tasks) with their ids and next run."""
        with ctx.sessions() as s:
            rows = s.scalars(select(Schedule).where(Schedule.dottie_id == ctx.dottie_id).order_by(Schedule.id)).all()
            return (
                "\n".join(
                    f"- #{r.id} {r.title} ({'cron ' + r.cron if r.cron else 'once'}, {r.timezone}), "
                    f"{'next ' + r.next_run_at.isoformat() if r.next_run_at else 'finished or paused'}"
                    for r in rows
                )
                or "You have no schedules."
            )

    def create_schedule(title: str, prompt: str, cron: str = "", run_at: str = "", timezone: str = "UTC") -> str:
        """Schedule a task for yourself. When it is due you are woken with `prompt` as the message, so write the prompt
        as complete instructions. Give `cron` (five fields, e.g. '0 8 * * 1-5' for weekdays at 8:00) for a recurring
        task, or `run_at` (ISO 8601, e.g. '2026-11-02T09:30') for a single one, and the user's `timezone`."""
        when: datetime | None = None
        if run_at:
            try:
                when = datetime.fromisoformat(run_at)
            except ValueError:
                return f"{run_at!r} is not an ISO 8601 date and time."
            if when.tzinfo is None:
                try:
                    when = when.replace(tzinfo=ZoneInfo(timezone))
                except Exception:
                    return f"Unknown timezone {timezone!r}."
        problem = scheduler.validate(cron or None, when, timezone)
        if problem:
            return problem
        with ctx.sessions() as s:
            item = Schedule(
                dottie_id=ctx.dottie_id,
                title=title,
                prompt=prompt,
                cron=cron or None,
                run_at=when,
                timezone=timezone,
                created_by="dottie",
                enabled=True,
            )
            scheduler.arm(item)
            s.add(item)
            s.commit()
            nxt = item.next_run_at.isoformat() if item.next_run_at else "never (that time has passed)"
            number = item.id
        record(ctx.sessions, ctx.dottie_id, ctx.run_id, "schedule", f"Scheduled: {title}", schedule_id=number)
        return f"Scheduled #{number}: {title}. Next run: {nxt}."

    def delete_schedule(schedule_id: int) -> str:
        """Delete one of your schedules by its id."""
        with ctx.sessions() as s:
            item = s.get(Schedule, schedule_id)
            if item is None or item.dottie_id != ctx.dottie_id:
                return f"You have no schedule #{schedule_id}."
            s.delete(item)
            s.commit()
        return f"Deleted schedule #{schedule_id}."

    return [list_schedules, create_schedule, delete_schedule]


class _Text(HTMLParser):
    """The readable text of a page: no scripts, styles or markup."""

    SKIP = frozenset({"script", "style", "noscript", "svg", "head"})

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.skipping = 0

    def handle_starttag(self, tag: str, attrs: Any) -> None:  # noqa: ARG002
        if tag in self.SKIP:
            self.skipping += 1
        elif tag in {"p", "br", "li", "h1", "h2", "h3", "h4", "tr", "div"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP and self.skipping:
            self.skipping -= 1

    def handle_data(self, data: str) -> None:
        if not self.skipping and data.strip():
            self.parts.append(data.strip() + " ")


def _is_public(host: str) -> bool:
    """A page on the internet, not this machine or its network (a tool that fetches URLs must not reach the cloud's
    metadata service or the database)."""
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(host, None)}
    except socket.gaierror:
        return False
    return bool(addresses) and all(ipaddress.ip_address(a).is_global for a in addresses)


def is_public_url(url: str) -> bool:
    """An http(s) address on the internet: what the app may call for a user (a web page, an MCP server)."""
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.hostname) and _is_public(parsed.hostname or "")


def fetch_page(url: str) -> str:
    """The text of a public web page; redirects are followed one hop at a time and checked each time."""
    with httpx.Client(timeout=20, headers={"User-Agent": "Dottie/1.0"}) as client:
        for _ in range(5):
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or not _is_public(parsed.hostname):
                return "Refused: only public http(s) addresses can be fetched."
            response = client.get(url)
            if response.is_redirect and (location := response.headers.get("location")):
                url = urljoin(url, location)
                continue
            if "html" in response.headers.get("content-type", ""):
                parser = _Text()
                parser.feed(response.text)
                text = "".join(parser.parts)
            else:
                text = response.text
            prefix = "" if response.is_success else f"HTTP {response.status_code}\n"
            return prefix + text[:MAX_FETCH_CHARS]
    return "Too many redirects."


def web(ctx: RunContext) -> list[Callable[..., str]]:  # noqa: ARG001
    def fetch_url(url: str) -> str:
        """Fetch a public web page and return its text (at most about 20,000 characters)."""
        try:
            return fetch_page(url)
        except httpx.HTTPError as e:
            return f"Could not fetch {url}: {e}"

    return [fetch_url]


KITS: dict[str, Callable[[RunContext], list[Callable[..., str]]]] = {
    "messaging": messaging,
    "schedule": schedule,
    "web": web,
}


def build_tools(ctx: RunContext, enabled: list[str]) -> list[Callable[..., str]]:
    tools: list[Callable[..., str]] = []
    for name in enabled:
        if name in KITS:
            tools.extend(KITS[name](ctx))
    return tools
