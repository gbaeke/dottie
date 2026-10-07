"""Secrets are write-only, encrypted, per user; MCP servers use them through {{secret:NAME}} references."""

import asyncio

import pytest
from sqlalchemy import select

from dottie.engine import mcp
from dottie.engine.secrets import SecretCipher, SecretStore, repair_inline_credentials
from dottie.models import Dottie, Secret

from .test_dotties import make
from .test_multi_user import app, sign_in  # noqa: F401  (the fixture and the helper for two signed-in users)

KEY = "tvly-dev-0123456789abcdefghij"


def put(client, name="tavily", value=KEY):
    return client.put(f"/api/secrets/{name}", json={"value": value})


def server(**fields):
    return {"name": "tavily", "url": "https://mcp.tavily.com/mcp/", **fields}


def test_the_cipher_round_trips_and_hides_the_value():
    cipher = SecretCipher("a key")
    stored = cipher.encrypt(KEY)
    assert stored.startswith("v1:") and KEY not in stored
    assert cipher.decrypt(stored) == KEY
    with pytest.raises(Exception):  # noqa: B017  (a different key cannot read it)
        SecretCipher("another key").decrypt(stored)


def test_a_secret_is_written_listed_by_hint_and_never_read_back(client):
    saved = put(client)
    assert saved.status_code == 200
    assert saved.json() == {"name": "tavily", "hint": "ghij", "updated_at": saved.json()["updated_at"], "used_by": []}
    listing = client.get("/api/secrets").json()
    assert [(s["name"], s["hint"]) for s in listing] == [("tavily", "ghij")]
    assert KEY not in client.get("/api/secrets").text and KEY not in saved.text  # no way to get the value back
    # in the database it is ciphertext
    with client.app.state.session_factory() as s:
        stored = s.scalar(select(Secret.ciphertext))
    assert KEY not in stored and stored.startswith("v1:")
    # replacing it changes the value, not the name
    assert put(client, value="another-long-key-value-wxyz").json()["hint"] == "wxyz"
    assert len(client.get("/api/secrets").json()) == 1


def test_a_short_value_has_no_hint_and_bad_names_are_refused(client):
    assert put(client, "short", "abc").json()["hint"] == ""
    assert put(client, "1bad", "x").status_code == 422
    assert client.put("/api/secrets/ok", json={"value": ""}).status_code == 422


def test_secrets_are_off_without_a_key(settings):
    from fastapi.testclient import TestClient

    from dottie.api.app import create_app

    with TestClient(create_app(settings.model_copy(update={"secrets_key": type(settings.secrets_key)("")}))) as c:
        res = put(c)
        assert (res.status_code, res.json()["error"]["code"]) == (503, "not_configured")


def test_secrets_belong_to_a_user(app):  # noqa: F811
    ann, bob = sign_in(app, "ann"), sign_in(app, "bob")
    put(ann, "tavily", "ann-key-0123456789abcdef")
    assert bob.get("/api/secrets").json() == []
    put(bob, "tavily", "bob-key-0123456789abcdef")  # the same name, another user's
    assert [s["hint"] for s in ann.get("/api/secrets").json()] == ["cdef"]
    assert bob.delete("/api/secrets/nope").status_code == 404
    store: SecretStore = app.state.secret_store
    assert store.get_many("user_ann", {"tavily"}) == {"tavily": "ann-key-0123456789abcdef"}
    assert store.get_many("user_bob", {"tavily"}) == {"tavily": "bob-key-0123456789abcdef"}


def test_a_credential_cannot_be_saved_as_plain_text(client):
    def create(**fields):
        return client.post("/api/dotties", json={"name": "Ada", "mcp_servers": [server(**fields)]})

    put(client)
    refused = [
        create(url=f"https://mcp.tavily.com/mcp/?tavilyApiKey={KEY}"),  # a key in the URL's query
        create(headers={"Authorization": f"Bearer {KEY}"}),  # a key in a header
        create(query={"tavilyApiKey": KEY}),  # a key in a query parameter
        create(url="https://me:hunter2@mcp.tavily.com/mcp/"),  # a password in the URL
        create(headers={"Host": "evil.example"}),  # a header the connection must control
        create(headers={f"X-{n}": "v" for n in range(11)}),  # too many
    ]
    assert [r.status_code for r in refused] == [422] * len(refused)
    assert "secret" in refused[0].text and KEY not in refused[0].text  # it says what to do, without echoing the key
    assert create(headers={"Authorization": "Bearer {{secret:tavily}}"}).status_code == 201
    assert create(query={"tavilyApiKey": "{{secret:tavily}}"}).status_code == 201
    assert create(headers={"Accept-Language": "en"}).status_code == 201  # not a credential: plain text is fine


