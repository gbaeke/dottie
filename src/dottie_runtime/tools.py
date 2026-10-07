"""The dottie's tools as the agent sees them: names and schemas from the app, which also runs them."""

from typing import Any

from langchain_core.tools import StructuredTool

from .api import Api


def remote_tools(api: Api, specs: list[dict[str, Any]]) -> list[StructuredTool]:
    """A tool per spec. Calling it asks the app to run the real tool (the app holds the credentials)."""

    def make(spec: dict[str, Any]) -> StructuredTool:
        name = spec["name"]

        async def call(**arguments: Any) -> str:
            answer = await api.asy.post(f"/tools/{name}", json=arguments, timeout=300)
            if answer.is_error:
                return f"{name} failed: HTTP {answer.status_code}"
            return answer.json()["result"]

        return StructuredTool(
            name=name, description=spec["description"] or name, args_schema=spec["schema"], coroutine=call
        )

    return [make(spec) for spec in specs]
