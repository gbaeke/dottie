import os

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from dottie.api.app import create_app
from dottie.config import Settings, settings_without_env_file
from dottie.db import run_migrations
from dottie.models import Base

from .fakes import ScriptedModel

# the same PostgreSQL as the app (scripts/db.sh up), its own database; CI sets TEST_DATABASE_URL
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "postgresql://dottie:dottie@localhost:54845/dottie_test")


@pytest.fixture(autouse=True)
def isolate_from_env(monkeypatch):
    """No setting leaks in from the shell: tests build their Settings explicitly."""
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)


@pytest.fixture(scope="session")
def database() -> str:
    """A fresh schema at the start of the run, migrated to head once."""
    settings = settings_without_env_file(database_url=TEST_DATABASE_URL)
    engine = create_engine(settings.db_url)
    try:
        with engine.begin() as c:
            c.execute(text("DROP SCHEMA public CASCADE"))
            c.execute(text("CREATE SCHEMA public"))
    except OperationalError as e:
        pytest.exit(f"No test database at {TEST_DATABASE_URL}: start it with scripts/db.sh up\n{e}", 2)
    finally:
        engine.dispose()
    run_migrations(settings)
    return TEST_DATABASE_URL


@pytest.fixture
def settings(database) -> Settings:
    """Empty tables for every test (truncating is much faster than migrating again)."""
    settings = settings_without_env_file(
        database_url=database,
        engine_enabled=False,
        sandbox_backend="none",
        llm_base_url="http://fake/v1",
        llm_model="fake",
    )
    engine = create_engine(settings.db_url)
    with engine.begin() as c:
        tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
        c.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    engine.dispose()
    return settings


@pytest.fixture
def scripts() -> dict[str, list[AIMessage]]:
    """What each dottie's (fake) model will say, by slug, in order: a test fills it in before waking anyone."""
    return {}


@pytest.fixture
def client(settings, scripts):
    """The app on test settings and scripted models; `with` runs its startup and shutdown. The engine does not run on
    its own: tests call `client.app.state.engine.tick()` to let it look for work."""
    queues = {}

    def model_for(_settings, dottie):
        queues.setdefault(dottie.slug, iter(scripts.get(dottie.slug, [AIMessage("Hello.")])))
        return ScriptedModel(messages=queues[dottie.slug])

    with TestClient(create_app(settings, model_factory=model_for)) as c:
        yield c