def test_a_reference_to_a_missing_secret_is_caught_when_saving(client):
    res = client.post(
        "/api/dotties",
        json={"name": "Ada", "mcp_servers": [server(headers={"Authorization": "Bearer {{secret:nope}}"})]},
    )
    assert res.status_code == 422 and "nope" in res.text


def test_a_secret_in_use_cannot_be_deleted(client):
    put(client)
    ada = client.post(
        "/api/dotties",
        json={"name": "Ada", "mcp_servers": [server(headers={"Authorization": "Bearer {{secret:tavily}}"})]},
    ).json()
    assert client.get("/api/secrets").json()[0]["used_by"] == ["Ada"]
    blocked = client.delete("/api/secrets/tavily")
    assert (blocked.status_code, blocked.json()["error"]["code"]) == (409, "in_use")
    assert client.patch(f"/api/dotties/{ada['id']}", json={"mcp_servers": []}).status_code == 200
    assert client.delete("/api/secrets/tavily").status_code == 204


def test_the_connection_has_the_secrets_filled_in_and_logs_never_show_the_query():
    config = {
        "name": "tavily",
        "url": "https://mcp.tavily.com/mcp/?v=2",
        "headers": {"Authorization": "Bearer {{secret:tavily}}", "X-Plain": "yes"},
        "query": {"tavilyApiKey": "{{secret:tavily}}"},
    }
    assert mcp.referenced_secrets(config) == {"tavily"}
    made = mcp.connection(config, {"tavily": KEY})
    assert made["headers"] == {"Authorization": f"Bearer {KEY}", "X-Plain": "yes"}
    assert made["transport"] == "streamable_http"
    assert made["url"].startswith("https://mcp.tavily.com/mcp/?") and f"tavilyApiKey={KEY}" in made["url"]
    assert "v=2" in made["url"]  # the URL's own query stays
    assert mcp.describe({"url": f"https://mcp.tavily.com/mcp/?tavilyApiKey={KEY}"}) == "mcp.tavily.com/mcp/"


def test_loading_tools_uses_the_owners_secrets_and_reports_what_is_missing(client, monkeypatch):
    seen = {}

    class Fake:
        def __init__(self, servers):
            seen.update(servers)

        async def get_tools(self):
            return ["a-tool"]

    monkeypatch.setattr(mcp, "MultiServerMCPClient", Fake)
    store: SecretStore = client.app.state.secret_store
    store.put("user_ann", "tavily", KEY)
    config = {
        "name": "tavily",
        "url": "https://mcp.tavily.com/mcp/",
        "headers": {"Authorization": "Bearer {{secret:tavily}}"},
    }

    tools, problems = asyncio.run(mcp.load_mcp_tools([config], owner_id="user_ann", store=store))
    assert (tools, problems) == (["a-tool"], [])
    assert seen["tavily"]["headers"] == {"Authorization": f"Bearer {KEY}"}

    tools, problems = asyncio.run(mcp.load_mcp_tools([config], owner_id="user_bob", store=store))  # no such secret
    assert tools == [] and problems == ["MCP server 'tavily' needs the secret(s) tavily, which are not set."]


def test_the_test_endpoint_lists_a_servers_tools(client, monkeypatch):
    class Tool:
        name, description = "search", "Search the web"

    async def fake_load(servers, **_):
        assert servers[0]["headers"] == {
            "Authorization": "Bearer {{secret:tavily}}"
        }  # not filled in: the loader does it
        return [Tool()], []

    from dottie.api import mcp as mcp_api

    monkeypatch.setattr(mcp_api, "load_mcp_tools", fake_load)
    put(client)
    res = client.post("/api/mcp-servers/test", json=server(headers={"Authorization": "Bearer {{secret:tavily}}"}))
    assert res.json() == {"ok": True, "tools": [{"name": "search", "description": "Search the web"}], "problems": []}


def test_a_key_stored_in_a_url_before_secrets_existed_is_moved_out(client):
    store: SecretStore = client.app.state.secret_store
    sessions = client.app.state.session_factory
    ada = make(client)
    with sessions() as s:
        d = s.get_one(Dottie, ada["id"])
        d.mcp_servers = [{"name": "tavily", "url": f"https://mcp.tavily.com/mcp/?tavilyApiKey={KEY}&v=2"}]
        s.commit()

    assert repair_inline_credentials(sessions, store, mcp.looks_secret) == 1
    with sessions() as s:
        saved = s.get_one(Dottie, ada["id"]).mcp_servers[0]
    assert KEY not in str(saved)
    assert saved["url"] == "https://mcp.tavily.com/mcp/?v=2"
    assert saved["query"] == {"tavilyApiKey": "{{secret:tavily-tavilyApiKey}}"}
    assert store.get_many("local", {"tavily-tavilyApiKey"}) == {"tavily-tavilyApiKey": KEY}
    assert repair_inline_credentials(sessions, store, mcp.looks_secret) == 0  # nothing left to move
