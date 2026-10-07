"""The agent loop of one dottie, for one run, inside its own sandbox.

It asks the app what to do (`/context`), thinks through the app's model proxy, keeps its wiki and skills in the app,
runs its tools through the app, and works on its own computer directly: `execute` and `/workspace` are the machine it
runs on. Its memory of the conversation (the LangGraph checkpoints) is a SQLite file on this machine's disk.
"""

import asyncio
import json
import logging
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any

import httpx
from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, LocalShellBackend, StateBackend
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolCall, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from .api import Api
from .files import RemoteFiles
from .filters import ToolFilter
from .tools import remote_tools

log = logging.getLogger(__name__)


class Feed:
    """What the agent does, sent to the app's activity feed in small batches."""

    def __init__(self, api: Api):
        self.api, self.pending = api, []

    def add(self, kind: str, text: str, **data: Any) -> None:
        self.pending.append({"kind": kind, "text": text[:2000], "data": data})

    async def flush(self) -> None:
        batch, self.pending = self.pending, []
        if batch:
            await self.api.asy.post("/events", json=batch)


def proxy_model(api: Api, context: dict[str, Any]) -> BaseChatModel:
    """The model, reached through the app: the key stays there, and the token is only good for this run."""
    extra: dict[str, Any] = {}
    if context["use_responses_api"]:
        extra = {"use_responses_api": True, "store": False, "include": ["reasoning.encrypted_content"]}
    return ChatOpenAI(
        base_url=f"{api.base_url}/llm",
        api_key=api.token,  # pyright: ignore[reportArgumentType]
        model=context["model"],
        timeout=90,  # a model call that takes longer is stuck (a connection that died with the sandbox, say)
        max_retries=1,
        http_async_client=httpx.AsyncClient(timeout=120),
        **extra,
    )


def computer(workdir: Path) -> LocalShellBackend:
    """This machine, as the agent's filesystem and shell. Its commands do not inherit this process's environment: the
    run token stays out of what the agent's shell can print."""
    return LocalShellBackend(
        root_dir=workdir,
        virtual_mode=False,
        env={"PATH": "/usr/local/bin:/usr/bin:/bin:/usr/local/sbin:/usr/sbin:/sbin", "HOME": str(workdir)},
    )


async def run(api: Api, *, model: BaseChatModel | None = None, workdir: Path, state_db: Path) -> None:
    feed = Feed(api)
    context = (await api.asy.get("/context")).raise_for_status().json()
    shell = context["shell"]
    backend = CompositeBackend(
        default=computer(workdir) if shell else StateBackend(),
        routes={
            "/wiki/": RemoteFiles(api.sync, "wiki", preload=context["wiki"]),
            "/skills/": RemoteFiles(api.sync, "skills", read_only=True, preload=context["skills"]),
        },
    )
    config: RunnableConfig = {"configurable": {"thread_id": context["thread_id"]}, "recursion_limit": 120}
    state_db.parent.mkdir(parents=True, exist_ok=True)
    async with AsyncSqliteSaver.from_conn_string(str(state_db)) as saver:
        agent = create_deep_agent(
            model=model or proxy_model(api, context),
            tools=remote_tools(api, context["tools"]),
            system_prompt=context["system_prompt"],
            middleware=[ToolFilter(set() if shell else {"execute"})],
            backend=backend,
            memory=["/wiki/index.md"],
            skills=["/skills/"],
            checkpointer=saver,
            name=context["dottie"]["slug"],
        )
        messages: list[Any] = []
        if context["history"] and await saver.aget_tuple(config) is None:  # a new computer: rebuild from the transcript
            messages = list(context["history"])
        messages.append(HumanMessage(context["input"]))
        reply = await stream(agent, messages, config, feed)
    await feed.flush()
    await api.asy.post("/finish", json={"status": "done", "reply": reply})


