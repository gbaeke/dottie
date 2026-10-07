"""External MCP servers a dottie was connected to: their tools become the dottie's tools."""

import logging
from typing import Any

from langchain_mcp_adapters.client import MultiServerMCPClient

log = logging.getLogger(__name__)


async def load_mcp_tools(servers: list[dict[str, Any]]) -> list[Any]:
    """Tools of every reachable server. One that is down costs the dottie those tools, not the whole waking."""
    tools: list[Any] = []
    for server in servers:
        name, url = server.get("name"), server.get("url")
        if not name or not url:
            continue
        try:
            client = MultiServerMCPClient({name: {"url": url, "transport": "streamable_http"}})
            tools.extend(await client.get_tools())
        except Exception as e:
            log.warning("MCP server %s (%s) is not reachable: %s", name, url, e)
    return tools
