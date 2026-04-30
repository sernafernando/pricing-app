"""Create RRHH horas extras tables + permisos

Crea las 4 tablas del módulo HE:
  - rrhh_horas_extras_config (singleton, id=1)
  - rrhh_horas_extras (bloque principal, audit revisión 1)
  - rrhh_horas_extras_historial (append-only)
  - rrhh_horas_extras_alertas (Fix riesgo 1)

Seedea:
  - singleton de config (defaults documentados, incluye revisión 2)
  - 4 permisos (`rrhh.ver_horas_extras`, `rrhh.gestionar_horas_extras`,
    `rrhh.aprobar_horas_extras`, `rrhh.liquidar_horas_extras`)
  - asignación a roles base: ADMIN (los 4) y GERENTE (solo ver).

Revision ID: 20260430_rrhh_horas_extras
Revises: add_idx_mlp_official_store_id
Create Date: 2026-04-30
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "20260430_rrhh_horas_extras"
down_revision: Union[str, None] = "add_idx_mlp_official_store_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ─── Permisos del módulo ──────────────────────────────────────────────────
PERMISOS_HE = [
    (
        "rrhh.ver_horas_extras",
        "Ver horas extras",
        "Acceso de lectura a bloques de horas extras y su historial",
        "rrhh",
        130,
        False,
    ),
    (
        "rrhh.gestionar_horas_extras",
        "Gestionar horas extras",
        "Disparar detección manual, editar % recargo, completar fichadas, agregar bloques manuales",
        "rrhh",
        131,
        False,
    ),
    (
        "rrhh.aprobar_horas_extras",
        "Aprobar horas extras",
        "Aprobar/rechazar/reabrir bloques de HE",
        "rrhh",
        132,
        True,
    ),
    (
        "rrhh.liquidar_horas_extras",
        "Liquidar horas extras",
        "Marcar período como liquidado y reabrir post-liquidación",
        "rrhh",
        133,
        True,
    ),
]

# ADMIN recibe los 4. GERENTE solo ver. SUPERADMIN cubierto por wildcard.
ROL_PERMISOS = {
    "ADMIN": [c for c, *_ in PERMISOS_HE],
    "GERENTE": ["rrhh.ver_horas_extras"],
}


def upgrade() -> None:
    # ── 1. rrhh_horas_extras_config (singleton) ─────────────────────────
    op.create_table(
        "rrhh_horas_extras_config",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "porcentaje_dia_habil",
            sa.Numeric(5, 2),
            nullable=False,
            server_default="50.00",
        ),
        sa.Column(
            "porcentaje_sabado_pm",
            sa.Numeric(5, 2),
            nullable=False,
            server_default="100.00",
        ),
        sa.Column(
            "porcentaje_domingo",
            sa.Numeric(5, 2),
            nullable=False,
            server_default="100.00",
        ),
        sa.Column(
            "porcentaje_feriado",
            sa.Numeric(5, 2),
            nullable=False,
            server_default="100.00",
        ),
        sa.Column(
            "hora_corte_sabado",
            sa.Time,
            nullable=False,
            server_default="13:00:00",
        ),
        sa.Column(
            "tolerancia_extras_minutos",
            sa.Integer,
            nullable=False,
            server_default="15",
        ),
        sa.Column(
            "requiere_aprobacion",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "cron_activo",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("true"),
        ),
        # Revisión 2
        sa.Column(
            "dias_retencion_alertas",
            sa.Integer,
            nullable=False,
            server_default="15",
        ),
        sa.Column(
            "cap_dias_recalculo_manual",
            sa.Integer,
            nullable=False,
            server_default="90",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "actualizado_por_id",
            sa.Integer,
            sa.ForeignKey("usuarios.id"),
            nullable=True,
        ),
        sa.CheckConstraint("id = 1", name="ck_rrhh_he_config_singleton"),
        sa.CheckConstraint(
            "porcentaje_dia_habil >= 0 AND porcentaje_sabado_pm >= 0 "
            "AND porcentaje_domingo >= 0 AND porcentaje_feriado >= 0",
            name="ck_rrhh_he_config_pct_no_neg",
        ),
        sa.CheckConstraint(
            "tolerancia_extras_minutos >= 0 AND tolerancia_extras_minutos <= 240",
            name="ck_rrhh_he_config_tolerancia_rango",
        ),
        sa.CheckConstraint(
            "dias_retencion_alertas >= 1",
            name="ck_rrhh_he_config_retencion_alertas",
        ),
        sa.CheckConstraint(
            "cap_dias_recalculo_manual >= 1 AND cap_dias_recalculo_manual <= 366",
            name="ck_rrhh_he_config_cap_recalculo",
        ),
    )
    # Seed singleton
    op.execute(
        """
        INSERT INTO rrhh_horas_extras_config (id) VALUES (1)
        ON CONFLICT (id) DO NOTHING;
        """
    )

    # ── 2. rrhh_horas_extras (tabla principal) ──────────────────────────
    op.create_table(
        "rrhh_horas_extras",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column(
            "empleado_id",
            sa.Integer,
            sa.ForeignKey("rrhh_empleados.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("fecha", sa.Date, nullable=False, index=True),
        sa.Column(
            "fichada_entrada_id",
            sa.Integer,
            sa.ForeignKey("rrhh_fichadas.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "fichada_salida_id",
            sa.Integer,
            sa.ForeignKey("rrhh_fichadas.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "turno_esperado_minutos",
            sa.Integer,
            nullable=False,
            server_default="0",
        ),
        sa.Column("trabajado_minutos", sa.Integer, nullable=True),
        sa.Column("extras_minutos", sa.Integer, nullable=True),
        sa.Column("tipo_dia", sa.String(20), nullable=False),
        sa.Column("porcentaje_recargo", sa.Numeric(5, 2), nullable=False),
        sa.Column(
            "estado",
            sa.String(30),
            nullable=False,
            server_default="detectada",
            index=True,
        ),
        sa.Column("error_tipo", sa.String(40), nullable=True),
        sa.Column(
            "aprobado_por_id",
            sa.Integer,
            sa.ForeignKey("usuarios.id"),
            nullable=True,
        ),
        sa.Column("aprobado_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("motivo_rechazo", sa.Text, nullable=True),
        sa.Column(
            "reabierto_por_id",
            sa.Integer,
            sa.ForeignKey("usuarios.id"),
            nullable=True,
        ),
        sa.Column("reabierto_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("motivo_reapertura", sa.Text, nullable=True),
        sa.Column(
            "liquidacion_periodo",
            sa.String(6),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "liquidado_por_id",
            sa.Integer,
            sa.ForeignKey("usuarios.id"),
            nullable=True,
        ),
        sa.Column("liquidado_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "generada_por",
            sa.String(10),
            nullable=False,
            server_default="sistema",
        ),
        sa.Column(
            "generada_por_id",
            sa.Integer,
            sa.ForeignKey("usuarios.id"),
            nullable=True,
        ),
        sa.Column("observaciones", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "empleado_id",
            "fecha",
            "tipo_dia",
            name="uq_rrhh_he_emp_fecha_tipo",
        ),
        sa.CheckConstraint(
            "estado IN ('pendiente_asignacion_turno','detectada','error_fichadas','aprobada','rechazada','liquidada')",
            name="ck_rrhh_he_estado_valido",
        ),
        sa.CheckConstraint(
            "tipo_dia IN ('habil_50','sabado_100','domingo_100','feriado_100','manual')",
            name="ck_rrhh_he_tipo_dia_valido",
        ),
        sa.CheckConstraint(
            "generada_por IN ('sistema','manual')",
            name="ck_rrhh_he_generada_por_valido",
        ),
        sa.CheckConstraint(
            "porcentaje_recargo >= 0 AND porcentaje_recargo <= 500",
            name="ck_rrhh_he_porcentaje_rango",
        ),
        sa.CheckConstraint(
            "(estado = 'error_fichadas' AND error_tipo IS NOT NULL) OR "
            "(estado <> 'error_fichadas' AND error_tipo IS NULL)",
            name="ck_rrhh_he_error_tipo_consistencia",
        ),
        sa.CheckConstraint(
            "(estado = 'liquidada' AND liquidacion_periodo IS NOT NULL "
            "AND liquidado_por_id IS NOT NULL AND liquidado_at IS NOT NULL) "
            "OR (estado <> 'liquidada')",
            name="ck_rrhh_he_liquidacion_consistencia",
        ),
    )
    op.create_index(
        "idx_rrhh_he_empleado_fecha",
        "rrhh_horas_extras",
        ["empleado_id", "fecha"],
    )
    op.create_index(
        "idx_rrhh_he_fecha_estado",
        "rrhh_horas_extras",
        ["fecha", "estado"],
    )
    op.create_index(
        "idx_rrhh_he_emp_fecha_estado",
        "rrhh_horas_extras",
        ["empleado_id", "fecha", "estado"],
    )
    op.create_index(
        "idx_rrhh_he_liquidacion",
        "rrhh_horas_extras",
        ["liquidacion_periodo"],
        postgresql_where=sa.text("liquidacion_periodo IS NOT NULL"),
    )

    # ── 3. rrhh_horas_extras_historial (append-only) ────────────────────
    op.create_table(
        "rrhh_horas_extras_historial",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column(
            "he_id",
            sa.Integer,
            sa.ForeignKey("rrhh_horas_extras.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("accion", sa.String(40), nullable=False),
        sa.Column("estado_anterior", sa.String(30), nullable=True),
        sa.Column("estado_nuevo", sa.String(30), nullable=False),
        sa.Column(
            "usuario_id",
            sa.Integer,
            sa.ForeignKey("usuarios.id"),
            nullable=True,
        ),
        sa.Column("motivo", sa.Text, nullable=True),
        sa.Column("snapshot", postgresql.JSONB, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "idx_rrhh_he_hist_he_created",
        "rrhh_horas_extras_historial",
        ["he_id", "created_at"],
    )
    op.create_index(
        "idx_rrhh_he_hist_accion",
        "rrhh_horas_extras_historial",
        ["accion"],
    )

    # Hardening: append-only enforcement a nivel DB. El service nunca
    # hace UPDATE/DELETE sobre historial, pero esto bloquea modificaciones
    # manuales accidentales (queries directas, herramientas externas).
    op.execute("REVOKE UPDATE, DELETE ON rrhh_horas_extras_historial FROM PUBLIC")

    # ── 4. rrhh_horas_extras_alertas ────────────────────────────────────
    op.create_table(
        "rrhh_horas_extras_alertas",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column(
            "he_id",
            sa.Integer,
            sa.ForeignKey("rrhh_horas_extras.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("tipo", sa.String(40), nullable=False),
        sa.Column(
            "severidad",
            sa.String(10),
            nullable=False,
            server_default="warning",
        ),
        sa.Column("mensaje", sa.Text, nullable=False),
        sa.Column("contexto", postgresql.JSONB, nullable=True),
        sa.Column("leida_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "leida_por_id",
            sa.Integer,
            sa.ForeignKey("usuarios.id"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "severidad IN ('info','warning','critical')",
            name="ck_rrhh_he_alerta_severidad",
        ),
    )
    op.create_index(
        "idx_rrhh_he_alerta_no_leida",
        "rrhh_horas_extras_alertas",
        ["he_id"],
        postgresql_where=sa.text("leida_at IS NULL"),
    )
    op.create_index(
        "idx_rrhh_he_alerta_created",
        "rrhh_horas_extras_alertas",
        ["created_at"],
    )

    # ── 5. Permisos (catálogo + asignación a roles base) ────────────────
    # Usamos bindparams para evitar interpolación SQL (regla del proyecto).
    conn = op.get_bind()
    insert_permiso = sa.text(
        "INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, "
        "                      es_critico, created_at) "
        "VALUES (:codigo, :nombre, :descripcion, :categoria, :orden, "
        "        :es_critico, NOW()) "
        "ON CONFLICT (codigo) DO NOTHING"
    )
    for codigo, nombre, desc, cat, orden, critico in PERMISOS_HE:
        conn.execute(
            insert_permiso,
            {
                "codigo": codigo,
                "nombre": nombre,
                "descripcion": desc,
                "categoria": cat,
                "orden": orden,
                "es_critico": critico,
            },
        )

    insert_rol_permiso = sa.text(
        "INSERT INTO roles_permisos_base (rol_id, permiso_id) "
        "SELECT r.id, p.id FROM roles r CROSS JOIN permisos p "
        "WHERE r.codigo = :rol AND p.codigo = :codigo "
        "ON CONFLICT DO NOTHING"
    )
    for rol, codigos in ROL_PERMISOS.items():
        for codigo in codigos:
            conn.execute(insert_rol_permiso, {"rol": rol, "codigo": codigo})


def downgrade() -> None:
    # ── 1. Limpiar permisos asignados + catálogo ────────────────────────
    codigos = [p[0] for p in PERMISOS_HE]
    conn = op.get_bind()

    delete_rol_permisos = sa.text(
        "DELETE FROM roles_permisos_base WHERE permiso_id IN (SELECT id FROM permisos WHERE codigo IN :codigos)"
    ).bindparams(sa.bindparam("codigos", expanding=True))
    delete_user_overrides = sa.text(
        "DELETE FROM usuarios_permisos_override WHERE permiso_id IN (SELECT id FROM permisos WHERE codigo IN :codigos)"
    ).bindparams(sa.bindparam("codigos", expanding=True))
    delete_permisos = sa.text("DELETE FROM permisos WHERE codigo IN :codigos").bindparams(
        sa.bindparam("codigos", expanding=True)
    )

    conn.execute(delete_rol_permisos, {"codigos": codigos})
    conn.execute(delete_user_overrides, {"codigos": codigos})
    conn.execute(delete_permisos, {"codigos": codigos})

    # ── 2. Drop tablas en orden inverso de FK ───────────────────────────
    op.drop_index(
        "idx_rrhh_he_alerta_created",
        table_name="rrhh_horas_extras_alertas",
    )
    op.drop_index(
        "idx_rrhh_he_alerta_no_leida",
        table_name="rrhh_horas_extras_alertas",
    )
    op.drop_table("rrhh_horas_extras_alertas")

    op.drop_index(
        "idx_rrhh_he_hist_accion",
        table_name="rrhh_horas_extras_historial",
    )
    op.drop_index(
        "idx_rrhh_he_hist_he_created",
        table_name="rrhh_horas_extras_historial",
    )
    op.drop_table("rrhh_horas_extras_historial")

    op.drop_index("idx_rrhh_he_liquidacion", table_name="rrhh_horas_extras")
    op.drop_index("idx_rrhh_he_emp_fecha_estado", table_name="rrhh_horas_extras")
    op.drop_index("idx_rrhh_he_fecha_estado", table_name="rrhh_horas_extras")
    op.drop_index("idx_rrhh_he_empleado_fecha", table_name="rrhh_horas_extras")
    op.drop_table("rrhh_horas_extras")

    # Singleton config: la fila se elimina junto con el drop_table.
    op.drop_table("rrhh_horas_extras_config")
