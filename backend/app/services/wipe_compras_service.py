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
  - dinero_a_cuenta → leaf table; origen_op_id → ordenes_pago.id (RESTRICT). Debe ir
    ANTES de ordenes_pago para evitar ForeignKeyViolation al borrar OPs.
  - ordenes_pago → debe ir antes de caja/banco porque tiene FK RESTRICT a esas tablas.
  - notas_credito_local → tabla de documentos; sin hijos en el módulo compras.
  - pedidos_compra → tabla cabecera; va al final del bloque compras.
  - caja_documentos, caja_movimientos, banco_movimientos → últimas, ya sin hijos.

NOTA sobre etiquetas_envio: es una tabla COMPARTIDA entre módulos. No se borra aquí por
dos razones:
  1. rma_caso_items referencia etiquetas_envio via FK (fk_rma_item_shipping_id) con RESTRICT.
  2. etiquetas_envio.pedido_compra_id → pedidos_compra.id es una FK ENTRANTE con ondelete=RESTRICT.
     Borrar pedidos_compra sin deshacer esta referencia provoca IntegrityError.
Solución: antes de DELETE FROM pedidos_compra, el wipe ejecuta un UPDATE no destructivo que
desvincula las etiquetas de retiro de proveedor (tipo_envio → 'cliente', fks compras → NULL).
Las filas etiqueta_envio sobreviven intactas; solo se limpia el vínculo a compras.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.logging import get_logger

logger = get_logger("services.wipe_compras")

# Orden FK-safe: hijos antes que padres.
# - compras_papelera y compras_adjuntos solo referencian usuarios/empresas/proveedores,
#   sin FKs hacia tablas internas del módulo → van primero, sin restricción.
# - dinero_a_cuenta: origen_op_id → ordenes_pago.id con ondelete=RESTRICT. Es leaf
#   (ninguna tabla la referencia). Debe ir ANTES de ordenes_pago.
# - ordenes_pago referencia caja_movimientos/caja_documentos/banco_movimientos con RESTRICT,
#   por eso va ANTES de las tablas de caja/banco.
# - pedidos_compra: antes de su DELETE se ejecuta un UPDATE no destructivo sobre
#   etiquetas_envio para deshacer la FK RESTRICT entrante (ver wipe_compras).
#   etiquetas_envio NO se borra (tabla compartida con RMA).
TABLAS_COMPRAS_SIEMPRE = [
    "compras_papelera",
    "compras_adjuntos",
    "cc_reconciliacion_log",
    "compras_eventos",
    "imputaciones",
    "cc_proveedor_movimientos",
    "dinero_a_cuenta",
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

    # Desvincular etiquetas_envio de compras ANTES de borrar pedidos_compra.
    # etiquetas_envio.pedido_compra_id → pedidos_compra.id tiene ondelete=RESTRICT,
    # por lo que el DELETE FROM pedidos_compra fallaría si hay etiquetas vinculadas.
    # La tabla es compartida con RMA (rma_caso_items → etiquetas_envio via RESTRICT),
    # por lo que NO se borra — solo se limpia el vínculo de retiro de proveedor:
    # tipo_envio vuelve a 'cliente' y las FKs de compras quedan en NULL.
    unlink_result = session.execute(
        text(
            "UPDATE etiquetas_envio "
            "SET tipo_envio = 'cliente', "
            "    proveedor_id = NULL, "
            "    proveedor_direccion_id = NULL, "
            "    pedido_compra_id = NULL "
            "WHERE pedido_compra_id IS NOT NULL"
        )
    )
    etiquetas_desvinculadas = unlink_result.rowcount if unlink_result.rowcount is not None else 0
    logger.warning(
        "wipe_compras: UPDATE etiquetas_envio (desvinculación compras) → %d filas desvinculadas",
        etiquetas_desvinculadas,
    )

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
