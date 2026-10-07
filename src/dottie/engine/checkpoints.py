"""LangGraph keeps each conversation's agent state (its checkpoints) in this app's PostgreSQL, keyed by thread id."""

from typing import Any

from langgraph.checkpoint.postgres import PostgresSaver
from psycopg import Connection
from psycopg.rows import dict_row

from ..config import Settings
from ..db import entra_password


def _connect(settings: Settings) -> Connection[Any]:
    extra: dict[str, Any] = {"autocommit": True, "row_factory": dict_row}
    if settings.database_entra_auth:
        extra["password"] = entra_password()()
    return Connection.connect(settings.database_url, **extra)


def setup(settings: Settings) -> None:
    """Create or migrate LangGraph's own tables (checkpoint*), which Alembic leaves alone."""
    with _connect(settings) as conn:
        PostgresSaver(conn).setup()


def delete_thread(settings: Settings, thread_id: str) -> None:
    with _connect(settings) as conn:
        PostgresSaver(conn).delete_thread(thread_id)
