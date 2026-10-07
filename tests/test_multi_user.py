"""Sign-in, and above all: one user never sees or touches another user's things."""

import json
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from dottie.api.app import create_app
from dottie.auth import User
from dottie.engine.tools import RunContext, build_tools
from dottie.models import Dottie, Run, Skill

USERS = {"ann": User(id="user_ann", email="ann@example.com"), "bob": User(id="user_bob", email="bob@example.com")}


class FakeWorkOS:
    """Codes are names ("ann"); a session is "s_<name>"; "expired_<name>" refreshes into the real one."""

    def authorization_url(self, redirect_uri, state):
        return f"https://authkit.test/authorize?redirect_uri={redirect_uri}&state={state}"

    async def sign_in(self, code):
        return USERS[code], f"s_{code}"

    async def check(self, sealed):
        if sealed.startswith("expired_"):
            return USERS[sealed.removeprefix("expired_")], "s_" + sealed.removeprefix("expired_")
        return USERS.get(sealed.removeprefix("s_")), None

    def logout_url(self, sealed, return_to):
        return f"https://authkit.test/logout?return_to={return_to}"


@pytest.fixture
def app(settings):
    on = settings.model_copy(update={"workos_client_id": "client_test", "session_secret": "secret"})
    app = create_app(on, workos=FakeWorkOS())
    with TestClient(app):  # runs the startup once; each user below has a client with their own cookies
        yield app


def sign_in(app, who: str) -> TestClient:
    client = TestClient(app, follow_redirects=False)
    login = client.get("/auth/login")
    state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]
    assert client.get(f"/auth/callback?code={who}&state={state}").status_code == 303
    return client


def make(client, name="Ada", **fields) -> dict:
    res = client.post("/api/dotties", json={"name": name, **fields})
    assert res.status_code == 201, res.text
    return res.json()


def test_sign_in_is_off_without_a_client_id(client):
    assert client.get("/api/me").json() == {"user": None}  # one local user, no login


def test_signed_out_api_is_401_pages_redirect_and_the_sandbox_api_is_not_behind_the_login(app):
    anon = TestClient(app, follow_redirects=False)
    assert anon.get("/api/dotties").status_code == 401
    assert anon.get("/some/page").headers["location"] == "/auth/login?next=/some/page"
    assert anon.get("/api/health").status_code == 200
    # the sandboxes answer to run tokens, not to people: a 401 from that check, never a redirect to the sign-in
    res = anon.get("/internal/context")
    assert res.status_code == 401 and res.json()["error"]["code"] == "unauthorized"


def test_sign_in_shows_who_you_are_and_sign_out_ends_it(app):
    ann = sign_in(app, "ann")
    assert ann.get("/api/me").json() == {"user": {"id": "user_ann", "email": "ann@example.com"}}
    assert ann.get("/auth/logout").headers["location"].startswith("https://authkit.test/logout")


def test_an_expired_session_is_refreshed(app):
    client = TestClient(app, follow_redirects=False, cookies={"wos_session": "expired_ann"})
    assert client.get("/api/me").status_code == 200
    assert "s_ann" in [c.value for c in client.cookies.jar if c.name == "wos_session"]  # the new session is stored


def test_only_allowed_users_get_in(settings):
    on = settings.model_copy(
        update={"workos_client_id": "c", "session_secret": "s", "allowed_users": "ann@example.com"}
    )
    with TestClient(create_app(on, workos=FakeWorkOS())) as c:
        bob = TestClient(c.app, follow_redirects=False)
        state = parse_qs(urlparse(bob.get("/auth/login").headers["location"]).query)["state"][0]
        assert bob.get(f"/auth/callback?code=bob&state={state}").status_code == 403


