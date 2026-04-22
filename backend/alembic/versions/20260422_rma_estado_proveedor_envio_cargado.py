"""RMA: add 'Envío cargado' + 'Entregado a proveedor' + update colors

Revision ID: 20260422_rma_estado_prov_envio
Revises: compras_023_extend_adjuntos_nc
Create Date: 2026-04-22

Adds two new estado_proveedor options:
- 'Envío cargado' (blue) — auto-set when envío is created from RMA
- 'Entregado a proveedor' (green) — auto-set when depósito marks delivered

Updates existing colors to follow universal shipment status pattern:
- Pendiente de envío  → gray  (not started)
- Envío cargado       → blue  (loaded into system)
- Enviado a proveedor → orange (in transit)
- Entregado a proveedor → green (confirmed delivery)
- En revisión proveedor → yellow (awaiting response)
- NC recibida         → green  (positive resolution)
- Rechazado por proveedor → red (negative resolution)
- Producto reemplazado → teal  (alternative resolution)
"""

from alembic import op
from sqlalchemy import text

revision = "20260422_rma_estado_prov_envio"
down_revision = "compras_023_extend_adjuntos_nc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Insert new options
    conn.execute(
        text(
            "INSERT INTO rma_seguimiento_opciones (categoria, valor, orden, activo, color) "
            "VALUES (:cat, :val, :orden, true, :color) "
            "ON CONFLICT (categoria, valor) DO NOTHING"
        ),
        {"cat": "estado_proveedor", "val": "Envío cargado", "orden": 2, "color": "blue"},
    )
    conn.execute(
        text(
            "INSERT INTO rma_seguimiento_opciones (categoria, valor, orden, activo, color) "
            "VALUES (:cat, :val, :orden, true, :color) "
            "ON CONFLICT (categoria, valor) DO NOTHING"
        ),
        {"cat": "estado_proveedor", "val": "Entregado a proveedor", "orden": 4, "color": "green"},
    )

    # 2. Update colors and order of existing options to match universal pattern
    updates = [
        # (valor, new_color, new_orden)
        ("Pendiente de envío", "gray", 1),
        ("Envío cargado", "blue", 2),
        ("Enviado a proveedor", "orange", 3),
        ("Entregado a proveedor", "green", 4),
        ("En revisión proveedor", "yellow", 5),
        ("NC recibida", "green", 6),
        ("Rechazado por proveedor", "red", 7),
        ("Producto reemplazado", "teal", 8),
    ]

    for valor, color, orden in updates:
        conn.execute(
            text(
                "UPDATE rma_seguimiento_opciones "
                "SET color = :color, orden = :orden "
                "WHERE categoria = 'estado_proveedor' AND valor = :valor"
            ),
            {"color": color, "valor": valor, "orden": orden},
        )


def downgrade() -> None:
    conn = op.get_bind()

    # Remove new options
    conn.execute(
        text(
            "DELETE FROM rma_seguimiento_opciones "
            "WHERE categoria = 'estado_proveedor' AND valor IN ('Envío cargado', 'Entregado a proveedor')"
        )
    )

    # Restore original colors and order
    restores = [
        ("Pendiente de envío", "yellow", 1),
        ("Enviado a proveedor", "blue", 2),
        ("En revisión proveedor", "orange", 3),
        ("NC recibida", "green", 4),
        ("Rechazado por proveedor", "red", 5),
        ("Producto reemplazado", "green", 6),
    ]

    for valor, color, orden in restores:
        conn.execute(
            text(
                "UPDATE rma_seguimiento_opciones "
                "SET color = :color, orden = :orden "
                "WHERE categoria = 'estado_proveedor' AND valor = :valor"
            ),
            {"color": color, "valor": valor, "orden": orden},
        )
