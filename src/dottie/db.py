from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session

from .config import Settings

ROOT = Path(__file__).resolve().parents[2]  # where alembic.ini and migrations/ are
ENTRA_SCOPE = "https://ossrdbms-aad.database.windows.net/.default"


def make_engine(settings: Settings) -> Engine:
    # managed PostgreSQL drops idle connections (and a scaled-to-zero app sleeps for hours): test each before use
    engine = create_engine(settings.db_url, pool_pre_ping=True)
    if settings.database_entra_auth:
        password = entra_password()

        @event.listens_for(engine, "do_connect")
        def _token(_dialect, _conn_rec, _cargs, cparams) -> None:
            cparams["password"] = password()

    return engine


def entra_password() -> Callable[[], str]:
    """Azure: a function giving a PostgreSQL password that is an Entra token for the app's managed identity (or your
    az login, locally). Call it per new connection; azure-identity caches the token until shortly before it expires.
    Any other pool needs it too, e.g. psycopg_pool: ConnectionPool(url, kwargs=lambda: {"password": password()})."""
    from azure.identity import DefaultAzureCredential

    credential = DefaultAzureCredential()
    return lambda: credential.get_token(ENTRA_SCOPE).token


def run_migrations(settings: Settings) -> None:
    """Upgrade the database to the latest migration. The app does this at startup, under a lock (migrations/env.py)."""
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.attributes["settings"] = settings
    command.upgrade(cfg, "head")


def get_session(request: Request) -> Iterator[Session]:
    with request.app.state.session_factory() as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]
