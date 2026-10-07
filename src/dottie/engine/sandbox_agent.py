"""The agent inside the sandbox: put its runtime there, start it, and wait for it to report that it is done.

In this mode the app is a control plane. It wakes the dottie's sandbox, makes sure `dottie_runtime` is installed in it,
starts the runtime with a token for this run, and waits. The agent loop, the shell and the working files all live in the
sandbox; the model, the wiki, the tools and the feed are reached through `api/internal.py`.
"""

import contextlib
import hashlib
import importlib.metadata
import json
import logging
import shlex
import time
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

import dottie_runtime

from ..config import Settings
from ..models import Dottie, Run
from .sandboxes import WORKDIR, SandboxProvider
from .tools import record

log = logging.getLogger(__name__)

HOME = "/opt/dottie"
INBOX = f"{WORKDIR}/.dottie/inbox"  # run tickets for the runtime that stays alive in the sandbox
PIDFILE = f"{WORKDIR}/.dottie/runtime.pid"
RUNTIME_PACKAGES = ["deepagents", "langchain-openai", "langgraph-checkpoint-sqlite", "httpx"]
POLL_SECONDS = 0.3  # how often a waiting run looks at whether the agent has finished
WARM_MARGIN = 15  # trust a sandbox to be running this many seconds less than the idle window
STUCK_CHECKS = 2  # probes in a row that find the ticket still waiting: the runtime is stuck
ALIVE_CHECK_SECONDS = 15  # also what keeps the sandbox from counting as idle while the agent thinks
INSTALL_TIMEOUT = 900

INSTALL = f"""set -e
trap 'echo failed > {HOME}/failed' ERR
rm -f {HOME}/failed
pkill -f 'dottie_runtime' || true  # a runtime from before this install is replaced, not left running
rm -f {PIDFILE}
export DEBIAN_FRONTEND=noninteractive
if ! python3 -c 'import venv, ensurepip' 2>/dev/null; then
  apt-get update -qq && apt-get install -y -qq python3 python3-venv python3-pip
fi
python3 -m venv {HOME}/venv
{HOME}/venv/bin/pip install -q -r {HOME}/requirements.txt
cp {HOME}/stamp.new {HOME}/stamp
"""


def runtime_files() -> dict[str, bytes]:
    """The runtime's source, by path inside the sandbox."""
    root = Path(dottie_runtime.__file__).parent
    return {f"{HOME}/app/dottie_runtime/{p.name}": p.read_bytes() for p in sorted(root.glob("*.py"))}


def requirements() -> str:
    """The libraries the runtime needs, at the versions this app was tested with."""
    return "\n".join(f"{name}=={importlib.metadata.version(name)}" for name in RUNTIME_PACKAGES) + "\n"


def stamp(files: dict[str, bytes], pins: str) -> str:
    digest = hashlib.sha256(pins.encode())
    for path, content in files.items():
        digest.update(path.encode() + content)
    return digest.hexdigest()[:16]


