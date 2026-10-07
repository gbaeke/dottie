"""A dottie's computer: somewhere to run commands and keep working files, which sleeps when the dottie does.

The agent's brain (Deep Agents) runs in this app; its tools reach the sandbox through `execute()` and file transfer,
which is the only thing a Deep Agents sandbox backend has to provide. So the sandbox can be stopped, suspended or
lost without losing the dottie: identity, memory and wiki are in PostgreSQL.

Providers: `none` (no shell: the dottie has its wiki and nothing else), `docker` (a container per dottie, for local
work), `aca` (Azure Container Apps Sandboxes: suspend and resume with disk and memory).
"""

import logging
import shlex
import subprocess
from abc import ABC, abstractmethod

from deepagents.backends.protocol import (
    ExecuteResponse,
    FileDownloadResponse,
    FileUploadResponse,
    SandboxBackendProtocol,
)
from deepagents.backends.sandbox import BaseSandbox

from ..config import Settings
from ..models import Dottie

log = logging.getLogger(__name__)

WORKDIR = "/workspace"
MAX_OUTPUT = 60_000  # characters handed back to the model; the rest is cut (and flagged)
DEFAULT_TIMEOUT = 120


class SandboxProvider(ABC):
    """Creates, wakes and sleeps the computers. `ref` is whatever the provider needs to find a sandbox again."""

    name: str

    @abstractmethod
    def wake(self, dottie: Dottie) -> tuple[SandboxBackendProtocol | None, str | None]:
        """A running sandbox for this dottie (creating it the first time) and its ref to store on the dottie."""

    @abstractmethod
    def sleep(self, ref: str) -> None: ...

    @abstractmethod
    def destroy(self, ref: str) -> None: ...

    def state(self, ref: str | None) -> str:
        """`none` | `stopped` | `running`, for the UI."""
        return "none" if ref is None else "unknown"


class NoSandbox(SandboxProvider):
    name = "none"

    def wake(self, dottie: Dottie) -> tuple[None, None]:  # noqa: ARG002
        return None, None

    def sleep(self, ref: str) -> None:
        pass

    def destroy(self, ref: str) -> None:
        pass


# --- Docker ------------------------------------------------------------


def _docker(*args: str, input: bytes | None = None, timeout: int = 60) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["docker", *args], input=input, capture_output=True, timeout=timeout, check=False)  # noqa: S603, S607


class DockerSandbox(BaseSandbox):
    def __init__(self, container: str):
        self.container = container

    @property
    def id(self) -> str:
        return self.container

    def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        limit = timeout or DEFAULT_TIMEOUT
        try:
            done = _docker("exec", "-w", WORKDIR, self.container, "bash", "-c", command, timeout=limit)
        except subprocess.TimeoutExpired:
            return ExecuteResponse(output=f"Command timed out after {limit}s.", exit_code=124)
        text = (done.stdout + done.stderr).decode(errors="replace")
        return ExecuteResponse(output=text[:MAX_OUTPUT], exit_code=done.returncode, truncated=len(text) > MAX_OUTPUT)

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        results: list[FileUploadResponse] = []
        for path, content in files:
            script = f'mkdir -p "$(dirname {shlex.quote(path)})" && cat > {shlex.quote(path)}'
            done = _docker("exec", "-i", self.container, "bash", "-c", script, input=content)
            results.append(FileUploadResponse(path=path, error=None if done.returncode == 0 else "permission_denied"))
        return results

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        results: list[FileDownloadResponse] = []
        for path in paths:
            done = _docker("exec", self.container, "cat", path)
            ok = done.returncode == 0
            results.append(
                FileDownloadResponse(
                    path=path, content=done.stdout if ok else None, error=None if ok else "file_not_found"
                )
            )
        return results


