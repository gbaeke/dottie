"""External MCP servers a dottie was connected to: their tools become the dottie's tools."""

import asyncio
import logging
from typing import Any

from langchain_mcp_adapters.client import MultiServerMCPClient

from .tools import is_public_url

log = logging.getLogger(__name__)


async def load_mcp_tools(servers: list[dict[str, Any]], *, public_only: bool = False) -> list[Any]:
    """Tools of every reachable server. One that is down costs the dottie those tools, not the whole waking.

    `public_only` (on when there are several users): the app makes these calls, so a server on a private address,
    such as the cloud's metadata service or this app's own database, is refused."""
    tools: list[Any] = []
    for server in servers:
        name, url = server.get("name"), server.get("url")
        if not name or not url:
            continue
        if public_only and not await asyncio.to_thread(is_public_url, url):
            log.warning("MCP server %s (%s) is not a public address: skipped", name, url)
            continue
        try:
            client = MultiServerMCPClient({name: {"url": url, "transport": "streamable_http"}})
            tools.extend(await client.get_tools())
        except Exception as e:
            log.warning("MCP server %s (%s) is not reachable: %s", name, url, e)
    return tools