class SandboxAgent:
    def __init__(self, settings: Settings, sessions: sessionmaker[Session], provider: SandboxProvider):
        self.settings, self.sessions, self.provider = settings, sessions, provider
        # dottie -> (its sandbox, until when it is surely still running). While a sandbox is warm, a run skips the calls
        # that find out: waking it and checking that the runtime is installed.
        self._warm: dict[int, tuple[str, float]] = {}

    def run(self, dottie_id: int, run_id: int) -> tuple[str, str]:
        """Run the agent for this run in the dottie's sandbox. Returns (status, reply); the reply is empty when the
        agent has reported its own end (it has already delivered its answer)."""
        with self.sessions() as s:
            dottie = s.get_one(Dottie, dottie_id)
            token = s.get_one(Run, run_id).token
            s.expunge(dottie)
        self._mark_awake(dottie.id)  # its computer is about to run (or already does)
        sandbox, pid = self._start_warm(dottie, token, run_id)
        if sandbox is None or pid is None:
            sandbox, ref = self.provider.wake(dottie)
            if sandbox is None or ref is None:
                raise RuntimeError(
                    "The agent runs in a sandbox, and this installation has none (SANDBOX_BACKEND=none)."
                )
            with self.sessions() as s:
                dottie_row = s.get_one(Dottie, dottie_id)
                dottie_row.sandbox_ref, dottie_row.sandbox_awake = ref, True
                s.commit()
            self._install(sandbox, dottie_id, run_id)
            pid = self._start(sandbox, token, run_id)
            dottie.sandbox_ref = ref
        outcome = self._wait(sandbox, run_id, pid)
        # Not stopped afterwards: it stays warm for follow-ups until the engine finds it idle (Engine.reap_idle)
        if dottie.sandbox_ref:
            until = time.monotonic() + max(0, self.settings.sandbox_idle_seconds - WARM_MARGIN)
            self._warm[dottie_id] = (dottie.sandbox_ref, until)
        return outcome

    def forget(self, dottie_id: int) -> None:
        """Its sandbox is about to be stopped: do not trust it to be running any more."""
        self._warm.pop(dottie_id, None)

    def _mark_awake(self, dottie_id: int) -> None:
        with self.sessions() as s:
            s.get_one(Dottie, dottie_id).sandbox_awake = True
            s.commit()

    def _start_warm(self, dottie: Dottie, token: str, run_id: int):
        """Start the runtime in a sandbox that ran a moment ago, without asking the platform whether it is up. Any
        trouble (it was stopped after all) is not an error: the caller then wakes it the long way."""
        warm = self._warm.get(dottie.id)
        if not warm or warm[0] != dottie.sandbox_ref or time.monotonic() >= warm[1]:
            return None, None
        try:
            sandbox = self.provider.attach(warm[0])
            return (sandbox, self._start(sandbox, token, run_id)) if sandbox else (None, None)
        except Exception as e:
            log.info("warm start for dottie %s failed (%s): waking its sandbox", dottie.id, e)
            self._warm.pop(dottie.id, None)
            return None, None

    def _install(self, sandbox, dottie_id: int, run_id: int) -> None:
        """Make sure the runtime in the sandbox is the one this app ships. The first time that means installing it,
        which takes minutes: it runs in the background and is polled, so no single call has to last that long."""
        files, pins = runtime_files(), requirements()
        wanted = stamp(files, pins)
        if self._read(sandbox, "stamp") == wanted:
            return
        record(self.sessions, dottie_id, run_id, "note", "Setting up my computer (installing my runtime).")
        uploads = [(path, content) for path, content in files.items()]
        uploads += [
            (f"{HOME}/requirements.txt", pins.encode()),
            (f"{HOME}/stamp.new", wanted.encode()),
            (f"{HOME}/install.sh", INSTALL.encode()),
        ]
        for done in sandbox.upload_files(uploads):
            if done.error:
                raise RuntimeError(f"Could not copy my runtime to my computer ({done.path}: {done.error}).")
        sandbox.execute(f"setsid nohup bash {HOME}/install.sh > {HOME}/install.log 2>&1 < /dev/null &")
        deadline = time.monotonic() + INSTALL_TIMEOUT
        while time.monotonic() < deadline:
            time.sleep(3)
            if self._read(sandbox, "stamp") == wanted:
                return
            if self._read(sandbox, "failed"):
                log_tail = sandbox.execute(f"tail -n 20 {HOME}/install.log").output.strip()
                raise RuntimeError(f"Installing my runtime failed:\n{log_tail}")
        raise RuntimeError("Installing my runtime took too long.")

    @staticmethod
    def _read(sandbox, name: str) -> str:
        return sandbox.execute(f"cat {HOME}/{name} 2>/dev/null || true").output.strip()

    def _daemon_command(self) -> str:
        """The shell command that starts the runtime in the background and records its process id."""
        return (
            f"PYTHONPATH={HOME}/app setsid nohup {HOME}/venv/bin/python -m dottie_runtime "
            f"> {WORKDIR}/.dottie/last.log 2>&1 < /dev/null & echo $! > {PIDFILE}"
        )

    def _start(self, sandbox, token: str, run_id: int) -> str:
        """Hand the run to the runtime in the sandbox, starting it first if it is not running, in one call. Returns the
        runtime's process id (to watch that it stays alive until the run is over)."""
        ticket = json.dumps(
            {
                "api": self.settings.callback_url + "/internal",
                "token": token,
                "timeout": self.settings.run_timeout_seconds,  # the runtime gives up on a hung run by itself
            }
        )
        command = (
            f"mkdir -p {INBOX} && cd {WORKDIR} && "
            f"if ! {{ [ -f {PIDFILE} ] && kill -0 $(cat {PIDFILE}) 2>/dev/null; }}; "
            f"then {self._daemon_command()}; fi && "
            f"printf '%s' {shlex.quote(ticket)} > {INBOX}/{run_id}.tmp && "
            f"mv {INBOX}/{run_id}.tmp {INBOX}/{run_id}.run && cat {PIDFILE}"
        )
        started = sandbox.execute(command)
        pid = started.output.strip().splitlines()[-1] if started.output.strip() else ""
        if started.exit_code != 0 or not pid.isdigit():
            raise RuntimeError(f"Could not start my runtime: {started.output[-500:]}")
        return pid

    def _restart_runtime(self, sandbox, old_pid: str) -> str:
        """Replace a runtime that does not take its tickets (hung on a connection that died when the sandbox was
        stopped, say). The ticket stays in the inbox; the new runtime picks it up."""
        command = (
            f"kill -9 {old_pid} 2>/dev/null; rm -f {PIDFILE}; mkdir -p {INBOX} && cd {WORKDIR} && "
            f"{self._daemon_command()}; sleep 1; cat {PIDFILE}"
        )
        done = sandbox.execute(command)
        pid = done.output.strip().splitlines()[-1] if done.output.strip() else ""
        if not pid.isdigit():
            raise RuntimeError(f"Could not restart my runtime: {done.output[-500:]}")
        return pid

    def _log_tail(self, sandbox, lines: int = 25) -> str:
        try:
            return sandbox.execute(f"tail -n {lines} {WORKDIR}/.dottie/last.log").output.strip()
        except Exception:
            return ""

    def _probe(self, sandbox, pid: str, run_id: int) -> tuple[bool, bool]:
        """(is the runtime alive, is this run's ticket still waiting in the inbox)."""
        done = sandbox.execute(
            f"kill -0 {pid} 2>/dev/null && echo alive; [ -f {INBOX}/{run_id}.run ] && echo waiting; true"
        )
        return "alive" in done.output, "waiting" in done.output

    def _wait(self, sandbox, run_id: int, pid: str) -> tuple[str, str]:
        deadline = time.monotonic() + self.settings.run_timeout_seconds
        next_check = time.monotonic() + ALIVE_CHECK_SECONDS
        unreachable = waiting_checks = 0
        restarted = False
        while True:
            time.sleep(POLL_SECONDS)
            status = self._status(run_id)
            if status != "running":
                return status, ""  # the agent reported its end itself
            now = time.monotonic()
            if now > deadline:
                with contextlib.suppress(Exception):
                    sandbox.execute(f"kill {pid} 2>/dev/null || true")
                tail = self._log_tail(sandbox, 15)
                message = f"I ran out of time ({self.settings.run_timeout_seconds}s) and stopped."
                return "failed", message + (f"\nMy runtime's log:\n{tail}" if tail else "")
            if now < next_check:
                continue
            next_check = now + ALIVE_CHECK_SECONDS
            try:
                alive, waiting = self._probe(sandbox, pid, run_id)
                unreachable = 0
            except Exception as e:  # stopped under us (the platform answers 409) or unreachable: twice in a row
                unreachable += 1
                log.warning("probe of the sandbox failed for run %s: %s", run_id, e)
                if unreachable >= 2:
                    return "failed", "My computer was stopped or could not be reached while I was working. Try again."
                continue
            if not alive and self._status(run_id) == "running":
                return "failed", f"My runtime stopped without finishing.\n{self._log_tail(sandbox)}"
            waiting_checks = waiting_checks + 1 if waiting else 0
            if waiting_checks >= STUCK_CHECKS and not restarted:
                restarted = True  # once per run: a second hang is a failure, not a loop
                log.warning("run %s: its ticket is not taken; restarting the runtime of the sandbox", run_id)
                try:
                    pid = self._restart_runtime(sandbox, pid)
                except Exception as e:
                    return "failed", f"My runtime did not take the task and could not be restarted: {e}"

    def _status(self, run_id: int) -> str:
        with self.sessions() as s:
            return s.scalar(select(Run.status).where(Run.id == run_id)) or "failed"