def test_users_only_see_their_own_dotties_and_cannot_reach_each_others(app):
    ann, bob = sign_in(app, "ann"), sign_in(app, "bob")
    adas = make(ann, "Ada")
    assert [d["name"] for d in ann.get("/api/dotties").json()] == ["Ada"]
    assert bob.get("/api/dotties").json() == []

    conversation = ann.post(f"/api/dotties/{adas['id']}/conversations", json={}).json()["id"]
    ann.post(f"/api/conversations/{conversation}/messages", json={"body": "secret plan"})
    schedule = ann.post(
        f"/api/dotties/{adas['id']}/schedules", json={"title": "t", "prompt": "p", "cron": "0 8 * * *"}
    ).json()
    d = adas["id"]
    # every way to reach it by id answers "not found" to Bob: he cannot even tell it exists
    attempts = [
        bob.get(f"/api/dotties/{d}"),
        bob.patch(f"/api/dotties/{d}", json={"name": "Mine now"}),
        bob.delete(f"/api/dotties/{d}"),
        bob.get(f"/api/dotties/{d}/conversations"),
        bob.post(f"/api/dotties/{d}/conversations", json={}),
        bob.get(f"/api/conversations/{conversation}/messages"),
        bob.post(f"/api/conversations/{conversation}/messages", json={"body": "hi"}),
        bob.post(f"/api/conversations/{conversation}/read"),
        bob.delete(f"/api/conversations/{conversation}"),
        bob.get(f"/api/dotties/{d}/wiki"),
        bob.get(f"/api/dotties/{d}/wiki/user.md"),
        bob.put(f"/api/dotties/{d}/wiki/user.md", json={"content": "overwritten"}),
        bob.delete(f"/api/dotties/{d}/wiki/user.md"),
        bob.get(f"/api/dotties/{d}/schedules"),
        bob.post(f"/api/dotties/{d}/schedules", json={"title": "t", "prompt": "p", "cron": "* * * * *"}),
        bob.patch(f"/api/schedules/{schedule['id']}", json={"enabled": False}),
        bob.post(f"/api/schedules/{schedule['id']}/run"),
        bob.delete(f"/api/schedules/{schedule['id']}"),
        bob.get(f"/api/dotties/{d}/events"),
        bob.get(f"/api/dotties/{d}/runs"),
    ]
    assert [r.status_code for r in attempts] == [404] * len(attempts)
    # and nothing of Ann's shows in his lists
    assert bob.get("/api/schedules").json() == []
    assert bob.get("/api/inbox").json() == []
    assert bob.get("/api/bus").json() == []
    assert bob.get("/api/events").json() == []
    # Ann's things are untouched
    assert ann.get(f"/api/dotties/{d}").json()["name"] == "Ada"
    assert "secret plan" in ann.get(f"/api/conversations/{conversation}/messages").json()[0]["body"]
    assert ann.get(f"/api/dotties/{d}/wiki/user.md").status_code == 200


def test_skills_are_private_except_the_built_in_ones(app):
    ann, bob = sign_in(app, "ann"), sign_in(app, "bob")
    mine = ann.post("/api/skills", json={"name": "my-skill", "description": "d", "body": "b"}).json()
    builtin = next(s for s in bob.get("/api/skills").json() if s["builtin"])
    assert "my-skill" not in [s["name"] for s in bob.get("/api/skills").json()]
    assert ann.get("/api/skills").json()[-1]["name"] == "my-skill" or "my-skill" in [
        s["name"] for s in ann.get("/api/skills").json()
    ]
    assert bob.patch(f"/api/skills/{mine['id']}", json={"body": "x"}).status_code == 404
    assert bob.delete(f"/api/skills/{mine['id']}").status_code == 404
    # Bob cannot hand Ann's skill to his dottie, but may use the built-in ones
    assert bob.post("/api/dotties", json={"name": "B", "skill_ids": [mine["id"]]}).status_code == 422
    assert bob.post("/api/dotties", json={"name": "B", "skill_ids": [builtin["id"]]}).status_code == 201
    # the same name can be used by two people
    assert bob.post("/api/skills", json={"name": "my-skill", "description": "d", "body": "b"}).status_code == 201


def test_a_dottie_only_knows_and_writes_to_the_dotties_of_its_own_user(app):
    ann, bob = sign_in(app, "ann"), sign_in(app, "bob")
    adas, bobs, annes = make(ann, "Ada"), make(bob, "Bo"), make(ann, "Anne")
    sessions = app.state.session_factory
    with sessions() as db:
        run = Run(dottie_id=adas["id"], trigger="user")
        db.add(run)
        db.commit()
        run_id = run.id
    tools = {f.__name__: f for f in build_tools(RunContext(sessions, adas["id"], run_id, 0, 5), ["messaging"])}
    listing = tools["list_dotties"]()
    assert "anne" in listing and "bo" not in listing.split()
    assert "No dottie called" in tools["send_message"]("bo", "hello Bo")  # someone else's, and so unreachable
    assert "Sent to Anne" in tools["send_message"]("anne", "hello Anne")
    assert bob.get(f"/api/dotties/{bobs['id']}/conversations").json() == []  # nothing arrived at Bo's
    assert annes["slug"] == "anne"


