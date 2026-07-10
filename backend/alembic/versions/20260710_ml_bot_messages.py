"""ml-bot: create ml_bot_messages table + seed ml_bot.messages.ver permission

Revision ID: 20260710_ml_bot_messages
Revises: 20260708_ml_bot_roster
Create Date: 2026-07-10

PR1 of the ML Bot Postventa Messages MVP (read-only). Creates the
`ml_bot_messages` table (sibling of `ml_bot_questions`, design §"Schema"),
seeds the granular `ml_bot.messages.ver` permission (categoria=ventas_ml,
orden=510, non-critical) and grants it to every role that currently holds
`ml_bot.ver` — new capability layered on top of an existing one, not a
replacement, so grants mirror the existing holders rather than admin-only.

No runtime behavior change: nothing reads/writes `ml_bot_messages` yet
(ingestor + router land in follow-up PRs of this same change).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260710_ml_bot_messages"
down_revision: Union[str, None] = "20260708_ml_bot_roster"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_MESSAGES_VER_PERMISO = {
    "codigo": "ml_bot.messages.ver",
    "nombre": "Ver mensajes postventa del bot ML",
    "descripcion": "Ver la lista de mensajes postventa ingestados por el bot ML",
    "categoria": "ventas_ml",
    "orden": 510,
    "es_critico": False,
}

_SOURCE_PERMISO_CODIGO = "ml_bot.ver"


def upgrade() -> None:
    op.create_table(
        "ml_bot_messages",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("ml_message_id", sa.String(length=64), nullable=False),
        sa.Column("pack_id", sa.String(length=32), nullable=True),
        sa.Column("buyer_id", sa.BigInteger(), nullable=True),
        sa.Column("buyer_nickname", sa.String(length=255), nullable=True),
        sa.Column("seller_id", sa.BigInteger(), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("moderation_status", sa.String(length=50), nullable=True),
        sa.Column("is_first_message", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("attachments", sa.JSON(), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("kind", sa.String(length=16), nullable=False, server_default="postventa"),
        sa.Column("taken_over_by", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("ingested_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["taken_over_by"], ["usuarios.id"]),
        sa.UniqueConstraint("ml_message_id", name="uq_ml_bot_messages_ml_message_id"),
    )
    op.create_index("idx_ml_bot_messages_pack_id", "ml_bot_messages", ["pack_id"])
    op.create_index("idx_ml_bot_messages_buyer_id", "ml_bot_messages", ["buyer_id"])
    op.create_index("idx_ml_bot_messages_received_at", "ml_bot_messages", ["received_at"])
    op.create_index(
        "idx_ml_bot_messages_moderation_status",
        "ml_bot_messages",
        ["moderation_status"],
        postgresql_where=sa.text("moderation_status IS NOT NULL AND moderation_status != 'clean'"),
    )

    conn = op.get_bind()

    conn.execute(
        sa.text(
            """
            INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico)
            VALUES (:codigo, :nombre, :descripcion, :categoria, :orden, :es_critico)
            ON CONFLICT (codigo) DO NOTHING
            """
        ),
        _MESSAGES_VER_PERMISO,
    )

    conn.execute(
        sa.text(
            """
            INSERT INTO roles_permisos_base (rol_id, permiso_id)
            SELECT rp.rol_id, p_new.id
            FROM roles_permisos_base rp
            JOIN permisos p_src ON p_src.id = rp.permiso_id AND p_src.codigo = :source_codigo
            JOIN permisos p_new ON p_new.codigo = :new_codigo
            ON CONFLICT (rol_id, permiso_id) DO NOTHING
            """
        ),
        {"source_codigo": _SOURCE_PERMISO_CODIGO, "new_codigo": _MESSAGES_VER_PERMISO["codigo"]},
    )


def downgrade() -> None:
    conn = op.get_bind()

    conn.execute(
        sa.text("DELETE FROM permisos WHERE codigo = :codigo"),
        {"codigo": _MESSAGES_VER_PERMISO["codigo"]},
    )

    op.drop_index("idx_ml_bot_messages_moderation_status", table_name="ml_bot_messages")
    op.drop_index("idx_ml_bot_messages_received_at", table_name="ml_bot_messages")
    op.drop_index("idx_ml_bot_messages_buyer_id", table_name="ml_bot_messages")
    op.drop_index("idx_ml_bot_messages_pack_id", table_name="ml_bot_messages")
    op.drop_table("ml_bot_messages")
