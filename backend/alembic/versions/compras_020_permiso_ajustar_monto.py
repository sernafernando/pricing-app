"""compras 020 — seed permiso administracion.ajustar_monto_pedido

Revision ID: compras_020_ajustar_monto
Revises: compras_019_adjuntos
Create Date: 2026-04-22

Inserta el permiso crítico `administracion.ajustar_monto_pedido`, requerido
para ajustar el monto de un pedido al valor de una factura del ERP (flujo
manual del modal "Vincular factura"). El ajuste genera un movimiento nuevo
en `cc_proveedor_movimientos` (append-only), y queda registrado en
`compras_eventos` con payload `{monto_anterior, monto_nuevo, diferencia,
ct_transaction, motivo}`.

IMPORTANTE: NO se asigna a ningún rol base ni usuario por default. Es un
permiso destructivo (modifica plata) que el admin decide manualmente a
quién dárselo.

Orden relativo: continúa después de:
  170 = aprobar_ordenes_compra
  171 = ejecutar_pagos
  172 = eliminar_compras_basura
  173 = ajustar_monto_pedido   ← éste
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "compras_020_ajustar_monto"
down_revision: Union[str, None] = "compras_019_adjuntos"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_ORDEN_AJUSTAR: int = 173
_CATEGORIA: str = "administracion_sector"

_PERMISO: dict = {
    "codigo": "administracion.ajustar_monto_pedido",
    "nombre": "Ajustar monto de pedido con factura ERP",
    "descripcion": (
        "Permite modificar el monto de un pedido de compra al vincularlo con "
        "una factura del ERP cuyo total difiere. El ajuste se materializa como "
        "un movimiento nuevo en cuenta corriente del proveedor (append-only). "
        "NO revierte imputaciones previas. Requiere motivo obligatorio."
    ),
    "categoria": _CATEGORIA,
    "orden": _ORDEN_AJUSTAR,
    "es_critico": True,
}


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
        _PERMISO,
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text("DELETE FROM permisos WHERE codigo = :codigo"),
        {"codigo": _PERMISO["codigo"]},
    )
