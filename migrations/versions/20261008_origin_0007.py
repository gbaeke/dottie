"""conversation origin

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-08 09:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("origin_id", sa.String(length=40), nullable=True))
    op.create_foreign_key(
        op.f("fk_conversations_origin_id_conversations"),
        "conversations",
        "conversations",
        ["origin_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("fk_conversations_origin_id_conversations"), "conversations", type_="foreignkey")
    op.drop_column("conversations", "origin_id")
