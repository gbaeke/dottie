"""Trying an MCP server before saving it: connect, and say which tools it offers."""

import asyncio

from fastapi import APIRouter, Request
from pydantic import BaseModel

from ..auth import UserDep
from ..engine.mcp import load_mcp_tools
from .dotties import McpServer

router = APIRouter(prefix="/mcp-servers", tags=["mcp"])


class ToolInfo(BaseModel):
    name: str
    description: str


class McpTest(BaseModel):
    ok: bool
    tools: list[ToolInfo]
    problems: list[str]


@router.post("/test")
async def test_server(server: McpServer, request: Request, user: UserDep) -> McpTest:
    """Connect to the server the way a dottie would (headers, query and secrets filled in) and list its tools."""
    settings = request.app.state.settings
    try:
        tools, problems = await asyncio.wait_for(
            load_mcp_tools(
                [server.model_dump(mode="json")],
                owner_id=user.id,
                store=request.app.state.secret_store,
                public_only=settings.auth_enabled,
            ),
            timeout=30,
        )
    except TimeoutError:
        return McpTest(ok=False, tools=[], problems=["The server did not answer within 30 seconds."])
    info = [ToolInfo(name=t.name, description=(t.description or "")[:300]) for t in tools]
    return McpTest(ok=bool(info) and not problems, tools=info, problems=problems)
