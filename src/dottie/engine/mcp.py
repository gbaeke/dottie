"""External MCP servers a dottie was connected to: their tools become the dottie's tools.

A server is a URL plus `headers` and `query` parameters. A value may contain `{{secret:NAME}}`, which is replaced by the
owner's stored secret when the app connects, so no credential is kept in a URL or a config. Anything that looks like a
credential must be written that way: the API refuses a literal one.
"""

import asyncio
import logging
import re
from typing import Any
from urllib.parse import urlsplit

import httpx
from langchain_mcp_adapters.client import MultiServerMCPClient

from .secrets import SecretsNotConfigured, SecretStore, fill, refs
from .tools import is_public_url

log = logging.getLogger(__name__)

SECRETISH = re.compile(r"key|token|secret|passw|auth|credential|bearer|signature|cookie|sig$", re.IGNORECASE)
HEADER_NAME = re.compile(r"^[A-Za-z0-9-]{1,64}$")
QUERY_NAME = re.compile(r"^[A-Za-z0-9_.\-]{1,64}$")
FORBIDDEN_HEADERS = {"host", "content-length", "connection", "transfer-encoding", "upgrade", "te", "trailer"}
MAX_ENTRIES = 10
MAX_VALUE = 2000


def looks_secret(name: str) -> bool:
    return bool(SECRETISH.search(name))


def config_problems(server: dict[str, Any]) -> list[str]:
    """Why this server config must not be saved as it is (empty: fine). The point is credentials: a header or query
    value that looks like one has to come from a secret."""
    problems: list[str] = []
    parts = urlsplit(str(server.get("url", "")))
    if parts.username or parts.password:
        problems.append("The URL carries a user name or password: use a header with a secret instead.")
    from urllib.parse import parse_qsl

    for param, value in parse_qsl(parts.query, keep_blank_values=True):
        if looks_secret(param) and value and not refs(value):
            problems.append(
                f"The URL has a credential in its query ({param}=...). Remove it, add {param} under query "
                "and give it as {{secret:NAME}}."
            )
    for kind, entries, name_ok in (
        ("header", server.get("headers") or {}, HEADER_NAME),
        ("query parameter", server.get("query") or {}, QUERY_NAME),
    ):
        if len(entries) > MAX_ENTRIES:
            problems.append(f"At most {MAX_ENTRIES} {kind}s.")
        for name, value in entries.items():
            if not name_ok.match(name) or (kind == "header" and name.lower() in FORBIDDEN_HEADERS):
                problems.append(f"{name!r} is not a usable {kind} name.")
            elif len(value) > MAX_VALUE:
                problems.append(f"The value of {kind} {name!r} is too long.")
            elif looks_secret(name) and value and not refs(value):
                problems.append(
                    f"{kind.capitalize()} {name!r} looks like a credential: give it as {{{{secret:NAME}}}}."
                )
    return problems


def referenced_secrets(server: dict[str, Any]) -> set[str]:
    names: set[str] = set(refs(str(server.get("url", ""))))
    for entries in (server.get("headers") or {}, server.get("query") or {}):
        for value in entries.values():
            names |= refs(value)
    return names


def describe(server: dict[str, Any]) -> str:
    """Where a server is, for logs: the host and path, never the query (it may carry a credential)."""
    parts = urlsplit(str(server.get("url", "")))
    return f"{parts.hostname or '?'}{parts.path}"


def connection(server: dict[str, Any], values: dict[str, str]) -> dict[str, Any]:
    """The client settings for a server, with its secrets filled in."""
    url = httpx.URL(fill(str(server["url"]), values))
    query = {k: fill(v, values) for k, v in (server.get("query") or {}).items()}
    if query:
        url = url.copy_merge_params(query)
    headers = {k: fill(v, values) for k, v in (server.get("headers") or {}).items()}
    config: dict[str, Any] = {"url": str(url), "transport": "streamable_http"}
    if headers:
        config["headers"] = headers
    return config


async def load_mcp_tools(
    servers: list[dict[str, Any]],
    *,
    owner_id: str,
    store: SecretStore | None,
    public_only: bool = False,
) -> tuple[list[Any], list[str]]:
    """The tools of every reachable server, and what went wrong with the others (for the activity feed): one server
    that is down or lacks a secret costs the dottie those tools, not the whole waking.

    `public_only` (on when there are several users): the app makes these calls, so a server on a private address,
    such as the cloud's metadata service or this app's own database, is refused."""
    tools: list[Any] = []
    problems: list[str] = []
    for server in servers:
        name = server.get("name")
        if not name or not server.get("url"):
            continue
        if public_only and not await asyncio.to_thread(is_public_url, server["url"]):
            problems.append(f"MCP server {name!r} is not on a public address.")
            continue
        try:
            names = referenced_secrets(server)
            values = await asyncio.to_thread(store.get_many, owner_id, names) if store and names else {}
            if missing := names - values.keys():
                problems.append(
                    f"MCP server {name!r} needs the secret(s) {', '.join(sorted(missing))}, which are not set."
                )
                continue
            client = MultiServerMCPClient({name: connection(server, values)})  # pyright: ignore[reportArgumentType]
            tools.extend(await client.get_tools())
        except SecretsNotConfigured:
            problems.append(f"MCP server {name!r} needs secrets, and this installation has no SECRETS_KEY.")
        except Exception as e:
            log.warning("MCP server %s (%s) is not reachable: %s", name, describe(server), type(e).__name__)
            problems.append(f"MCP server {name!r} is not reachable ({type(e).__name__}).")
    return tools, problems
