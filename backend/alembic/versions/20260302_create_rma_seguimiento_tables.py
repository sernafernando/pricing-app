"""Crear tablas del módulo RMA Seguimiento

4 tablas nuevas para el sistema de seguimiento de RMA:
- rma_seguimiento_opciones: dropdowns configurables desde admin
- rma_casos: header del caso (1 caso = 1 cliente/pedido)
- rma_caso_items: artículos dentro del caso con ciclo de vida propio
- rma_caso_historial: auditoría de cambios campo por campo

Revision ID: 20260302_rma_seg
Revises: 20260227_pist_asigna
Create Date: 2026-03-02

"""

from alembic import op
import sqlalchemy as sa

revision = "20260302_rma_seg"
down_revision = "20260227_pist_asigna"
branch_labels = None
depends_on = None


def upgrade():
    # ── 1. Opciones configurables para dropdowns ──
    op.create_table(
        "rma_seguimiento_opciones",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("categoria", sa.String(50), nullable=False),
        sa.Column("valor", sa.String(200), nullable=False),
        sa.Column("orden", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("activo", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("color", sa.String(20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("categoria", "valor", name="uq_rma_opcion_categoria_valor"),
    )
    op.create_index("idx_rma_opciones_categoria", "rma_seguimiento_opciones", ["categoria"])

    # ── 2. Casos RMA (header) ──
    op.create_table(
        "rma_casos",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("numero_caso", sa.String(20), unique=True, nullable=False),
        # Cliente
        sa.Column("cust_id", sa.BigInteger(), nullable=True),
        sa.Column("cliente_nombre", sa.String(255), nullable=True),
        sa.Column("cliente_dni", sa.String(20), nullable=True),
        sa.Column("cliente_numero", sa.Integer(), nullable=True),
        # Pedido
        sa.Column("ml_id", sa.String(50), nullable=True),
        sa.Column("origen", sa.String(50), nullable=True),
        sa.Column("estado", sa.String(50), nullable=False, server_default="abierto"),
        # Flag de proceso (transporte → "BORRAR PEDIDO" en ERP)
        sa.Column("marcado_borrar_pedido", sa.Boolean(), nullable=True),
        # Reclamo ML
        sa.Column(
            "estado_reclamo_ml_id",
            sa.Integer(),
            sa.ForeignKey("rma_seguimiento_opciones.id"),
            nullable=True,
        ),
        sa.Column(
            "cobertura_ml_id",
            sa.Integer(),
            sa.ForeignKey("rma_seguimiento_opciones.id"),
            nullable=True,
        ),
        sa.Column("monto_cubierto", sa.Numeric(15, 2), nullable=True),
        # Observaciones
        sa.Column("observaciones", sa.Text(), nullable=True),
        # Auditoría
        sa.Column("corroborar_nc", sa.String(100), nullable=True),
        sa.Column("fecha_caso", sa.Date(), nullable=True),
        # Sistema
        sa.Column(
            "creado_por_id",
            sa.Integer(),
            sa.ForeignKey("usuarios.id"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_rma_casos_numero", "rma_casos", ["numero_caso"])
    op.create_index("idx_rma_casos_cust_id", "rma_casos", ["cust_id"])
    op.create_index("idx_rma_casos_ml_id", "rma_casos", ["ml_id"])
    op.create_index("idx_rma_casos_estado", "rma_casos", ["estado"])
    op.create_index("idx_rma_casos_estado_reclamo", "rma_casos", ["estado_reclamo_ml_id"])
    op.create_index("idx_rma_casos_cobertura_ml", "rma_casos", ["cobertura_ml_id"])
    op.create_index("idx_rma_casos_creado_por", "rma_casos", ["creado_por_id"])

    # ── 3. Items del caso (detalle por artículo) ──
    op.create_table(
        "rma_caso_items",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "caso_id",
            sa.Integer(),
            sa.ForeignKey("rma_casos.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Datos artículo
        sa.Column("serial_number", sa.String(100), nullable=True),
        sa.Column("item_id", sa.BigInteger(), nullable=True),
        sa.Column("is_id", sa.BigInteger(), nullable=True),
        sa.Column("it_transaction", sa.BigInteger(), nullable=True),
        sa.Column("ean", sa.String(50), nullable=True),
        sa.Column("producto_desc", sa.String(500), nullable=True),
        sa.Column("precio", sa.Numeric(15, 2), nullable=True),
        sa.Column("estado_facturacion", sa.String(50), nullable=True),
        sa.Column("link_ml", sa.String(500), nullable=True),
        # Recepción
        sa.Column(
            "estado_recepcion_id",
            sa.Integer(),
            sa.ForeignKey("rma_seguimiento_opciones.id"),
            nullable=True,
        ),
        sa.Column("costo_envio", sa.Numeric(15, 2), nullable=True),
        sa.Column(
            "causa_devolucion_id",
            sa.Integer(),
            sa.ForeignKey("rma_seguimiento_opciones.id"),
            nullable=True,
        ),
        sa.Column(
            "recepcion_usuario_id",
            sa.Integer(),
            sa.ForeignKey("usuarios.id"),
            nullable=True,
        ),
        sa.Column("recepcion_fecha", sa.DateTime(timezone=True), nullable=True),
        # Revisión
        sa.Column(
            "apto_venta_id",
            sa.Integer(),
            sa.ForeignKey("rma_seguimiento_opciones.id"),
            nullable=True,
        ),
        sa.Column("requirio_reacondicionamiento", sa.Boolean(), nullable=True),
        sa.Column(
            "estado_revision_id",
            sa.Integer(),
            sa.ForeignKey("rma_seguimiento_opciones.id"),
            nullable=True,
        ),
        sa.Column(
            "revision_usuario_id",
            sa.Integer(),
            sa.ForeignKey("usuarios.id"),
            nullable=True,
        ),
        sa.Column("revision_fecha", sa.DateTime(timezone=True), nullable=True),
        # Proceso interno
        sa.Column(
            "estado_proceso_id",
            sa.Integer(),
            sa.ForeignKey("rma_seguimiento_opciones.id"),
            nullable=True,
        ),
        sa.Column(
            "deposito_destino_id",
            sa.Integer(),
            sa.ForeignKey("rma_seguimiento_opciones.id"),
            nullable=True,
        ),
        sa.Column("enviado_fisicamente_deposito", sa.Boolean(), nullable=True),
        sa.Column("corroborar_nc", sa.Boolean(), nullable=True),
        sa.Column("requirio_rma_interno", sa.Boolean(), nullable=True),
        # Devolución parcial
        sa.Column("requiere_nota_credito", sa.Boolean(), nullable=True),
        sa.Column("debe_facturarse", sa.Boolean(), nullable=True),
        # Envío a proveedor
        sa.Column("supp_id", sa.BigInteger(), nullable=True),
        sa.Column("proveedor_nombre", sa.String(255), nullable=True),
        sa.Column("enviado_proveedor", sa.Boolean(), nullable=True),
        sa.Column("fecha_envio_proveedor", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fecha_respuesta_proveedor", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "estado_proveedor_id",
            sa.Integer(),
            sa.ForeignKey("rma_seguimiento_opciones.id"),
            nullable=True,
        ),
        sa.Column("nc_proveedor", sa.String(100), nullable=True),
        sa.Column("monto_nc_proveedor", sa.Numeric(15, 2), nullable=True),
        # Observaciones por artículo
        sa.Column("observaciones", sa.Text(), nullable=True),
        # Vinculación ERP
        sa.Column("rmah_id", sa.BigInteger(), nullable=True),
        sa.Column("rmad_id", sa.BigInteger(), nullable=True),
        # Sistema
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_rma_items_caso", "rma_caso_items", ["caso_id"])
    op.create_index("idx_rma_items_serial", "rma_caso_items", ["serial_number"])
    op.create_index("idx_rma_items_item_id", "rma_caso_items", ["item_id"])
    op.create_index("idx_rma_items_estado_recep", "rma_caso_items", ["estado_recepcion_id"])
    op.create_index("idx_rma_items_causa_dev", "rma_caso_items", ["causa_devolucion_id"])
    op.create_index("idx_rma_items_apto_venta", "rma_caso_items", ["apto_venta_id"])
    op.create_index("idx_rma_items_estado_rev", "rma_caso_items", ["estado_revision_id"])
    op.create_index("idx_rma_items_estado_proc", "rma_caso_items", ["estado_proceso_id"])
    op.create_index("idx_rma_items_deposito_dest", "rma_caso_items", ["deposito_destino_id"])
    op.create_index("idx_rma_items_supp_id", "rma_caso_items", ["supp_id"])
    op.create_index("idx_rma_items_estado_prov", "rma_caso_items", ["estado_proveedor_id"])

    # ── 4. Historial de cambios (auditoría) ──
    op.create_table(
        "rma_caso_historial",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "caso_id",
            sa.Integer(),
            sa.ForeignKey("rma_casos.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "caso_item_id",
            sa.Integer(),
            sa.ForeignKey("rma_caso_items.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("campo", sa.String(100), nullable=False),
        sa.Column("valor_anterior", sa.Text(), nullable=True),
        sa.Column("valor_nuevo", sa.Text(), nullable=True),
        sa.Column(
            "usuario_id",
            sa.Integer(),
            sa.ForeignKey("usuarios.id"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_rma_hist_caso", "rma_caso_historial", ["caso_id"])
    op.create_index("idx_rma_hist_item", "rma_caso_historial", ["caso_item_id"])
    op.create_index("idx_rma_hist_usuario", "rma_caso_historial", ["usuario_id"])
    op.create_index("idx_rma_hist_campo", "rma_caso_historial", ["campo"])

    # ── Seed: opciones iniciales de los dropdowns ──
    # Estos valores son editables desde el admin panel del frontend.
    # Solo se cargan una vez como punto de partida.
    rma_opciones = sa.table(
        "rma_seguimiento_opciones",
        sa.column("categoria", sa.String),
        sa.column("valor", sa.String),
        sa.column("orden", sa.Integer),
        sa.column("color", sa.String),
    )

    op.bulk_insert(
        rma_opciones,
        [
            # Estado de recepción
            {"categoria": "estado_recepcion", "valor": "No llegó", "orden": 1, "color": "red"},
            {"categoria": "estado_recepcion", "valor": "Llegó otro producto", "orden": 2, "color": "orange"},
            {"categoria": "estado_recepcion", "valor": "Llegó para revisar", "orden": 3, "color": "yellow"},
            {"categoria": "estado_recepcion", "valor": "Llegó cerrado", "orden": 4, "color": "blue"},
            # Causa de devolución
            {"categoria": "causa_devolucion", "valor": "Arrepentimiento de compra", "orden": 1, "color": "blue"},
            {"categoria": "causa_devolucion", "valor": "Le llegó otro producto", "orden": 2, "color": "orange"},
            {"categoria": "causa_devolucion", "valor": "Fallado", "orden": 3, "color": "red"},
            {"categoria": "causa_devolucion", "valor": "Cancelada", "orden": 4, "color": "gray"},
            {"categoria": "causa_devolucion", "valor": "No le llegó / Llegó Vacío / Llegó Roto", "orden": 5, "color": "red"},
            # Apto para la venta
            {"categoria": "apto_venta", "valor": "Nuevo", "orden": 1, "color": "green"},
            {"categoria": "apto_venta", "valor": "Sí, pero con detalles", "orden": 2, "color": "yellow"},
            {"categoria": "apto_venta", "valor": "Outlet", "orden": 3, "color": "orange"},
            {"categoria": "apto_venta", "valor": "Scrap", "orden": 4, "color": "red"},
            {"categoria": "apto_venta", "valor": "A Proveedor", "orden": 5, "color": "purple"},
            {"categoria": "apto_venta", "valor": "Garantía", "orden": 6, "color": "blue"},
            {"categoria": "apto_venta", "valor": "Garantía finalizada", "orden": 7, "color": "gray"},
            {"categoria": "apto_venta", "valor": "Full", "orden": 8, "color": "green"},
            # Estado de revisión
            {"categoria": "estado_revision", "valor": "RMA y Cambio", "orden": 1, "color": "blue"},
            {"categoria": "estado_revision", "valor": "Garantía", "orden": 2, "color": "purple"},
            {"categoria": "estado_revision", "valor": "Sin garantía", "orden": 3, "color": "gray"},
            {"categoria": "estado_revision", "valor": "Reacondicionado", "orden": 4, "color": "yellow"},
            # Estado del reclamo ML
            {"categoria": "estado_reclamo_ml", "valor": "Abierto", "orden": 1, "color": "yellow"},
            {"categoria": "estado_reclamo_ml", "valor": "Reintegro al comprador", "orden": 2, "color": "red"},
            {"categoria": "estado_reclamo_ml", "valor": "Reintegro a nosotros", "orden": 3, "color": "green"},
            {"categoria": "estado_reclamo_ml", "valor": "Reintegro a Ambos", "orden": 4, "color": "orange"},
            # Cobertura ML
            {"categoria": "cobertura_ml", "valor": "No aplica", "orden": 1, "color": "gray"},
            {"categoria": "cobertura_ml", "valor": "Total", "orden": 2, "color": "green"},
            {"categoria": "cobertura_ml", "valor": "Parcial", "orden": 3, "color": "yellow"},
            {"categoria": "cobertura_ml", "valor": "Nada", "orden": 4, "color": "red"},
            {"categoria": "cobertura_ml", "valor": "Envío", "orden": 5, "color": "blue"},
            # Estado del proceso interno
            {"categoria": "estado_proceso", "valor": "Falta procesar", "orden": 1, "color": "yellow"},
            {"categoria": "estado_proceso", "valor": "Se hizo RMA", "orden": 2, "color": "blue"},
            {"categoria": "estado_proceso", "valor": "Se hizo RMA y NC", "orden": 3, "color": "green"},
            {"categoria": "estado_proceso", "valor": "RMA y Cambio", "orden": 4, "color": "purple"},
            {"categoria": "estado_proceso", "valor": "RMA Cerrado", "orden": 5, "color": "gray"},
            {"categoria": "estado_proceso", "valor": "No pasa por ERP", "orden": 6, "color": "orange"},
            # Depósito destino
            {"categoria": "deposito_destino", "valor": "Se devolvió al cliente", "orden": 99, "color": "blue"},
            # Estado proveedor
            {"categoria": "estado_proveedor", "valor": "Pendiente de envío", "orden": 1, "color": "yellow"},
            {"categoria": "estado_proveedor", "valor": "Enviado a proveedor", "orden": 2, "color": "blue"},
            {"categoria": "estado_proveedor", "valor": "En revisión proveedor", "orden": 3, "color": "orange"},
            {"categoria": "estado_proveedor", "valor": "NC recibida", "orden": 4, "color": "green"},
            {"categoria": "estado_proveedor", "valor": "Rechazado por proveedor", "orden": 5, "color": "red"},
            {"categoria": "estado_proveedor", "valor": "Producto reemplazado", "orden": 6, "color": "green"},
        ],
    )


def downgrade():
    op.drop_table("rma_caso_historial")
    op.drop_table("rma_caso_items")
    op.drop_table("rma_casos")
    op.drop_table("rma_seguimiento_opciones")