async def stream(agent: Any, messages: list[Any], config: RunnableConfig, feed: Feed) -> str:
    """Run the agent, tell the feed what it does as it does it, return its final answer."""
    reply = ""
    async for update in agent.astream({"messages": messages}, config, stream_mode="updates"):
        for node_update in update.values():
            items = node_update.get("messages") if isinstance(node_update, dict) else None
            if not isinstance(items, list):
                continue
            for message in items:
                if isinstance(message, AIMessage):
                    for call in message.tool_calls:
                        feed.add("tool", call_text(call), tool=call["name"])
                    if not message.tool_calls and message.text:
                        reply = str(message.text)
                elif isinstance(message, ToolMessage):
                    feed.add("tool_result", str(message.content)[:400])
        await feed.flush()
    return reply or "(I have nothing to add.)"


def call_text(call: ToolCall) -> str:
    args = ", ".join(f"{k}={str(v)[:80]!r}" for k, v in call["args"].items())
    return f"{call['name']}({args})"


async def run_safely(api: Api, **options: Any) -> None:
    """`run`, and when it fails, say so to the app so the user is told (a dead agent can say nothing else)."""
    started = time.monotonic()
    log.info("run started")
    try:
        await run(api, **options)
        log.info("run finished in %.1f s", time.monotonic() - started)
    except Exception as e:
        log.exception("run failed after %.1f s", time.monotonic() - started)
        await api.asy.post("/finish", json={"status": "failed", "reply": f"I could not finish: {e}"})


async def serve(
    inbox: Path,
    *,
    workdir: Path,
    state_db: Path,
    idle_exit: float = 600,
    poll: float = 0.1,
    max_runs: int | None = None,
    **options: Any,
) -> None:
    """Stay alive between runs, so the libraries are imported once and not on every message.

    A run arrives as a ticket: a file `<run>.run` in `inbox` holding the app's address and the run's token. The runtime
    takes tickets one at a time, in order, and exits after `idle_exit` seconds without one (the app starts it again).
    """
    inbox.mkdir(parents=True, exist_ok=True)
    last, handled = time.monotonic(), 0
    while max_runs is None or handled < max_runs:
        tickets = sorted(inbox.glob("*.run"), key=lambda f: f.stat().st_mtime)
        if not tickets:
            if time.monotonic() - last > idle_exit:
                return
            await asyncio.sleep(poll)
            continue
        ticket = json.loads(tickets[0].read_text())
        waited = time.time() - tickets[0].stat().st_mtime
        tickets[0].unlink()  # the token is only on disk until it is picked up
        log.info("took ticket %s (it waited %.1f s)", tickets[0].stem, waited)
        api = Api.connect(ticket["api"], ticket["token"])
        try:
            # a run that hangs must not hold up the tickets behind it: the app's own limit applies in here too
            await asyncio.wait_for(
                run_safely(api, workdir=workdir, state_db=state_db, **options), ticket.get("timeout")
            )
        except TimeoutError:
            log.error("run took longer than %s s: given up", ticket.get("timeout"))
            await _report_failure(ticket, "I ran out of time and stopped.")
        finally:
            await api.close()
        last, handled = time.monotonic(), handled + 1


async def _report_failure(ticket: dict[str, Any], reply: str) -> None:
    """Best effort, on a fresh connection (the one the run used may be the thing that hung)."""
    api = Api.connect(ticket["api"], ticket["token"])
    try:
        await asyncio.wait_for(api.asy.post("/finish", json={"status": "failed", "reply": reply}), 20)
    except Exception:
        log.exception("could not report the failure to the app")
    finally:
        await api.close()


def cli() -> None:
    """`python -m dottie_runtime serve`: run until idle, handling tickets from `$DOTTIE_WORKDIR/.dottie/inbox`."""
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stderr, force=True
    )  # stderr goes to /workspace/.dottie/last.log
    log.info("runtime started (pid %s)", os.getpid())
    workdir = Path(os.environ.get("DOTTIE_WORKDIR", "/workspace"))
    state = workdir / ".dottie"
    try:
        asyncio.run(serve(state / "inbox", workdir=workdir, state_db=state / "state.db"))
    except Exception:
        traceback.print_exc()
        sys.exit(1)
