"""ventas por fuera operations loaded from GBP's PDF reports + upload/view permissions

Revision ID: 20261118_ventas_fuera_pdf_operaciones
Revises: 20261118_tn_medidas_maestro
Create Date: 2026-11-16

The detailed GBP report creates the ventas por fuera operations (`ventas_fuera_operaciones`, one row per document,
and `ventas_fuera_operacion_lineas`); each upload is kept in `ventas_fuera_pdf_cargas`. Each load scope (company +
salesperson + range) is a row of `ventas_fuera_pdf_alcances` that says which salespeople and dates of it no summary or
no detailed report covers yet (reports of other scopes of the company cover it by parts); the documents of its last summary are kept in `ventas_fuera_pdf_resumen_documentos` to pair with a detailed
report uploaded later. New tables only: the GBP sync
(`ventas_fuera_ml_metricas`) is not touched.

Permissions `ventas_fuera.subir_pdf` and `ventas_fuera.ver_metricas_pdf` go to every role that has
`ventas_fuera.ver_dashboard` (owner's decision); SUPERADMIN gets them implicitly. Downgrade drops the tables and
removes the two permissions with their grants and overrides.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261118_ventas_fuera_pdf_operaciones"
down_revision: Union[str, None] = "20261118_tn_medidas_maestro"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PERMISOS = [
    {
        "codigo": "ventas_fuera.subir_pdf",
        "nombre": "Subir PDFs de ventas por fuera",
        "descripcion": "Cargar los reportes de ventas de GBP (detallado y resumen) que crean las operaciones de "
        "ventas por fuera.",
        "orden": 26,
    },
    {
        "codigo": "ventas_fuera.ver_metricas_pdf",
        "nombre": "Ver métricas de ventas por fuera (PDF)",
        "descripcion": "Ver las operaciones y métricas de ventas por fuera cargadas desde los PDFs de GBP.",
        "orden": 27,
    },
]
ROL_ORIGEN = "ventas_fuera.ver_dashboard"

_INSERT_PERMISO = sa.text("""
    INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico, created_at)
    VALUES (:codigo, :nombre, :descripcion, 'ventas_fuera', :orden, false, NOW())
    ON CONFLICT (codigo) DO NOTHING
""")

_INSERT_ROL_PERMISO = sa.text("""
    INSERT INTO roles_permisos_base (rol_id, permiso_id)
    SELECT origen.rol_id, nuevo.id
    FROM roles_permisos_base origen
    JOIN permisos p_origen ON p_origen.id = origen.permiso_id AND p_origen.codigo = :origen
    CROSS JOIN permisos nuevo
    WHERE nuevo.codigo = :codigo
    ON CONFLICT DO NOTHING
