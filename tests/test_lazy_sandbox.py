"""A dottie's sandbox starts only when the agent uses it, and stops again afterwards."""

from datetime import UTC, datetime, timedelta

from deepagents.backends.protocol import ExecuteResponse, FileDownloadResponse, FileUploadResponse
from deepagents.backends.sandbox import BaseSandbox
from fastapi.testclient import TestClient

from dottie.api.app import create_app
from dottie.engine.sandboxes import SandboxProvider

from .fakes import ScriptedModel
from .test_dotties import make
from .test_engine import call, chat, say, use


class FakeSandbox(BaseSandbox):
    @property
    def id(self) -> str:
        return "fake"

    def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        return ExecuteResponse(output=f"ran: {command}", exit_code=0)

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        return [FileUploadResponse(path=p) for p, _ in files]

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        return [FileDownloadResponse(path=p, content=b"") for p in paths]


class CountingProvider(SandboxProvider):
    name = "counting"

    def __init__(self) -> None:
        self.woken = self.slept = 0

    def wake(self, dottie):
        self.woken += 1
        return FakeSandbox(), "sandbox-1"

    def sleep(self, ref: str) -> None:
        self.slept += 1

    def destroy(self, ref: str) -> None:
        pass


def test_sandbox_starts_only_when_used_and_stops_after(settings, scripts):
    provider = CountingProvider()
    scripts["ada"] = [say("Just chatting."), use(call("execute", command="echo hi")), say("Ran it.")]
    queues = {"ada": iter(scripts["ada"])}
    app = create_app(settings, model_factory=lambda _s, d: ScriptedModel(messages=queues[d.slug]), provider=provider)
    with TestClient(app) as client:
        ada = make(client)
        engine = app.state.engine

        chat(client, ada["id"], "Hello")
        engine.tick()
        engine.wait_idle()
        assert (provider.woken, provider.slept) == (0, 0)  # a plain answer leaves the computer alone

        chat(client, ada["id"], "Run echo hi")
        engine.tick()
        engine.wait_idle()
        assert (provider.woken, provider.slept) == (1, 0)  # started on first use, and left warm for follow-ups
        assert client.get(f"/api/dotties/{ada['id']}").json()["state"] == "idle"  # awake: its computer is warm
        engine.reap_idle(datetime.now(UTC) + timedelta(seconds=app.state.settings.sandbox_idle_seconds + 1))
        assert provider.slept == 1  # ...until it has been idle long enough
        assert client.get(f"/api/dotties/{ada['id']}").json()["state"] == "sleeping"
        results = [
            e["text"] for e in client.get(f"/api/dotties/{ada['id']}/events").json() if e["kind"] == "tool_result"
        ]
        assert any("ran: echo hi" in r for r in results)
