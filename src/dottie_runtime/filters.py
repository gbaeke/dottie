"""Hides tools a dottie has not been given."""

from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.types import Command


class ToolFilter(AgentMiddleware):
    """Deep Agents always adds `execute`, shell or not: this hides the tools a dottie has not been given and refuses
    them if a model asks for one anyway."""

    def __init__(self, blocked: set[str]):
        self.blocked = blocked

    def _allowed(self, request: ModelRequest) -> ModelRequest:
        return request.override(tools=[t for t in request.tools if getattr(t, "name", None) not in self.blocked])

    def _refusal(self, request: ToolCallRequest) -> ToolMessage | None:
        if request.tool_call["name"] in self.blocked:
            return ToolMessage(
                content=f"{request.tool_call['name']} is not available to you.",
                tool_call_id=request.tool_call["id"],
                status="error",
            )
        return None

    def wrap_model_call(self, request: ModelRequest, handler: Callable[[ModelRequest], ModelResponse]):
        return handler(self._allowed(request))

    async def awrap_model_call(
        self, request: ModelRequest, handler: Callable[[ModelRequest], Awaitable[ModelResponse]]
    ):
        return await handler(self._allowed(request))

    def wrap_tool_call(
        self, request: ToolCallRequest, handler: Callable[[ToolCallRequest], ToolMessage | Command[Any]]
    ):
        return self._refusal(request) or handler(request)

    async def awrap_tool_call(
        self, request: ToolCallRequest, handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]]
    ):
        return self._refusal(request) or await handler(request)
