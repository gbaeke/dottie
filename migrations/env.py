from alembic import context
from sqlalchemy import text

from dottie.config import get_settings
from dottie.db import make_engine
from dottie.models import Base

MIGRATION_LOCK = 0x6D6967  # any constant: one migration run at a time, however many replicas start together
# tables a library creates and migrates itself (e.g. LangGraph's checkpoint* tables): not ours to diff or migrate
EXTERNAL_TABLE_PREFIXES: tuple[str, ...] = ("checkpoint",)


def include_name(name: str | None, type_: str, _parent_names: object) -> bool:
    return not (type_ == "table" and name is not None and name.startswith(EXTERNAL_TABLE_PREFIXES))


# the app (run_migrations) and the tests pass their settings; the alembic CLI uses the app's (.env)
settings = context.config.attributes.get("settings") or get_settings()

engine = make_engine(settings)
with engine.connect() as connection:
    context.configure(
        connection=connection,
        target_metadata=Base.metadata,
        compare_server_default=True,
        include_name=include_name,
    )
    with context.begin_transaction():
        connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": MIGRATION_LOCK})
        context.run_migrations()
engine.dispose()
