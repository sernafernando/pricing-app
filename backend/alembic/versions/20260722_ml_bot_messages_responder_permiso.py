"""ml-bot-messages-reply Phase A PR2: seed ml_bot.messages.responder permission

Revision ID: 20260722_ml_bot_messages_responder_permiso
Revises: 20260722_ml_bot_messages_bot_columns
Create Date: 2026-07-22

Seeds the granular `ml_bot.messages.responder` permission (categoria=ventas_ml,
orden=511, non-critical), required by the new human take-over/edit/send
endpoints on `ml_bot_messages` (mirrors `ml_bot.responder` for questions).
Grants it to every role that currently holds `ml_bot.messages.ver` — a human
who can already see postventa messages gets the new capability to act on
them, not an admin-only grant.

No runtime behavior change on its own — the router endpoints that check this
permission land in the same PR, additive only.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260722_ml_bot_messages_responder_permiso"
down_revision: Union[str, None] = "20260722_ml_bot_messages_bot_columns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_MESSAGES_RESPONDER_PERMISO = {
    "codigo": "ml_bot.messages.responder",
    "nombre": "Responder mensajes postventa del bot ML",
    "descripcion": "Tomar, editar y enviar respuestas a mensajes postventa ingestados por el bot ML",
    "categoria": "ventas_ml",
    "orden": 511,
    "es_critico": False,
}

_SOURCE_PERMISO_CODIGO = "ml_bot.messages.ver"


def upgrade() -> None:
    conn = op.get_bind()

    conn.execute(
        sa.text(
            """
            INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico)
            VALUES (:codigo, :nombre, :descripcion, :categoria, :orden, :es_critico)
            ON CONFLICT (codigo) DO NOTHING
            """
        ),
        _MESSAGES_RESPONDER_PERMISO,
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
        {"source_codigo": _SOURCE_PERMISO_CODIGO, "new_codigo": _MESSAGES_RESPONDER_PERMISO["codigo"]},
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text("DELETE FROM permisos WHERE codigo = :codigo"),
        {"codigo": _MESSAGES_RESPONDER_PERMISO["codigo"]},
    )
