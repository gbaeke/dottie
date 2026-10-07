"""The agent running in the sandbox: the app wakes the sandbox and waits; the runtime does the work and calls back.

The sandbox here is a fake whose "start the runtime" command runs the real runtime in a thread, against the real app
(over in-process HTTP), with a scripted model."""

import asyncio
import re
import threading
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from deepagents.backends.protocol import ExecuteResponse, FileDownloadResponse, FileUploadResponse
from deepagents.backends.sandbox import BaseSandbox
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from pydantic import SecretStr

from dottie.api.app import create_app
from dottie.engine import sandbox_agent
from dottie.engine.sandboxes import SandboxProvider
from dottie_runtime.api import Api
from dottie_runtime.files import RemoteFiles
from dottie_runtime.main import run_safely

from .fakes import ScriptedModel
from .test_dotties import make
from .test_engine import call, chat, say, use


class RuntimeSandbox(BaseSandbox):
    """Pretends to be a machine: answers the installer's questions and starts the runtime when told to."""

    def __init__(self, app, model, workdir):
        self.app, self.model, self.workdir = app, model, workdir
        self.thread: threading.Thread | None = None
        self.commands: list[str] = []

    @property
    def id(self) -> str:
        return "runtime-sandbox"

    def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        self.commands.append(command)
        if command.startswith("cat /opt/dottie/stamp"):
            files, pins = sandbox_agent.runtime_files(), sandbox_agent.requirements()
            return ExecuteResponse(output=sandbox_agent.stamp(files, pins), exit_code=0)
        if "/inbox/" in command:  # a run ticket for the runtime: its token is in the command
            token = re.search(r'"token": "([^"]+)"', command).group(1)  # pyright: ignore[reportOptionalMemberAccess]
            self.thread = threading.Thread(target=self._runtime, args=(token,), daemon=True)
            self.thread.start()
            return ExecuteResponse(output="4242", exit_code=0)
        if command.startswith("kill -0"):
            return ExecuteResponse(output="", exit_code=0 if self.thread and self.thread.is_alive() else 1)
        return ExecuteResponse(output="", exit_code=0)

    def _runtime(self, token: str) -> None:
        headers = {"Authorization": f"Bearer {token}"}
        base = "http://app/internal"
        api = Api(
            sync=TestClient(self.app, base_url=base, headers=headers),  # pyright: ignore[reportArgumentType]
            asy=httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url=base, headers=headers),
            base_url=base,
            token=token,
        )
        asyncio.run(run_safely(api, model=self.model, workdir=self.workdir, state_db=self.workdir / "state.db"))

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        return [FileUploadResponse(path=p) for p, _ in files]

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        return [FileDownloadResponse(path=p, content=b"") for p in paths]


class Provider(SandboxProvider):
    name = "runtime"

    def __init__(self, sandbox: RuntimeSandbox):
        self.sandbox, self.slept, self.woken, self.attached = sandbox, 0, 0, 0
        self.attach_fails = False
        self.reported = "running"  # what the platform says about the sandbox

    def wake(self, dottie):
        self.woken += 1
        return self.sandbox, "runtime-1"

    def state(self, ref: str | None) -> str:
        return self.reported

    def attach(self, ref: str):
        self.attached += 1
        if self.attach_fails:
            raise RuntimeError("it is stopped")
        return self.sandbox

    def sleep(self, ref: str) -> None:
        self.slept += 1

    def destroy(self, ref: str) -> None:
        pass


@pytest.fixture
def sandboxed(settings, tmp_path):
    """An app whose dotties run their agent in a (fake) sandbox. Yields (client, provider, script of ada's model)."""
    script: list[AIMessage] = []
    holder: dict = {}
    app = create_app(
        settings.model_copy(update={"agent_mode": "sandbox", "run_timeout_seconds": 60}),
        provider=Provider(RuntimeSandbox(None, ScriptedModel(messages=iter(script)), tmp_path)),
    )
    holder["provider"] = app  # the sandbox needs the app that serves it: filled in below
    with TestClient(app) as client:
        provider = app.state.engine.runner.provider
        provider.sandbox.app = app
        yield client, provider, script


def wake(client) -> None:
    engine = client.app.state.engine
    engine.tick()
    engine.wait_idle(60)


