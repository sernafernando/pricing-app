"""
wipe_compras_service — herramienta de testing para limpiar el módulo compras.

ADVERTENCIA: Este servicio ejecuta DELETE destructivos sobre tablas del módulo
compras. Solo debe usarse en entornos de prueba. Nunca en producción con datos
reales.

Las tablas se borran en orden FK-safe (hijos antes que padres):
  - compras_papelera, compras_adjuntos → solo referencian usuarios/empresas/proveedores,
    sin FKs hacia otras tablas del módulo.
  - cc_reconciliacion_log, compras_eventos, imputaciones, cc_proveedor_movimientos
    → hijos que no tienen FKs salientes a ordenes_pago, pedidos, etc.
  - ordenes_pago → debe ir antes de caja/banco porque tiene FK RESTRICT a esas tablas.
  - notas_credito_local → tabla de documentos; sin hijos en el módulo compras.
  - pedidos_compra → tabla cabecera; va al final del bloque compras.
  - caja_documentos, caja_movimientos, banco_movimientos → últimas, ya sin hijos.

NOTA: etiquetas_envio NO se incluye aquí. Es una tabla compartida entre módulos:
rma_caso_items referencia etiquetas_envio via FK (fk_rma_item_shipping_id). Borrarla
en el wipe de compras provoca IntegrityError cuando existen ítems RMA apuntando a esas
etiquetas. pedidos_compra tiene FK hacia etiquetas_envio pero en dirección saliente,
por lo que eliminar pedidos_compra no requiere tocar etiquetas_envio.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.logging import get_logger

logger = get_logger("services.wipe_compras")

# Orden FK-safe: hijos antes que padres.
# - compras_papelera y compras_adjuntos solo referencian usuarios/empresas/proveedores,
#   sin FKs hacia tablas internas del módulo → van primero, sin restricción.
# - ordenes_pago referencia caja_movimientos/caja_documentos/banco_movimientos con RESTRICT,
#   por eso va ANTES de las tablas de caja/banco.
# - etiquetas_envio fue removida: es tabla compartida con el módulo RMA
#   (rma_caso_items → etiquetas_envio via FK RESTRICT). Incluirla aquí provoca
#   IntegrityError cuando hay ítems RMA apuntando a esas etiquetas. La FK de
#   pedidos_compra hacia etiquetas_envio es saliente, así que borrar pedidos_compra
#   no requiere tocar etiquetas_envio.
TABLAS_COMPRAS_SIEMPRE = [
    "compras_papelera",
    "compras_adjuntos",
    "cc_reconciliacion_log",
    "compras_eventos",
    "imputaciones",
    "cc_proveedor_movimientos",
    "ordenes_pago",
    "notas_credito_local",
    "pedidos_compra",
]

TABLAS_CAJA_BANCO = [
    "caja_documentos",
    "caja_movimientos",
    "banco_movimientos",
]


def wipe_compras(session: Session, *, incluir_caja_banco: bool) -> dict[str, int]:
    """
    Elimina todos los datos del módulo compras.

    Ejecuta DELETE FROM en orden FK-safe sobre las tablas del módulo compras.
    Si `incluir_caja_banco` es True, también limpia caja_documentos,
    caja_movimientos y banco_movimientos (DESPUÉS de ordenes_pago).

    Returns:
        dict con nombre de tabla → cantidad de filas eliminadas.

    Raises:
        Exception: re-levanta cualquier error de base de datos para que el caller
                   pueda hacer rollback y reportar el fallo con precisión.
    """
    tablas = list(TABLAS_COMPRAS_SIEMPRE)
    if incluir_caja_banco:
        tablas = tablas + list(TABLAS_CAJA_BANCO)

    resultado: dict[str, int] = {}

    for tabla in tablas:
        row = session.execute(text(f"DELETE FROM {tabla}"))  # noqa: S608
        filas = row.rowcount if row.rowcount is not None else 0
        resultado[tabla] = filas
        logger.warning("wipe_compras: DELETE FROM %s → %d filas", tabla, filas)

    logger.warning(
        "wipe_compras COMPLETADO. incluir_caja_banco=%s. Tablas: %s",
        incluir_caja_banco,
        resultado,
    )
    return resultado
