"""telegram links

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-08 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "telegram_links",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=True),
        sa.Column("chat_id", sa.BigInteger(), nullable=True),
        sa.Column("dottie_id", sa.Integer(), nullable=True),
        sa.Column("conversation_id", sa.String(length=40), nullable=True),
        sa.Column("sent_up_to", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name=op.f("fk_telegram_links_conversation_id_conversations"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["dottie_id"], ["dotties.id"], name=op.f("fk_telegram_links_dottie_id_dotties"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_telegram_links")),
        sa.UniqueConstraint("chat_id", name=op.f("uq_telegram_links_chat_id")),
        sa.UniqueConstraint("code", name=op.f("uq_telegram_links_code")),
    )
    op.create_index(op.f("ix_telegram_links_owner_id"), "telegram_links", ["owner_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_telegram_links_owner_id"), table_name="telegram_links")
    op.drop_table("telegram_links")