def test_the_agent_runs_in_the_sandbox_and_the_app_only_waits(sandboxed):
    client, provider, script = sandboxed
    ada = make(client)
    script.extend(
        [
            use(call("edit_file", file_path="/wiki/user.md", old_string="Nothing yet.", new_string="Likes tea.")),
            use(call("list_dotties")),
            say("Noted, and nobody else is around."),
        ]
    )
    conversation = chat(client, ada["id"], "I like tea.")
    wake(client)

    messages = client.get(f"/api/conversations/{conversation}/messages").json()
    assert [(m["sender_kind"], m["body"]) for m in messages] == [
        ("user", "I like tea."),
        ("dottie", "Noted, and nobody else is around."),
    ]
    assert "Likes tea." in client.get(f"/api/dotties/{ada['id']}/wiki/user.md").json()["content"]
    events = client.get(f"/api/dotties/{ada['id']}/events").json()[::-1]
    kinds = [e["kind"] for e in events]
    assert kinds[0] == "wake" and kinds[-1] == "idle"  # its computer is warm: not asleep yet
    assert "wiki" in kinds and kinds.count("tool") == 2
    assert any("There are no other dotties." in e["text"] for e in events if e["kind"] == "tool_result")
    assert [(r["status"], r["trigger"]) for r in client.get(f"/api/dotties/{ada['id']}/runs").json()] == [
        ("done", "user")
    ]
    assert provider.slept == 0  # still warm: a follow-up would find it running
    idle = client.app.state.settings.sandbox_idle_seconds
    client.app.state.engine.reap_idle(datetime.now(UTC) + timedelta(seconds=idle - 5))
    assert provider.slept == 0  # not idle for long enough yet
    client.app.state.engine.reap_idle(datetime.now(UTC) + timedelta(seconds=idle + 5))
    assert provider.slept == 1  # idle: stopped, and only once however often the engine looks
    last = client.get(f"/api/dotties/{ada['id']}/events").json()[0]
    assert (last["kind"], last["text"]) == ("sleep", "Went to sleep.")  # said when it really happened
    client.app.state.engine.reap_idle(datetime.now(UTC) + timedelta(seconds=idle + 60))
    assert provider.slept == 1


def test_a_runtime_that_dies_fails_the_run_visibly(sandboxed):
    client, provider, _ = sandboxed
    ada = make(client)
    provider.sandbox.model = ScriptedModel(messages=iter([]))  # an exhausted script: the model raises
    conversation = chat(client, ada["id"], "Hello")
    wake(client)
    reply = client.get(f"/api/conversations/{conversation}/messages").json()[-1]
    assert reply["sender_kind"] == "system" and "could not finish" in reply["body"]
    assert client.get(f"/api/dotties/{ada['id']}/runs").json()[0]["status"] == "failed"