def test_a_user_can_have_only_so_many_dotties(settings):
    on = settings.model_copy(update={"workos_client_id": "c", "session_secret": "s", "max_dotties_per_user": 2})
    with TestClient(create_app(on, workos=FakeWorkOS())) as c:
        ann, bob = sign_in(c.app, "ann"), sign_in(c.app, "bob")
        make(ann, "One")
        make(ann, "Two")
        third = ann.post("/api/dotties", json={"name": "Three"})
        assert (third.status_code, third.json()["error"]["code"]) == (409, "limit_reached")
        assert bob.post("/api/dotties", json={"name": "Bob's"}).status_code == 201  # the limit is per user


def test_the_first_person_to_sign_in_takes_over_what_existed_before_sign_in(app):
    with app.state.session_factory() as s:
        s.add(Dottie(owner_id="local", name="Old", slug="old"))
        s.add(Skill(owner_id="local", name="old-skill", description="d", body="b"))
        s.commit()
    ann = sign_in(app, "ann")
    assert [d["name"] for d in ann.get("/api/dotties").json()] == ["Old"]
    assert "old-skill" in [s["name"] for s in ann.get("/api/skills").json()]
    bob = sign_in(app, "bob")  # later users take nothing
    assert bob.get("/api/dotties").json() == []


def test_mcp_needs_a_personal_token_and_shows_only_that_users_dotties(app):
    ann, bob = sign_in(app, "ann"), sign_in(app, "bob")
    make(ann, "Ada")
    make(bob, "Bo")
    token = ann.post("/api/tokens", json={"name": "claude code"}).json()["token"]
    assert token.startswith("dtk_")
    assert ann.get("/api/tokens").json()[0]["name"] == "claude code"
    assert "token" not in ann.get("/api/tokens").json()[0]  # shown only when it was made

    def call(headers):
        body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "list_dotties", "arguments": {}}}
        mcp = TestClient(app, headers={"Accept": "application/json, text/event-stream", **headers})
        return mcp.post("/mcp/", content=json.dumps(body), headers={"Content-Type": "application/json"})

    assert call({}).status_code == 401
    assert call({"Authorization": "Bearer dtk_wrong"}).status_code == 401
    res = call({"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    text = next(line for line in res.text.splitlines() if line.startswith("data:"))
    assert "ada: Ada" in text and "Bo" not in text
    assert bob.delete(f"/api/tokens/{ann.get('/api/tokens').json()[0]['id']}").status_code == 404


def test_mcp_servers_must_be_on_public_addresses_when_there_are_several_users(app):
    ann = sign_in(app, "ann")
    for private in ("http://127.0.0.1:9/mcp", "http://169.254.169.254/latest", "http://10.0.0.5/mcp"):
        res = ann.post("/api/dotties", json={"name": "X", "mcp_servers": [{"name": "x", "url": private}]})
        assert res.status_code == 422, private
    ok = ann.post("/api/dotties", json={"name": "Y", "mcp_servers": [{"name": "y", "url": "https://1.1.1.1/mcp"}]})
    assert ok.status_code == 201
    bad = ann.patch(
        f"/api/dotties/{ok.json()['id']}", json={"mcp_servers": [{"name": "z", "url": "http://localhost/mcp"}]}
    )
    assert bad.status_code == 422


def test_a_workos_refusal_at_sign_in_is_explained_not_a_server_error(settings):
    class Refusing(FakeWorkOS):
        async def sign_in(self, code):
            raise RuntimeError("invalid_client")

    on = settings.model_copy(update={"workos_client_id": "c", "session_secret": "s"})
    with TestClient(create_app(on, workos=Refusing())) as c:
        client = TestClient(c.app, follow_redirects=False)
        state = parse_qs(urlparse(client.get("/auth/login").headers["location"]).query)["state"][0]
        res = client.get(f"/auth/callback?code=x&state={state}")
        assert res.status_code == 502
        assert (
            res.json()["error"]["code"] == "signin_failed"
            and "same WorkOS application" in res.json()["error"]["message"]
        )
