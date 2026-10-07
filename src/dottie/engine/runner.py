"""One waking of a dottie: claim its mail, start its sandbox, let the agent work, record it, go back to sleep."""

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolCall, ToolMessage
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import AsyncConnection
from psycopg.rows import dict_row
from sqlalchemy.orm import Session, sessionmaker

from ..config import Settings
from ..db import entra_password
from ..models import Conversation, Dottie, Message, Run
from . import bus
from .agent import ModelFactory, NotConfigured, build_agent
from .files import SkillFiles, WikiFiles
from .mcp import load_mcp_tools
from .sandboxes import SandboxProvider
from .tools import RunContext, build_tools, record

log = logging.getLogger(__name__)

MAX_BATCHES_PER_WAKING = 10  # conversations handled in a row before yielding the worker to someone else


class Runner:
    def __init__(
        self,
        settings: Settings,
        sessions: sessionmaker[Session],
        provider: SandboxProvider,
        model_factory: ModelFactory,
    ):
        self.settings, self.sessions, self.provider, self.model_factory = settings, sessions, provider, model_factory

    def wake(self, dottie_id: int) -> int:
        """Handle everything waiting for this dottie, then let it sleep. Returns how many batches it handled."""
        handled = 0
        try:
            while handled < MAX_BATCHES_PER_WAKING:
                with self.sessions() as s:
                    batch = bus.claim(s, dottie_id)
                    s.commit()
                    ids = [m.id for m in batch]
                if not ids:
                    break
                self._run_batch(dottie_id, ids)
                handled += 1
        finally:
            if handled:
                self._sleep(dottie_id)
        return handled

    # --- one batch: the messages of one conversation, handled as one run ---

    def _run_batch(self, dottie_id: int, message_ids: list[int]) -> None:
        with self.sessions() as s:
            dottie = s.get_one(Dottie, dottie_id)
            messages = [s.get_one(Message, i) for i in message_ids]
            conversation = s.get_one(Conversation, messages[0].conversation_id)
            first = messages[0]
            run = Run(dottie_id=dottie.id, conversation_id=conversation.id, trigger=first.sender_kind)
            s.add(run)
            dottie.last_woke_at = datetime.now(UTC)
            s.commit()
            run_id, depth = run.id, max(m.depth for m in messages)
            conversation_id, kind = conversation.id, conversation.kind
            text, trigger = self._describe(s, messages)
        record(self.sessions, dottie_id, run_id, "wake", trigger)
        status, reply = "done", ""
        try:
            reply = asyncio.run(
                asyncio.wait_for(
                    self._work(dottie_id, run_id, conversation_id, text, trigger, depth),
                    self.settings.run_timeout_seconds,
                )
            )
        except NotConfigured as e:
            status, reply = "failed", str(e)
        except TimeoutError:
            status, reply = "failed", f"I ran out of time ({self.settings.run_timeout_seconds}s) and stopped."
        except Exception as e:
            log.exception("run %s of dottie %s failed", run_id, dottie_id)
            status, reply = "failed", f"I could not finish: {e}"
        if status == "failed":
            record(self.sessions, dottie_id, run_id, "error", reply)
        with self.sessions() as s:
            conversation = s.get_one(Conversation, conversation_id)
            if kind != "dottie" and reply:  # a dottie's answer to another dottie is not delivered: it uses send_message
                bus.post(
                    s,
                    conversation,
                    sender_kind="dottie" if status == "done" else "system",
                    sender_id=dottie_id,
                    recipient_id=None,
                    body=reply,
                )
            bus.finish([s.get_one(Message, i) for i in message_ids], status)
            run = s.get_one(Run, run_id)
            run.status, run.summary, run.finished_at = status, reply[:500], datetime.now(UTC)
            s.commit()

    def _describe(self, s: Session, messages: list[Message]) -> tuple[str, str]:
        """What the dottie is told (the messages as one input) and why it woke (for the prompt and the feed)."""
        first = messages[0]
        if first.sender_kind == "dottie":
            sender = s.get(Dottie, first.sender_id) if first.sender_id else None
            who = f"{sender.name} ({sender.slug})" if sender else "another dottie"
            body = "\n\n".join(m.body for m in messages)
            return (
                f"Message from {who}:\n\n{body}",
                f"You were woken by a message from another dottie, {who}. Reply with send_message if it needs one.",
            )
        body = "\n\n".join(m.body for m in messages)
        if first.sender_kind == "scheduler":
            return body, "You were woken by one of your schedules; the task is the message below."
        return body, "You were woken by a message from the person you work for."

    async def _work(
        self, dottie_id: int, run_id: int, conversation_id: str, text: str, trigger: str, depth: int
    ) -> str:
        with self.sessions() as s:
            dottie = s.get_one(Dottie, dottie_id)
            s.expunge(dottie)
            toolkits, servers = list(dottie.tools), list(dottie.mcp_servers)
        model = self.model_factory(self.settings, dottie)

        sandbox = None
        if "shell" in toolkits:
            try:
                sandbox, ref = await asyncio.to_thread(self.provider.wake, dottie)
                if ref and ref != dottie.sandbox_ref:
                    self._remember_sandbox(dottie_id, ref)
            except Exception as e:
                log.warning("sandbox for dottie %s did not start: %s", dottie_id, e)
                record(self.sessions, dottie_id, run_id, "error", f"My computer did not start: {e}")

        wiki = WikiFiles(self.sessions, dottie_id)
        ctx = RunContext(self.sessions, dottie_id, run_id, depth, self.settings.max_message_depth)
        mcp_tools = await load_mcp_tools(servers)
        conn = await self._connect()
        try:
            agent = build_agent(
                dottie=dottie,
                model=model,
                tools=build_tools(ctx, toolkits),
                wiki=wiki,
                skills=SkillFiles(self.sessions, dottie_id),
                sandbox=sandbox,
                mcp_tools=mcp_tools,
                checkpointer=AsyncPostgresSaver(conn),
                trigger=trigger,
                timezone=self.settings.user_timezone,
            )
            reply = await self._stream(agent, text, conversation_id, dottie_id, run_id)
        finally:
            await conn.close()
            if client := getattr(model, "http_async_client", None):
                await client.aclose()
        for path in dict.fromkeys(wiki.written):
            record(self.sessions, dottie_id, run_id, "wiki", f"Updated {path}", path=path)
        return reply

    async def _stream(self, agent: Any, text: str, conversation_id: str, dottie_id: int, run_id: int) -> str:
        """Run the agent and write what it does to the feed as it happens; returns its final answer."""
        config = {"configurable": {"thread_id": conversation_id}, "recursion_limit": 120}
        reply = ""
        async for update in agent.astream({"messages": [HumanMessage(text)]}, config, stream_mode="updates"):
            for node_update in update.values():
                messages = node_update.get("messages") if isinstance(node_update, dict) else None
                if not isinstance(messages, list):
                    continue
                for message in messages:
                    if isinstance(message, AIMessage):
                        for call in message.tool_calls:
                            record(self.sessions, dottie_id, run_id, "tool", _call_text(call), tool=call["name"])
                        if not message.tool_calls and message.text:
                            reply = str(message.text)
                    elif isinstance(message, ToolMessage):
                        record(self.sessions, dottie_id, run_id, "tool_result", str(message.content)[:400])
        return reply or "(I have nothing to add.)"

    async def _connect(self) -> AsyncConnection[Any]:
        """A connection for the checkpointer (LangGraph keeps a conversation's state in PostgreSQL)."""
        extra: dict[str, Any] = {"autocommit": True, "row_factory": dict_row}
        if self.settings.database_entra_auth:
            extra["password"] = entra_password()()
        return await AsyncConnection.connect(self.settings.database_url, **extra)

    def _remember_sandbox(self, dottie_id: int, ref: str) -> None:
        with self.sessions() as s:
            s.get_one(Dottie, dottie_id).sandbox_ref = ref
            s.commit()

    def _sleep(self, dottie_id: int) -> None:
        """Put the dottie's computer to sleep (it keeps its disk) and say so in the feed."""
        with self.sessions() as s:
            ref = s.get_one(Dottie, dottie_id).sandbox_ref
        if ref:
            try:
                self.provider.sleep(ref)
            except Exception as e:
                log.warning("could not stop the sandbox of dottie %s: %s", dottie_id, e)
        record(self.sessions, dottie_id, None, "sleep", "Went back to sleep.")


def _call_text(call: ToolCall) -> str:
    args = ", ".join(f"{k}={str(v)[:80]!r}" for k, v in call["args"].items())
    return f"{call['name']}({args})"
