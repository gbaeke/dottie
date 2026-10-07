"""What the agent running inside a dottie's sandbox calls back to.

The sandbox holds no database or model credentials. It holds one random token for one run, and with it can only do what
the agent could do anyway: ask for its context, think through the model proxy, read and write its own wiki, call its
own tools, report what it does, and say it is done. The token stops working when the run ends.
"""

import asyncio
import json
from dataclasses import dataclass
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import StreamingResponse
from langchain_core.tools import BaseTool, StructuredTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import BaseModel
from sqlalchemy import select
from starlette.background import BackgroundTask

from ..engine import runs
from ..engine.agent import AZURE_COGNITIVE_SCOPE, system_prompt
from ..engine.files import SkillFiles, WikiFiles
from ..engine.mcp import load_mcp_tools
from ..engine.tools import RunContext, build_tools, record
from ..models import Dottie, Message, Run
from .errors import ApiError

router = APIRouter(prefix="/internal", include_in_schema=False)  # not part of the public API or its client


@dataclass
class RunInfo:
    run_id: int
    dottie_id: int
    conversation_id: str | None


def current_run(request: Request, authorization: Annotated[str | None, Header()] = None) -> RunInfo:
    token = (authorization or "").removeprefix("Bearer ").strip()
    if not token:
        raise ApiError("unauthorized", "A run token is required.", 401)
    with request.app.state.session_factory() as s:
        run = s.scalar(select(Run).where(Run.token == token, Run.status == "running"))
        if run is None:
            raise ApiError("unauthorized", "This run has ended or the token is wrong.", 401)
        return RunInfo(run.id, run.dottie_id, run.conversation_id)


RunDep = Annotated[RunInfo, Depends(current_run)]


# --- context ---------------------------------------------------------------------------------------------------------


async def run_tools(request: Request, run: RunInfo) -> dict[str, BaseTool]:
    """The tools of this run, by name: the toolkits and the MCP servers. They run here, where the credentials are."""
    cache: dict[int, dict[str, BaseTool]] = request.app.state.run_tools
    if run.run_id not in cache:
        sessions = request.app.state.session_factory
        with sessions() as s:
            dottie = s.get_one(Dottie, run.dottie_id)
            toolkits, servers = [t for t in dottie.tools if t != "shell"], list(dottie.mcp_servers)
            owner_id = dottie.owner_id
            depth = max((m.depth for m in s.scalars(select(Message).where(Message.run_id == run.run_id))), default=0)
        ctx = RunContext(sessions, run.dottie_id, run.run_id, depth, request.app.state.settings.max_message_depth)
        tools: list[BaseTool] = [StructuredTool.from_function(f) for f in build_tools(ctx, toolkits)]
        mcp_tools, problems = await load_mcp_tools(
            servers,
            owner_id=owner_id,
            store=request.app.state.secret_store,
            public_only=request.app.state.settings.auth_enabled,
        )
        tools += mcp_tools
        for problem in problems:  # the user sees why a server's tools are missing
            record(sessions, run.dottie_id, run.run_id, "error", problem)
        if len(cache) > 200:  # runs whose agent died without saying so
            cache.pop(next(iter(cache)))
        cache[run.run_id] = {t.name: t for t in tools}
    return cache[run.run_id]


def _schema(tool: BaseTool) -> dict[str, Any]:
    return convert_to_openai_tool(tool)["function"]["parameters"]


@router.get("/context")
async def context(request: Request, run: RunDep) -> dict[str, Any]:
    settings = request.app.state.settings
    tools = await run_tools(request, run)
    sessions = request.app.state.session_factory
    with sessions() as s:
        dottie = s.get_one(Dottie, run.dottie_id)
        batch = list(s.scalars(select(Message).where(Message.run_id == run.run_id).order_by(Message.id)))
        text, trigger, _ = runs.describe(s, batch)
        earlier = s.scalars(
            select(Message)
            .where(Message.conversation_id == run.conversation_id, Message.id < batch[0].id)
            .order_by(Message.id)
            .limit(200)
        )
        # the conversation so far, for an agent whose own memory of it is gone (a new sandbox)
        history = [
            {"role": "assistant" if m.sender_id == dottie.id else "user", "content": m.body}
            for m in earlier
            if m.sender_kind != "system"
        ]
        shell = "shell" in dottie.tools
        return {
            "dottie": {"id": dottie.id, "slug": dottie.slug, "name": dottie.name},
            "thread_id": run.conversation_id,
            "system_prompt": system_prompt(dottie, trigger, shell, settings.user_timezone, in_sandbox=True),
            "input": text,
            "history": history,
            "shell": shell,
            # the files come with the context: one call instead of four (the runtime caches them briefly)
            "wiki": [{"path": p, "content": c} for p, c in WikiFiles(sessions, dottie.id).load().items()],
            "skills": [{"path": p, "content": c} for p, c in SkillFiles(sessions, dottie.id).load().items()],
            "model": dottie.model or settings.llm_model,
            "use_responses_api": settings.llm_use_responses_api,
            "tools": [{"name": t.name, "description": t.description, "schema": _schema(t)} for t in tools.values()],
        }


