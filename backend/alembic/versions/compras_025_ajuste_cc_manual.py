"""compras 025 — seed permiso administracion.ajustar_cc_proveedor_manual

Revision ID: compras_025_permiso_ajuste_cc_manual
Revises: compras_024_op_estado_cancelado
Create Date: 2026-04-24

Permiso crítico para hacer ajustes manuales sobre la CC de un proveedor
desde el tab CC Proveedores (sub-batch 5.H). Es un "override" fuerte del
libro mayor: agrega un movimiento `tipo='ajuste'` sin origen natural
(OP, factura, NC). No revierte nada, solo INSERT append-only.

Casos de uso legítimos:
  - Asentar un pago/cobro que nunca pasó por OP/factura (ej: compensación
    con proveedor externa al sistema).
  - Corregir un saldo histórico después de migración de datos.
  - Registrar notas de débito/crédito que no tienen documento respaldo.

NO se asigna a ningún rol base ni usuario por default. El admin lo da
a quien corresponda. Es crítico porque modifica directamente la posición
de CC sin validación cruzada con pedidos/OPs/imputaciones.

Orden relativo (continuación del módulo compras):
  170 = aprobar_ordenes_compra
  171 = ejecutar_pagos
  172 = eliminar_compras_basura
  173 = ajustar_monto_pedido
  174 = aprobar_ncs_locales
  175 = ajustar_cc_proveedor_manual  ← éste
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "compras_025_ajuste_cc_manual"
down_revision: Union[str, None] = "compras_024_op_estado_cancelado"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_ORDEN_AJUSTE_CC_MANUAL: int = 175
_CATEGORIA: str = "administracion_sector"

_PERMISO: dict = {
    "codigo": "administracion.ajustar_cc_proveedor_manual",
    "nombre": "Ajustar CC de proveedor manualmente",
    "descripcion": (
        "Permite insertar un ajuste manual (debe/haber) en la cuenta "
        "corriente de un proveedor desde el tab CC Proveedores. Es un "
        "override directo del libro mayor sin OP/factura/NC de respaldo, "
        "append-only (no modifica movimientos existentes). Uso crítico: "
        "asentar compensaciones externas o corregir saldos históricos. "
        "NO se asigna por default."
    ),
    "categoria": _CATEGORIA,
    "orden": _ORDEN_AJUSTE_CC_MANUAL,
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
