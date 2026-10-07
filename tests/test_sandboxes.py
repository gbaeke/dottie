"""The docker sandbox: a real container, so these run only where Docker does."""

import shutil
import subprocess
import uuid

import pytest

from dottie.engine.sandboxes import DockerProvider
from dottie.models import Dottie

pytestmark = pytest.mark.skipif(
    shutil.which("docker") is None or subprocess.run(["docker", "info"], capture_output=True).returncode != 0,  # noqa: S607
    reason="Docker is not available",
)


def test_a_sandbox_runs_commands_keeps_files_and_sleeps():
    provider = DockerProvider("python:3.14-slim")
    dottie = Dottie(name="T", slug=f"test-{uuid.uuid4().hex[:8]}")
    ref = None
    try:
        sandbox, ref = provider.wake(dottie)
        assert provider.state(ref) == "running"

        sandbox.write("/workspace/hello.txt", "hi there")  # the file tools work through execute and upload
        assert sandbox.execute("cat /workspace/hello.txt").output.strip() == "hi there"
        assert sandbox.execute("exit 3").exit_code == 3

        provider.sleep(ref)
        assert provider.state(ref) == "stopped"

        again, same = provider.wake(dottie)  # waking it again finds its files where they were
        assert same == ref
        assert again.execute("cat /workspace/hello.txt").output.strip() == "hi there"
    finally:
        if ref:
            provider.destroy(ref)
    assert provider.state(ref) == "none"