# --- tools -----------------------------------------------------------------------------------------------------------


@router.post("/tools/{name}")
async def call_tool(name: str, arguments: dict[str, Any], request: Request, run: RunDep) -> dict[str, str]:
    tools = await run_tools(request, run)
    tool = tools.get(name)
    if tool is None:
        raise ApiError("not_found", f"No tool {name!r}.", 404)
    try:
        result = await tool.ainvoke(arguments)
    except Exception as e:
        return {"result": f"{name} failed: {e}"}
    return {"result": result if isinstance(result, str) else json.dumps(result, default=str)}


# --- wiki and skills -------------------------------------------------------------------------------------------------


class Content(BaseModel):
    content: str


@router.get("/wiki")
def read_wiki(request: Request, run: RunDep) -> list[dict[str, str]]:
    files = WikiFiles(request.app.state.session_factory, run.dottie_id)
    return [{"path": p, "content": c} for p, c in files.load().items()]


@router.put("/wiki/{path:path}", status_code=204)
def write_wiki(path: str, data: Content, request: Request, run: RunDep) -> None:
    WikiFiles(request.app.state.session_factory, run.dottie_id).store("/" + path, data.content)
    record(request.app.state.session_factory, run.dottie_id, run.run_id, "wiki", f"Updated {path}", path=path)


@router.delete("/wiki/{path:path}", status_code=204)
def delete_wiki(path: str, request: Request, run: RunDep) -> None:
    WikiFiles(request.app.state.session_factory, run.dottie_id).remove("/" + path)
    record(request.app.state.session_factory, run.dottie_id, run.run_id, "wiki", f"Deleted {path}", path=path)


@router.get("/skills")
def read_skills(request: Request, run: RunDep) -> list[dict[str, str]]:
    files = SkillFiles(request.app.state.session_factory, run.dottie_id)
    return [{"path": p, "content": c} for p, c in files.load().items()]


# --- the feed and the end ------------------------------------------------------------


class FeedItem(BaseModel):
    kind: str
    text: str = ""
    data: dict[str, Any] = {}


@router.post("/events", status_code=204)
def events(items: list[FeedItem], request: Request, run: RunDep) -> None:
    for item in items[:100]:
        if item.kind in {"tool", "tool_result", "error", "note"}:
            record(request.app.state.session_factory, run.dottie_id, run.run_id, item.kind, item.text, **item.data)


class Finish(BaseModel):
    status: str  # done | failed
    reply: str = ""


@router.post("/finish", status_code=204)
def finish(data: Finish, request: Request, run: RunDep) -> None:
    request.app.state.run_tools.pop(run.run_id, None)
    if data.status == "failed":
        record(request.app.state.session_factory, run.dottie_id, run.run_id, "error", data.reply)
    runs.complete_run(
        request.app.state.session_factory, run.run_id, "failed" if data.status == "failed" else "done", data.reply
    )


# --- the model, through the app --------------------------------------------------


async def _authorization(request: Request) -> str:
    """The credentials for the real model endpoint: its key, or a token for the app's managed identity."""
    settings = request.app.state.settings
    key = settings.llm_api_key.get_secret_value()
    if key:
        return f"Bearer {key}"
    if "azure.com" in settings.llm_base_url:
        if not hasattr(request.app.state, "llm_token"):
            from azure.identity import DefaultAzureCredential, get_bearer_token_provider

            request.app.state.llm_token = get_bearer_token_provider(DefaultAzureCredential(), AZURE_COGNITIVE_SCOPE)
        return f"Bearer {await asyncio.to_thread(request.app.state.llm_token)}"
    return "Bearer unused"


@router.api_route("/llm/{path:path}", methods=["GET", "POST"])
async def model(path: str, request: Request, run: RunDep) -> StreamingResponse:
    """Forward a model request with the real credentials, and the dottie's own model name whatever the caller asks."""
    settings = request.app.state.settings
    body = await request.body()
    try:
        payload = json.loads(body)
        with request.app.state.session_factory() as s:
            payload["model"] = s.get_one(Dottie, run.dottie_id).model or settings.llm_model
        body = json.dumps(payload).encode()
    except ValueError:
        pass  # not JSON: forwarded as it is
    client: httpx.AsyncClient = request.app.state.llm_client
    upstream = await client.send(
        client.build_request(
            request.method,
            f"{settings.llm_base_url.rstrip('/')}/{path}",
            content=body,
            headers={
                "authorization": await _authorization(request),
                "content-type": request.headers.get("content-type", "application/json"),
                "accept": request.headers.get("accept", "*/*"),
            },
        ),
        stream=True,
    )
    return StreamingResponse(
        upstream.aiter_bytes(),
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type"),
        background=BackgroundTask(upstream.aclose),
    )
