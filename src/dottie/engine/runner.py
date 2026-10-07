"""One waking of a dottie: claim its mail, let the agent work (its sandbox starts only if used), record it, sleep."""

import asyncio
import logging
import secrets
from datetime import UTC, datetime
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolCall, ToolMessage
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import AsyncConnection
from psycopg.rows import dict_row
from sqlalchemy.orm import Session, sessionmaker

from ..config import Settings
from ..db import entra_password
from ..models import Dottie, Message, Run
from . import bus
from .agent import ModelFactory, NotConfigured, build_agent
from .files import SkillFiles, WikiFiles
from .mcp import load_mcp_tools
from .runs import complete_run, describe
from .sandbox_agent import SandboxAgent
from .sandboxes import LazySandbox, SandboxProvider
from .secrets import SecretStore
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
        secrets: SecretStore | None = None,
    ):
        self.settings, self.sessions, self.provider, self.model_factory = settings, sessions, provider, model_factory
        self.secrets = secrets
        # Two ways to run the agent: its loop in this process (the sandbox is only its computer), or the loop in the
        # sandbox itself (this process then only wakes it and waits). The second needs a sandbox to run in.
        self.agent_in_sandbox = settings.agent_mode == "sandbox" and provider.name != "none"
        self.sandbox_agent = SandboxAgent(settings, sessions, provider)

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
            first = messages[0]
            run = Run(
                dottie_id=dottie.id,
                conversation_id=first.conversation_id,
                trigger=first.sender_kind,
                token=secrets.token_urlsafe(32),  # what an agent in a sandbox calls back with, until the run ends
            )
            s.add(run)
            s.flush()
            for m in messages:
                m.run_id = run.id
            dottie.last_woke_at = datetime.now(UTC)
            run_id, depth = run.id, max(m.depth for m in messages)
            conversation_id = first.conversation_id
            text, trigger, headline = describe(s, messages)
            s.commit()
        record(self.sessions, dottie_id, run_id, "wake", headline)
        status, reply = "done", ""
        try:
            if self.agent_in_sandbox:
                status, reply = self.sandbox_agent.run(dottie_id, run_id)
            else:
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
        if status == "failed" and reply:
            record(self.sessions, dottie_id, run_id, "error", reply)
        complete_run(self.sessions, run_id, status, reply)

    async def _work(
        self, dottie_id: int, run_id: int, conversation_id: str, text: str, trigger: str, depth: int
    ) -> str:
        with self.sessions() as s:
            dottie = s.get_one(Dottie, dottie_id)
            s.expunge(dottie)
            toolkits, servers = list(dottie.tools), list(dottie.mcp_servers)
        model = self.model_factory(self.settings, dottie)

        sandbox = (
            LazySandbox(self.provider, dottie, lambda ref: self._remember_sandbox(dottie_id, ref))
            if "shell" in toolkits
            else None
        )

        wiki = WikiFiles(self.sessions, dottie_id)
        ctx = RunContext(self.sessions, dottie_id, run_id, depth, self.settings.max_message_depth)
        mcp_tools, problems = await load_mcp_tools(
            servers, owner_id=dottie.owner_id, store=self.secrets, public_only=self.settings.auth_enabled
        )
        for problem in problems:  # the user sees why a server's tools are missing
            record(self.sessions, dottie_id, run_id, "error", problem)
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
            dottie = s.get_one(Dottie, dottie_id)
            dottie.sandbox_ref, dottie.sandbox_awake = ref, True
            s.commit()

    def _sleep(self, dottie_id: int) -> None:
        with self.sessions() as s:
            warm = s.get_one(Dottie, dottie_id).sandbox_awake and self.settings.sandbox_idle_seconds > 0
        if warm:  # its computer keeps running for follow-ups; the engine records the sleep when it stops it
            seconds = self.settings.sandbox_idle_seconds
            record(self.sessions, dottie_id, None, "idle", f"Done. Staying awake for {seconds} s in case you reply.")
        else:
            record(self.sessions, dottie_id, None, "sleep", "Went back to sleep.")


def _call_text(call: ToolCall) -> str:
    args = ", ".join(f"{k}={str(v)[:80]!r}" for k, v in call["args"].items())
    return f"{call['name']}({args})"
