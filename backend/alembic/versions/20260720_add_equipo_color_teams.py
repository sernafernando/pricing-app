"""productos-color-teams: create equipo/equipo_miembro/producto_color + seed global team

Revision ID: 20260720_add_equipo_color_teams
Revises: 20260715_add_promo_sync_watermark
Create Date: 2026-07-20

PR1 of the productos-color-teams change (models + migration only, no
endpoints). Introduces the `equipo` / `equipo_miembro` / `producto_color`
tables so product color marking can eventually be scoped per-team instead of
the single global `productos_pricing.color_marcado` / `color_marcado_tienda`
columns (which are retained, untouched, for rollback safety).

Steps:
1. Create the three tables, including a Postgres partial unique index on
   `equipo.es_global` (only one row may have `es_global = true`).
2. Seed the sentinel "Global" team row (idempotent — guarded by the partial
   unique index via `ON CONFLICT DO NOTHING` on a synthetic constraint name
   is not directly usable for a partial index target, so we use a
   NOT EXISTS guard instead).
3. Backfill `producto_color` from `productos_pricing.color_marcado` /
   `color_marcado_tienda` into the Global team's rows. `color_marcado`
   predates Alembic tracking for this codebase, so both columns are probed
   via `information_schema.columns` before being referenced — if a column
   is absent the backfill degrades gracefully (skips that source column).
4. Seed the `equipos.gestionar_global` permission (categoria=administracion,
   non-critical) and mirror-grant it to every role that already holds
   `admin.gestionar_roles`, following the mirror-grant pattern from
   20260710_ml_bot_messages.py.

Manual Postgres verification (NOT exercised by the SQLite test suite —
partial indexes, ON CONFLICT, and information_schema probing are
Postgres-only constructs):
    1. `alembic upgrade head`
    2. Assert exactly one row in `equipo` with `es_global = true`.
    3. Assert `producto_color` backfill count matches the count of
       `productos_pricing` rows where `color_marcado IS NOT NULL OR
       color_marcado_tienda IS NOT NULL`.
    4. `alembic downgrade -1`, then `alembic upgrade head` again — must be
       idempotent (no duplicate rows, no errors).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260720_add_equipo_color_teams"
down_revision: Union[str, None] = "20260715_add_promo_sync_watermark"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_GESTIONAR_GLOBAL_PERMISO = {
    "codigo": "equipos.gestionar_global",
    "nombre": "Gestionar equipo global",
    "descripcion": "Administrar la configuración y miembros del equipo global de productos",
    "categoria": "administracion",
    "orden": 60,
    "es_critico": False,
}

_SOURCE_PERMISO_CODIGO = "admin.gestionar_roles"


def upgrade() -> None:
    op.create_table(
        "equipo",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("nombre", sa.String(length=255), nullable=False),
        sa.Column("es_global", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("creado_por", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["creado_por"], ["usuarios.id"]),
    )
    op.create_index("ix_equipo_creado_por", "equipo", ["creado_por"])
    op.create_index(
        "uq_equipo_es_global_singleton",
        "equipo",
        ["es_global"],
        unique=True,
        postgresql_where=sa.text("es_global"),
    )

    op.create_table(
        "equipo_miembro",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("equipo_id", sa.Integer(), nullable=False),
        sa.Column("usuario_id", sa.Integer(), nullable=False),
        sa.Column("rol", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["equipo_id"], ["equipo.id"]),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuarios.id"]),
        sa.UniqueConstraint("equipo_id", "usuario_id", name="uq_equipo_miembro_equipo_usuario"),
    )
    op.create_index("ix_equipo_miembro_equipo_id", "equipo_miembro", ["equipo_id"])
    op.create_index("ix_equipo_miembro_usuario_id", "equipo_miembro", ["usuario_id"])

    op.create_table(
        "producto_color",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("equipo_id", sa.Integer(), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("color_ml", sa.String(length=20), nullable=True),
        sa.Column("color_tienda", sa.String(length=20), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["equipo_id"], ["equipo.id"]),
        sa.ForeignKeyConstraint(["item_id"], ["productos_erp.item_id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["usuarios.id"]),
        sa.UniqueConstraint("equipo_id", "item_id", name="uq_producto_color_equipo_item"),
    )
    op.create_index("ix_producto_color_equipo_id", "producto_color", ["equipo_id"])
    op.create_index("ix_producto_color_item_id", "producto_color", ["item_id"])
    op.create_index("ix_producto_color_updated_by", "producto_color", ["updated_by"])

    conn = op.get_bind()

    # 2. Seed the sentinel Global team row (idempotent via NOT EXISTS guard —
    # the partial unique index alone can't be targeted by ON CONFLICT here
    # since it isn't a plain column/expression constraint name).
    conn.execute(
        sa.text(
            """
            INSERT INTO equipo (nombre, es_global, creado_por, created_at)
            SELECT 'Global', true, NULL, now()
            WHERE NOT EXISTS (SELECT 1 FROM equipo WHERE es_global = true)
            """
        )
    )

    # 3. Defensive backfill: color_marcado predates Alembic tracking, so
    # probe information_schema before referencing either color column.
    inspector = sa.inspect(conn)
    pricing_columns = {col["name"] for col in inspector.get_columns("productos_pricing")}
    has_color_marcado = "color_marcado" in pricing_columns
    has_color_marcado_tienda = "color_marcado_tienda" in pricing_columns

    color_ml_expr = "pp.color_marcado" if has_color_marcado else "NULL"
    color_tienda_expr = "pp.color_marcado_tienda" if has_color_marcado_tienda else "NULL"

    if has_color_marcado or has_color_marcado_tienda:
        where_clauses = []
        if has_color_marcado:
            where_clauses.append("pp.color_marcado IS NOT NULL")
        if has_color_marcado_tienda:
            where_clauses.append("pp.color_marcado_tienda IS NOT NULL")
        where_sql = " OR ".join(where_clauses)

        conn.execute(
            sa.text(
                f"""
                INSERT INTO producto_color (equipo_id, item_id, color_ml, color_tienda, updated_at)
                SELECT (SELECT id FROM equipo WHERE es_global = true), pp.item_id,
                       {color_ml_expr}, {color_tienda_expr}, now()
                FROM productos_pricing pp
                WHERE {where_sql}
                ON CONFLICT (equipo_id, item_id) DO NOTHING
                """
            )
        )

    # 4. Seed the equipos.gestionar_global permission and mirror-grant it to
    # every role that already holds admin.gestionar_roles.
    conn.execute(
        sa.text(
            """
            INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico)
            VALUES (:codigo, :nombre, :descripcion, :categoria, :orden, :es_critico)
            ON CONFLICT (codigo) DO NOTHING
            """
        ),
        _GESTIONAR_GLOBAL_PERMISO,
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
        {"source_codigo": _SOURCE_PERMISO_CODIGO, "new_codigo": _GESTIONAR_GLOBAL_PERMISO["codigo"]},
    )


def downgrade() -> None:
    conn = op.get_bind()

    conn.execute(
        sa.text(
            """
            DELETE FROM roles_permisos_base
            WHERE permiso_id = (SELECT id FROM permisos WHERE codigo = :codigo)
            """
        ),
        {"codigo": _GESTIONAR_GLOBAL_PERMISO["codigo"]},
    )
    conn.execute(
        sa.text("DELETE FROM permisos WHERE codigo = :codigo"),
        {"codigo": _GESTIONAR_GLOBAL_PERMISO["codigo"]},
    )

    op.drop_index("ix_producto_color_updated_by", table_name="producto_color")
    op.drop_index("ix_producto_color_item_id", table_name="producto_color")
    op.drop_index("ix_producto_color_equipo_id", table_name="producto_color")
    op.drop_table("producto_color")

    op.drop_index("ix_equipo_miembro_usuario_id", table_name="equipo_miembro")
    op.drop_index("ix_equipo_miembro_equipo_id", table_name="equipo_miembro")
    op.drop_table("equipo_miembro")

    op.drop_index("uq_equipo_es_global_singleton", table_name="equipo")
    op.drop_index("ix_equipo_creado_por", table_name="equipo")
    op.drop_table("equipo")
    # productos_pricing.color_marcado / color_marcado_tienda are intentionally
    # left untouched — they remain the source of truth for rollback safety.
