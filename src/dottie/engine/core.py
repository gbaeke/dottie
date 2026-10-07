"""The part of the app that is always awake: it fires due schedules and wakes the dotties that have mail.

Dotties themselves do not run between wakings. Exactly one process runs this loop (an advisory lock in PostgreSQL
decides which, when there are several replicas); everything it does is rows in, rows out.
"""

import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor

from sqlalchemy import Engine as SqlEngine
from sqlalchemy import text, update
from sqlalchemy.orm import Session, sessionmaker

from ..config import Settings
from ..models import Run
from . import bus, scheduler
from .runner import Runner

log = logging.getLogger(__name__)

LEADER_LOCK = 0x646F74  # any constant: only the process holding it runs the loop


class Engine:
    def __init__(self, settings: Settings, db: SqlEngine, sessions: sessionmaker[Session], runner: Runner):
        self.settings, self.db, self.sessions, self.runner = settings, db, sessions, runner
        self.pool = ThreadPoolExecutor(settings.max_workers, thread_name_prefix="dottie")
        self.active: dict[int, Future[int]] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
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

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=10)
        self.pool.shutdown(wait=False, cancel_futures=True)
        if self._leader is not None:
            self._leader.close()

    def _loop(self) -> None:
        while not self._stop.wait(self.settings.poll_seconds):
            try:
                if self._is_leader():
                    self.tick()
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

    def _done(self, dottie_id: int) -> None:
        with self._lock:
            self.active.pop(dottie_id, None)

    def wait_idle(self, timeout: float = 30) -> None:
        """Block until every dottie that is awake has finished (tests)."""
        with self._lock:
            futures = list(self.active.values())
        for f in futures:
            f.result(timeout)
