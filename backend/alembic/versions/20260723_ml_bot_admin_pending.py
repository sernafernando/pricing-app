"""ml-bot: create ml_bot_admin_pending_requests table + seed permissions

Revision ID: 20260723_ml_bot_admin_pending
Revises: 20260722_tn_producto_published
Create Date: 2026-07-23

PR1 of ML Bot Phase B — derive-to-admin lane (Factura A / CUIT), sdd/ml-bot-
admin-pending. Creates the `ml_bot_admin_pending_requests` table (design
"Schema") and seeds two granular permissions (`ml_bot.admin_pending.ver` /
`.gestionar`, categoria=ventas_ml, non-critical), mirroring
`20260710_ml_bot_messages.py`'s pattern: `.ver` is granted to every role that
currently holds `ml_bot.messages.ver`, `.gestionar` to every role that
currently holds `ml_bot.messages.responder`.

No runtime behavior change in PR1: nothing reads/writes this table yet
outside the (best-effort, additive) derive hook landing in this same PR;
endpoints land in PR2.

Dialect-safe (design decision #8): the (pack_id, request_type) single-open-
row invariant is enforced primarily at the app level
(`admin_pending_service`); the Postgres-only PARTIAL unique index here is a
belt, guarded so sqlite CI never gets a stricter (full) unique constraint
than the real Postgres deployment target.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260723_ml_bot_admin_pending"
down_revision: Union[str, None] = "20260722_tn_producto_published"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_VER_PERMISO = {
    "codigo": "ml_bot.admin_pending.ver",
    "nombre": "Ver tareas pendientes admin del bot ML",
    "descripcion": "Ver la cola de tareas back-office derivadas de mensajes postventa (cambios de CUIT/factura)",
    "categoria": "ventas_ml",
    "orden": 520,
    "es_critico": False,
}

_GESTIONAR_PERMISO = {
    "codigo": "ml_bot.admin_pending.gestionar",
    "nombre": "Gestionar tareas pendientes admin del bot ML",
    "descripcion": "Tomar, resolver o cancelar tareas back-office derivadas de mensajes postventa",
    "categoria": "ventas_ml",
    "orden": 521,
    "es_critico": False,
}

_VER_SOURCE_CODIGO = "ml_bot.messages.ver"
_GESTIONAR_SOURCE_CODIGO = "ml_bot.messages.responder"


def upgrade() -> None:
    op.create_table(
        "ml_bot_admin_pending_requests",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=True),
        sa.Column("pack_id", sa.String(length=32), nullable=True),
        sa.Column("buyer_id", sa.BigInteger(), nullable=True),
        sa.Column("request_type", sa.String(length=40), nullable=False, server_default="invoice_cuit_change"),
        sa.Column("source", sa.String(length=16), nullable=False, server_default="bot_derived"),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("extracted_cuit", sa.String(length=20), nullable=True),
        sa.Column("extracted_name", sa.String(length=255), nullable=True),
        sa.Column("cuit_valid", sa.Boolean(), nullable=True),
        sa.Column("prefill_nickname", sa.String(length=255), nullable=True),
        sa.Column("prefill_identification_type", sa.String(length=255), nullable=True),
        sa.Column("prefill_identification_number", sa.String(length=255), nullable=True),
        sa.Column("prefill_billing_doc_type", sa.String(length=255), nullable=True),
        sa.Column("prefill_billing_doc_number", sa.String(length=255), nullable=True),
        sa.Column("prefill_billing_first_name", sa.String(length=255), nullable=True),
        sa.Column("prefill_billing_last_name", sa.String(length=255), nullable=True),
        sa.Column("doc_mismatch", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("afip_status", sa.String(length=16), nullable=True),
        sa.Column("afip_razon_social", sa.String(length=255), nullable=True),
        sa.Column("afip_condicion_iva", sa.String(length=64), nullable=True),
        sa.Column("afip_domicilio", sa.String(length=500), nullable=True),
        sa.Column("afip_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("superseded_values", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="new"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("cancel_reason", sa.Text(), nullable=True),
        sa.Column("resolved_cuit", sa.String(length=20), nullable=True),
        sa.Column("resolved_cuit_valid", sa.Boolean(), nullable=True),
        sa.Column("resolved_by", sa.Integer(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("claimed_by", sa.Integer(), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["message_id"], ["ml_bot_messages.id"]),
        sa.ForeignKeyConstraint(["resolved_by"], ["usuarios.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["usuarios.id"]),
        sa.ForeignKeyConstraint(["claimed_by"], ["usuarios.id"]),
    )
    op.create_index("idx_ml_bot_admin_pending_status", "ml_bot_admin_pending_requests", ["status"])
    op.create_index("idx_ml_bot_admin_pending_pack_id", "ml_bot_admin_pending_requests", ["pack_id"])
    op.create_index("idx_ml_bot_admin_pending_message_id", "ml_bot_admin_pending_requests", ["message_id"])
    op.create_index(
        "idx_ml_bot_admin_pending_pack_request_type",
        "ml_bot_admin_pending_requests",
        ["pack_id", "request_type"],
    )

    conn = op.get_bind()

    if conn.dialect.name == "postgresql":
        op.create_index(
            "uq_ml_bot_admin_pending_open_pack_request_type",
            "ml_bot_admin_pending_requests",
            ["pack_id", "request_type"],
            unique=True,
            postgresql_where=sa.text("status IN ('new', 'in_progress')"),
        )

    for permiso in (_VER_PERMISO, _GESTIONAR_PERMISO):
        conn.execute(
            sa.text(
                """
                INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico)
                VALUES (:codigo, :nombre, :descripcion, :categoria, :orden, :es_critico)
                ON CONFLICT (codigo) DO NOTHING
                """
            ),
            permiso,
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
        {"source_codigo": _VER_SOURCE_CODIGO, "new_codigo": _VER_PERMISO["codigo"]},
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
        {"source_codigo": _GESTIONAR_SOURCE_CODIGO, "new_codigo": _GESTIONAR_PERMISO["codigo"]},
    )


def downgrade() -> None:
    conn = op.get_bind()

    conn.execute(sa.text("DELETE FROM permisos WHERE codigo = :codigo"), {"codigo": _GESTIONAR_PERMISO["codigo"]})
    conn.execute(sa.text("DELETE FROM permisos WHERE codigo = :codigo"), {"codigo": _VER_PERMISO["codigo"]})

    if conn.dialect.name == "postgresql":
        op.drop_index("uq_ml_bot_admin_pending_open_pack_request_type", table_name="ml_bot_admin_pending_requests")

    op.drop_index("idx_ml_bot_admin_pending_pack_request_type", table_name="ml_bot_admin_pending_requests")
    op.drop_index("idx_ml_bot_admin_pending_message_id", table_name="ml_bot_admin_pending_requests")
    op.drop_index("idx_ml_bot_admin_pending_pack_id", table_name="ml_bot_admin_pending_requests")
    op.drop_index("idx_ml_bot_admin_pending_status", table_name="ml_bot_admin_pending_requests")
    op.drop_table("ml_bot_admin_pending_requests")
