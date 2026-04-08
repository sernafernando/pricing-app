"""Seed caja permissions, default categories, and document types

Inserts:
- 3 permissions: administracion.ver_caja, gestionar_caja, sincronizar_caja
- 8 default movement categories
- 8 default document types

Revision ID: 20260408_caja_seed
Revises: 20260408_caja
Create Date: 2026-04-08
"""

import sqlalchemy as sa
from alembic import op

revision = "20260408_caja_seed"
down_revision = "20260408_caja"
branch_labels = None
depends_on = None

# Tables we need to reference
permisos = sa.table(
    "permisos",
    sa.column("id", sa.Integer),
    sa.column("codigo", sa.String),
    sa.column("nombre", sa.String),
    sa.column("descripcion", sa.Text),
    sa.column("categoria", sa.String),
    sa.column("orden", sa.Integer),
    sa.column("es_critico", sa.Boolean),
)

caja_categorias = sa.table(
    "caja_categorias",
    sa.column("nombre", sa.String),
    sa.column("tipo_aplicable", sa.String),
)

caja_tipo_documentos = sa.table(
    "caja_tipo_documentos",
    sa.column("nombre", sa.String),
    sa.column("descripcion", sa.Text),
)


def upgrade() -> None:
    # ── Permissions ───────────────────────────────────────────────
    op.bulk_insert(
        permisos,
        [
            {
                "codigo": "administracion.ver_caja",
                "nombre": "Ver caja",
                "descripcion": "Acceso de lectura a cajas, movimientos, documentos y archivos",
                "categoria": "administracion_sector",
                "orden": 157,
                "es_critico": False,
            },
            {
                "codigo": "administracion.gestionar_caja",
                "nombre": "Gestionar caja",
                "descripcion": "Crear/editar cajas, registrar movimientos, gestionar categorías, documentos y archivos",
                "categoria": "administracion_sector",
                "orden": 158,
                "es_critico": False,
            },
            {
                "codigo": "administracion.sincronizar_caja",
                "nombre": "Sincronizar caja desde Google Sheets",
                "descripcion": "Ejecutar importación masiva de movimientos desde Google Sheets",
                "categoria": "administracion_sector",
                "orden": 159,
                "es_critico": True,
            },
        ],
    )

    # ── Default Categories (8) ────────────────────────────────────
    op.bulk_insert(
        caja_categorias,
        [
            {"nombre": "Gasto", "tipo_aplicable": "egreso"},
            {"nombre": "Sueldos", "tipo_aplicable": "egreso"},
            {"nombre": "Ingreso Venta", "tipo_aplicable": "ingreso"},
            {"nombre": "Proveedor", "tipo_aplicable": "egreso"},
            {"nombre": "Retiro", "tipo_aplicable": "egreso"},
            {"nombre": "Préstamo", "tipo_aplicable": "ambos"},
            {"nombre": "Servicios", "tipo_aplicable": "egreso"},
            {"nombre": "Impuestos", "tipo_aplicable": "egreso"},
        ],
    )

    # ── Default Document Types (8) ────────────────────────────────
    op.bulk_insert(
        caja_tipo_documentos,
        [
            {"nombre": "Factura Proveedor", "descripcion": "Facturas recibidas de proveedores"},
            {"nombre": "Factura Emitida", "descripcion": "Facturas emitidas a clientes"},
            {"nombre": "Recibo", "descripcion": "Recibos de pago"},
            {"nombre": "Ticket/Voucher", "descripcion": "Tickets y vouchers de compra"},
            {"nombre": "Nota de Crédito", "descripcion": "Notas de crédito recibidas o emitidas"},
            {"nombre": "Nota de Débito", "descripcion": "Notas de débito recibidas o emitidas"},
            {"nombre": "Comprobante de Gasto", "descripcion": "Comprobantes de gastos varios"},
            {"nombre": "Otro", "descripcion": "Otros documentos no clasificados"},
        ],
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "DELETE FROM permisos WHERE codigo IN "
            "('administracion.ver_caja', 'administracion.gestionar_caja', 'administracion.sincronizar_caja')"
        )
    )
    conn.execute(
        sa.text(
            "DELETE FROM caja_categorias WHERE nombre IN "
            "('Gasto', 'Sueldos', 'Ingreso Venta', 'Proveedor', 'Retiro', 'Préstamo', 'Servicios', 'Impuestos')"
        )
    )
    conn.execute(
        sa.text(
            "DELETE FROM caja_tipo_documentos WHERE nombre IN "
            "('Factura Proveedor', 'Factura Emitida', 'Recibo', 'Ticket/Voucher', "
            "'Nota de Crédito', 'Nota de Débito', 'Comprobante de Gasto', 'Otro')"
        )
    )
