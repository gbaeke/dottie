"""The part of the app that is always awake: it fires due schedules and wakes the dotties that have mail.

Dotties themselves do not run between wakings. Exactly one process runs this loop (an advisory lock in PostgreSQL
decides which, when there are several replicas); everything it does is rows in, rows out.
"""

import logging
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

from sqlalchemy import Engine as SqlEngine
from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session, sessionmaker

from ..config import Settings
from ..models import Dottie, Run
from . import bus, scheduler
from .runner import Runner
from .tools import record

log = logging.getLogger(__name__)

LEADER_LOCK = 0x646F74  # any constant: only the process holding it runs the loop
REAP_EVERY = 5.0  # seconds between looks for idle sandboxes
RECONCILE_EVERY = 30.0  # seconds between checks that the sandboxes we think are running are


class Engine:
    def __init__(self, settings: Settings, db: SqlEngine, sessions: sessionmaker[Session], runner: Runner):
        self.settings, self.db, self.sessions, self.runner = settings, db, sessions, runner
        self.pool = ThreadPoolExecutor(settings.max_workers, thread_name_prefix="dottie")
        self.active: dict[int, Future[int]] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._nudge = threading.Event()  # set by the API when something new is waiting: no need to wait for the poll
        self._thread: threading.Thread | None = None
        self._leader = None  # a connection that holds the advisory lock while this process leads

    # --- lifecycle ---

    def start(self) -> None:
        with self.sessions() as s:  # whatever a crash left half done
            bus.requeue_orphans(s)
            s.execute(
                update(Run).where(Run.status == "running").values(status="failed", summary="Interrupted by a restart.")
            )
            s.commit()
        self._thread = threading.Thread(target=self._loop, name="dottie-engine", daemon=True)
        self._thread.start()

    def nudge(self) -> None:
        """Look for work now: a message was just posted."""
        self._nudge.set()

    def stop(self) -> None:
        self._stop.set()
        self._nudge.set()
        if self._thread:
            self._thread.join(timeout=10)
        self.pool.shutdown(wait=False, cancel_futures=True)
        if self._leader is not None:
            self._leader.close()

    def _loop(self) -> None:
        next_reap = next_reconcile = 0.0
        while not self._stop.is_set():
            self._nudge.wait(self.settings.poll_seconds)
            self._nudge.clear()
            if self._stop.is_set():
                break
            try:
                if self._is_leader():
                    self.tick()
                    if time.monotonic() >= next_reap:
                        next_reap = time.monotonic() + REAP_EVERY
                        self.reap_idle()
                    if time.monotonic() >= next_reconcile:
                        next_reconcile = time.monotonic() + RECONCILE_EVERY
                        self.reconcile()
            except Exception:
                log.exception("engine tick failed")

    def _is_leader(self) -> bool:
        """Take (or keep) the leader lock. Losing the connection loses the lock, so another replica takes over."""
        try:
            if self._leader is None:
                self._leader = self.db.connect()
                got = self._leader.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": LEADER_LOCK}).scalar()
                if not got:
                    self._leader.close()
                    self._leader = None
                    return False
            self._leader.execute(text("SELECT 1"))
            return True
        except Exception:
            self._leader = None
            return False

    # --- one pass ---

    def tick(self) -> list[int]:
        """Fire due schedules, then wake every dottie that has mail and is not already awake. Returns who was woken."""
        with self.sessions() as s:
            if scheduler.fire_due(s):
                s.commit()
            waiting = bus.dotties_with_mail(s)
            s.commit()
        woken: list[int] = []
        with self._lock:
            for dottie_id in waiting:
                if dottie_id not in self.active:
                    future = self.pool.submit(self.runner.wake, dottie_id)
                    self.active[dottie_id] = future
                    future.add_done_callback(lambda _, d=dottie_id: self._done(d))
                    woken.append(dottie_id)
        return woken

    def reap_idle(self, now: datetime | None = None) -> list[int]:
        """Stop the sandboxes of dotties idle for `sandbox_idle_seconds`: no run in progress, and the last one ended
        that long ago. Until then a sandbox stays warm, so a follow-up message finds it running."""
        now = now or datetime.now(UTC)
        cutoff = now - timedelta(seconds=self.settings.sandbox_idle_seconds)
        with self.sessions() as s:
            last = (
                select(Run.dottie_id, func.max(Run.finished_at).label("at"))
                .group_by(Run.dottie_id)
                .having(func.count().filter(Run.status == "running") == 0)
                .subquery()
            )
            rows = s.execute(
                select(Dottie.id, Dottie.sandbox_ref)
                .join(last, last.c.dottie_id == Dottie.id)
                .where(Dottie.sandbox_awake, Dottie.sandbox_ref.is_not(None), last.c.at <= cutoff)
            ).all()
        stopped: list[int] = []
        for dottie_id, ref in rows:
            try:
                if ref is not None and self.runner.provider.state(ref) not in ("stopped", "none"):
                    self.runner.provider.sleep(ref)
                    stopped.append(dottie_id)
                self._set_awake(dottie_id, False)
                record(self.sessions, dottie_id, None, "sleep", "Went to sleep.")
            except Exception:
                log.exception("could not stop the sandbox of dottie %s", dottie_id)
        return stopped

    def reconcile(self) -> list[int]:
        """Dotties marked awake whose sandbox is in fact stopped (someone stopped it in the portal, the platform
        suspended it): mark them asleep, so what the UI says is what is true."""
        with self.sessions() as s:
            rows = s.execute(
                select(Dottie.id, Dottie.sandbox_ref).where(Dottie.sandbox_awake, Dottie.sandbox_ref.is_not(None))
            ).all()
            busy = set(s.scalars(select(Run.dottie_id).where(Run.status == "running")))
        changed: list[int] = []
        for dottie_id, ref in rows:
            if dottie_id in busy or ref is None:
                continue
            try:
                if self.runner.provider.state(ref) in ("stopped", "none"):
                    self._set_awake(dottie_id, False)
                    record(self.sessions, dottie_id, None, "sleep", "Its computer stopped.")
                    changed.append(dottie_id)
            except Exception:
                log.exception("could not check the sandbox of dottie %s", dottie_id)
        return changed

    def _set_awake(self, dottie_id: int, awake: bool) -> None:
        with self.sessions() as s:
            s.get_one(Dottie, dottie_id).sandbox_awake = awake
            s.commit()

    def _done(self, dottie_id: int) -> None:
        with self._lock:
            self.active.pop(dottie_id, None)

    def wait_idle(self, timeout: float = 30) -> None:
        """Block until every dottie that is awake has finished (tests)."""
        with self._lock:
            futures = list(self.active.values())
        for f in futures:
            f.result(timeout)