class DockerProvider(SandboxProvider):
    name = "docker"

    def __init__(self, image: str):
        self.image = image

    def wake(self, dottie: Dottie) -> tuple[SandboxBackendProtocol, str]:
        name = f"dottie-{dottie.slug}"
        if self.state(name) == "none":
            made = _docker(
                *("run", "-d", "--name", name, "--label", "app=dottie", "--memory", "1g", "--cpus", "1"),
                *("-v", f"{name}:{WORKDIR}", "-w", WORKDIR, self.image, "sleep", "infinity"),
                timeout=600,  # the first time pulls the image
            )
            if made.returncode != 0:
                raise RuntimeError(f"Could not create the sandbox: {made.stderr.decode().strip()}")
        elif self.state(name) == "stopped":
            _docker("start", name)
        return DockerSandbox(name), name

    def sleep(self, ref: str) -> None:
        _docker("stop", "-t", "1", ref)

    def destroy(self, ref: str) -> None:
        _docker("rm", "-f", ref)
        _docker("volume", "rm", "-f", ref)

    def state(self, ref: str | None) -> str:
        if ref is None:
            return "none"
        done = _docker("inspect", "-f", "{{.State.Running}}", ref)
        if done.returncode != 0:
            return "none"
        return "running" if done.stdout.strip() == b"true" else "stopped"


# --- Azure Container Apps Sandboxes ------------------------------------------


class AcaSandbox(BaseSandbox):
    def __init__(self, client):  # azure.containerapps.sandbox.SandboxClient (imported lazily: only Azure needs it)
        self.client = client

    @property
    def id(self) -> str:
        return self.client.sandbox_id

    def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:  # noqa: ARG002
        done = self.client.exec(command, working_directory=WORKDIR)
        text = (done.stdout or "") + (done.stderr or "")
        return ExecuteResponse(output=text[:MAX_OUTPUT], exit_code=done.exit_code, truncated=len(text) > MAX_OUTPUT)

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        results: list[FileUploadResponse] = []
        for path, content in files:
            try:
                self.client.write_file(path, content)
                results.append(FileUploadResponse(path=path))
            except Exception as e:
                results.append(FileUploadResponse(path=path, error=str(e)))
        return results

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        results: list[FileDownloadResponse] = []
        for path in paths:
            try:
                results.append(FileDownloadResponse(path=path, content=self.client.read_file(path)))
            except Exception as e:
                results.append(FileDownloadResponse(path=path, error=str(e)))
        return results


class AcaProvider(SandboxProvider):
    name = "aca"

    def __init__(self, settings: Settings):
        from azure.containerapps.sandbox import SandboxGroupClient, endpoint_for_region
        from azure.identity import DefaultAzureCredential

        self.idle_seconds = settings.sandbox_idle_seconds
        self.group = SandboxGroupClient(
            endpoint_for_region(settings.sandbox_region),
            DefaultAzureCredential(),
            subscription_id=settings.azure_subscription_id,
            resource_group=settings.azure_resource_group,
            sandbox_group=settings.sandbox_group,
        )

    def wake(self, dottie: Dottie) -> tuple[SandboxBackendProtocol, str]:
        if dottie.sandbox_ref:
            client = self.group.get_sandbox_client(dottie.sandbox_ref)
            client.ensure_running()  # resumes a suspended sandbox with its disk (and memory) as it was
        else:
            client = self.group.begin_create_sandbox(
                disk="ubuntu",
                auto_suspend_seconds=self.idle_seconds,
                labels={"app": "dottie", "dottie": dottie.slug},
            ).result()
            client.exec(f"mkdir -p {WORKDIR}")
        return AcaSandbox(client), client.sandbox_id

    def sleep(self, ref: str) -> None:
        self.group.get_sandbox_client(ref).stop()

    def destroy(self, ref: str) -> None:
        self.group.get_sandbox_client(ref).delete()

    def state(self, ref: str | None) -> str:
        if ref is None:
            return "none"
        try:
            state = (self.group.get_sandbox_client(ref).get().state or "").lower()
        except Exception:
            return "unknown"
        return "running" if state == "running" else "stopped"


def make_provider(settings: Settings) -> SandboxProvider:
    if settings.sandbox_backend == "docker":
        return DockerProvider(settings.sandbox_image)
    if settings.sandbox_backend == "aca":
        return AcaProvider(settings)
    return NoSandbox()