""")

_DELETES = [
    "DELETE FROM roles_permisos_base WHERE permiso_id IN (SELECT id FROM permisos WHERE codigo = :codigo)",
    "DELETE FROM usuarios_permisos_override WHERE permiso_id IN (SELECT id FROM permisos WHERE codigo = :codigo)",
    "DELETE FROM permisos WHERE codigo = :codigo",
]

MONTO = sa.Numeric(18, 2)


def seed_permisos(conn: sa.engine.Connection) -> None:
    for permiso in PERMISOS:
        conn.execute(_INSERT_PERMISO, permiso)
        conn.execute(_INSERT_ROL_PERMISO, {"codigo": permiso["codigo"], "origen": ROL_ORIGEN})


def upgrade() -> None:
    op.create_table(
        "ventas_fuera_pdf_cargas",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("empresa", sa.String(200), nullable=False),
        sa.Column("vendedor", sa.String(200), nullable=True),
        sa.Column("desde", sa.Date(), nullable=False),
        sa.Column("hasta", sa.Date(), nullable=False),
        sa.Column("archivo_detallado", sa.String(255), nullable=True),
        sa.Column("archivo_resumen", sa.String(255), nullable=True),
        sa.Column("documentos", sa.Integer(), nullable=False),
        sa.Column("reemplazados", sa.Integer(), nullable=False),
        sa.Column("avisos", sa.JSON(), nullable=False),
        sa.Column("usuario_id", sa.Integer(), sa.ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_ventas_fuera_pdf_cargas_usuario_id", "ventas_fuera_pdf_cargas", ["usuario_id"])
    op.create_index("ix_ventas_fuera_pdf_cargas_empresa_desde", "ventas_fuera_pdf_cargas", ["empresa", "desde"])

    op.create_table(
        "ventas_fuera_operaciones",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("carga_id", sa.Integer(), sa.ForeignKey("ventas_fuera_pdf_cargas.id"), nullable=False),
        sa.Column("empresa", sa.String(200), nullable=False),
        sa.Column("vendedor", sa.String(100), nullable=False),
        sa.Column("cliente", sa.String(255), nullable=False),
        sa.Column("cliente_codigo", sa.String(50), nullable=True),
        sa.Column("tipo", sa.String(2), nullable=False),
        sa.Column("letra", sa.String(1), nullable=False),
        sa.Column("punto_venta", sa.Integer(), nullable=False),
        sa.Column("numero", sa.Integer(), nullable=False),
        sa.Column("fecha", sa.Date(), nullable=False),
        sa.Column("fecha_vencimiento", sa.Date(), nullable=True),
        sa.Column("condicion_venta", sa.String(100), nullable=True),
        sa.Column("importe", MONTO, nullable=False),
        sa.Column("saldo", MONTO, nullable=False),
        sa.Column("total_lineas", MONTO, nullable=False),
        sa.Column("importe_resumen", MONTO, nullable=True),
        sa.Column("recargo_financiero", MONTO, nullable=False),
        sa.UniqueConstraint(
            "empresa", "tipo", "letra", "punto_venta", "numero", name="uq_ventas_fuera_operaciones_doc"
        ),
    )
    op.create_index("ix_ventas_fuera_operaciones_carga_id", "ventas_fuera_operaciones", ["carga_id"])
    op.create_index("ix_ventas_fuera_operaciones_empresa_fecha", "ventas_fuera_operaciones", ["empresa", "fecha"])

    op.create_table(
        "ventas_fuera_operacion_lineas",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "operacion_id",
            sa.Integer(),
            sa.ForeignKey("ventas_fuera_operaciones.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("renglon", sa.Integer(), nullable=False),
        sa.Column("codigo", sa.String(100), nullable=True),
        sa.Column("articulo", sa.String(255), nullable=False),
        sa.Column("cantidad", MONTO, nullable=False),
        sa.Column("moneda", sa.String(3), nullable=False),
        sa.Column("precio", MONTO, nullable=False),
        sa.Column("precio_costo", MONTO, nullable=False),
        sa.Column("precio_costo_pp", MONTO, nullable=False),
    )
    op.create_index("ix_ventas_fuera_operacion_lineas_operacion_id", "ventas_fuera_operacion_lineas", ["operacion_id"])
    op.create_index("ix_ventas_fuera_operacion_lineas_codigo", "ventas_fuera_operacion_lineas", ["codigo"])

    op.create_table(
        "ventas_fuera_pdf_alcances",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("empresa", sa.String(200), nullable=False),
        sa.Column("vendedor", sa.String(200), nullable=True),
        sa.Column("desde", sa.Date(), nullable=False),
        sa.Column("hasta", sa.Date(), nullable=False),
        sa.Column("detallada_carga_id", sa.Integer(), sa.ForeignKey("ventas_fuera_pdf_cargas.id"), nullable=True),
        sa.Column("resumen_carga_id", sa.Integer(), sa.ForeignKey("ventas_fuera_pdf_cargas.id"), nullable=True),
        sa.Column("resumen_con_impuestos", sa.Boolean(), nullable=True),
        # What no report of the other kind covers: [{"reporte", "vendedor", "desde", "hasta"}] (owner, L11).
        sa.Column("faltantes", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("avisos", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "uq_ventas_fuera_pdf_alcances_scope",
        "ventas_fuera_pdf_alcances",
        ["empresa", sa.text("coalesce(vendedor, '')"), "desde", "hasta"],
        unique=True,
    )

    op.create_table(
        "ventas_fuera_pdf_resumen_documentos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "alcance_id",
            sa.Integer(),
            sa.ForeignKey("ventas_fuera_pdf_alcances.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("cliente_codigo", sa.String(50), nullable=True),
        sa.Column("cliente", sa.String(255), nullable=False),
        sa.Column("tipo", sa.String(2), nullable=False),
        sa.Column("letra", sa.String(1), nullable=False),
        sa.Column("punto_venta", sa.Integer(), nullable=False),
        sa.Column("numero", sa.Integer(), nullable=False),
        sa.Column("fecha", sa.Date(), nullable=False),
        sa.Column("fecha_vencimiento", sa.Date(), nullable=True),
        sa.Column("vendedor", sa.String(100), nullable=False),
        sa.Column("condicion_venta", sa.String(100), nullable=False),
        sa.Column("importe", MONTO, nullable=False),
        sa.Column("saldo", MONTO, nullable=False),
    )
    op.create_index(
        "ix_ventas_fuera_pdf_resumen_documentos_alcance_id", "ventas_fuera_pdf_resumen_documentos", ["alcance_id"]
    )

    seed_permisos(op.get_bind())


def downgrade() -> None:
    conn = op.get_bind()
    for permiso in PERMISOS:
        for statement in _DELETES:
            conn.execute(sa.text(statement), {"codigo": permiso["codigo"]})
    op.drop_table("ventas_fuera_pdf_resumen_documentos")
    op.drop_table("ventas_fuera_pdf_alcances")
    op.drop_table("ventas_fuera_operacion_lineas")
    op.drop_table("ventas_fuera_operaciones")
    op.drop_table("ventas_fuera_pdf_cargas")