def test_the_callback_api_rejects_unknown_and_finished_runs(sandboxed):
    client, _, script = sandboxed
    ada = make(client)
    assert client.get("/internal/context").status_code == 401
    assert client.get("/internal/context", headers={"Authorization": "Bearer nope"}).status_code == 401
    script.append(say("Hi."))
    chat(client, ada["id"], "Hello")
    wake(client)
    from sqlalchemy import select

    from dottie.models import Run

    with client.app.state.session_factory() as s:
        token = s.scalar(select(Run.token))
    # the run is over: its token no longer works
    assert client.get("/internal/context", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_the_model_proxy_adds_the_real_credentials_and_the_dottie_s_own_model(settings):
    seen = {}

    def upstream(request: httpx.Request) -> httpx.Response:
        seen.update(url=str(request.url), auth=request.headers["authorization"], body=request.content)
        return httpx.Response(200, json={"id": "resp_1"})

    app = create_app(
        settings.model_copy(
            update={"llm_api_key": SecretStr("real-key"), "llm_base_url": "http://model/v1", "llm_model": "gpt-x"}
        )
    )
    with TestClient(app) as client:
        ada = make(client)
        from dottie.models import Run

        with app.state.session_factory() as s:
            s.add(Run(dottie_id=ada["id"], trigger="user", token="run-token"))
            s.commit()
        app.state.llm_client = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
        answer = client.post(
            "/internal/llm/responses",
            json={"model": "something-expensive", "input": "hi"},
            headers={"Authorization": "Bearer run-token"},
        )
    assert answer.json() == {"id": "resp_1"}
    assert seen["url"] == "http://model/v1/responses"
    assert seen["auth"] == "Bearer real-key"  # the run token never goes upstream
    assert b'"model": "gpt-x"' in seen["body"]  # and the caller cannot pick another model


def test_the_gateway_serves_only_the_sandbox_api(settings):
    with TestClient(create_app(settings.model_copy(update={"serve": "internal"}))) as client:
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/dotties").status_code == 404  # no UI API here
        assert client.get("/internal/context").status_code == 401  # the sandbox API, asking for a token
        assert client.post("/mcp/", json={}).status_code == 404


def test_a_dottie_is_idle_while_its_sandbox_is_warm_and_asleep_after(sandboxed):
    client, provider, script = sandboxed
    ada = make(client)
    script.append(say("Hi."))
    chat(client, ada["id"], "Hello")
    wake(client)
    assert client.get(f"/api/dotties/{ada['id']}").json()["state"] == "idle"  # no run, but its computer is warm
    idle = client.app.state.settings.sandbox_idle_seconds
    client.app.state.engine.reap_idle(datetime.now(UTC) + timedelta(seconds=idle + 5))
    assert provider.slept == 1


def test_a_follow_up_in_the_warm_window_skips_waking_and_the_install_check(sandboxed):
    client, provider, script = sandboxed
    ada = make(client)
    script.extend([say("One."), say("Two.")])
    chat(client, ada["id"], "First")
    wake(client)
    assert (provider.woken, provider.attached) == (1, 0)  # the first run wakes it and checks the runtime
    conversation = client.get(f"/api/dotties/{ada['id']}/conversations").json()[0]["id"]
    client.post(f"/api/conversations/{conversation}/messages", json={"body": "Second"})
    wake(client)
    assert (provider.woken, provider.attached) == (1, 1)  # the second attaches: no wake call
    checks = [c for c in provider.sandbox.commands if c.startswith("cat /opt/dottie/stamp")]
    assert len(checks) == 1  # and no second look at the installed runtime
    bodies = [m["body"] for m in client.get(f"/api/conversations/{conversation}/messages").json()]
    assert bodies == ["First", "One.", "Second", "Two."]


def test_a_warm_start_that_fails_falls_back_to_waking_the_sandbox(sandboxed):
    client, provider, script = sandboxed
    ada = make(client)
    script.extend([say("One."), say("Two.")])
    chat(client, ada["id"], "First")
    wake(client)
    provider.attach_fails = True  # it was stopped after all
    conversation = client.get(f"/api/dotties/{ada['id']}/conversations").json()[0]["id"]
    client.post(f"/api/conversations/{conversation}/messages", json={"body": "Second"})
    wake(client)
    assert (provider.woken, provider.attached) == (2, 1)
    assert client.get(f"/api/conversations/{conversation}/messages").json()[-1]["body"] == "Two."


def test_remote_files_come_with_the_context_and_stay_current_without_calls():
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(f"{request.method} {request.url.path}")
        return httpx.Response(204)

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://app/internal")
    wiki = RemoteFiles(client, "wiki", preload=[{"path": "/index.md", "content": "# Wiki"}])
    assert wiki.read("/index.md").file_data["content"] == "# Wiki"  # pyright: ignore[reportOptionalSubscript]
    assert seen == []  # served from what the context brought
    assert wiki.write("/new.md", "hello").error is None
    assert seen == ["PUT /internal/wiki/new.md"]  # only the write went out
    assert wiki.read("/new.md").file_data["content"] == "hello"  # pyright: ignore[reportOptionalSubscript]
    assert len(seen) == 1


def test_the_runtime_stays_alive_and_takes_runs_as_tickets(tmp_path, monkeypatch):
    import json

    from dottie_runtime import main as runtime

    handled: list[str] = []

    async def fake_run(api, **options):
        handled.append(api.token)

    monkeypatch.setattr(runtime, "run_safely", fake_run)
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    for n, token in enumerate(["first", "second"]):
        ticket = inbox / f"{n}.run"
        ticket.write_text(json.dumps({"api": "http://app/internal", "token": token}))
        import os

        os.utime(ticket, (1000 + n, 1000 + n))  # the oldest goes first
    asyncio.run(runtime.serve(inbox, workdir=tmp_path, state_db=tmp_path / "s.db", idle_exit=0.3, poll=0.05))
    assert handled == ["first", "second"]
    assert list(inbox.glob("*.run")) == []  # tickets are removed when picked up: the token is not left on disk


def test_a_sandbox_stopped_from_outside_is_not_shown_as_awake(sandboxed):
    client, provider, script = sandboxed
    ada = make(client)
    script.append(say("Hi."))
    chat(client, ada["id"], "Hello")
    wake(client)
    engine = client.app.state.engine
    assert client.get(f"/api/dotties/{ada['id']}").json()["state"] == "idle"
    assert engine.reconcile() == []  # the platform agrees: it runs
    provider.reported = "stopped"  # someone stopped it in the portal
    assert engine.reconcile() == [ada["id"]]
    assert client.get(f"/api/dotties/{ada['id']}").json()["state"] == "sleeping"
    assert provider.slept == 0  # nothing left for us to stop
