"""
Reconciliación de cancelaciones ML contra mlwebhook.ml_cancelled_orders.

Resuelve el bug de que las ventas canceladas seguían impactando ventas/ganancia/
markup. Causa raíz encadenada:
  1. sync_ml_orders_incremental es INSERT-ONLY por max(mlo_id): nunca refresca el
     estado de órdenes existentes, así que una cancelación posterior nunca llegaba
     a tb_mercadolibre_orders_header (mlo_status quedaba 'paid').
  2. agregar_metricas_ml_incremental solo mira los últimos 10 min y su filtro
     `mlo_status <> 'cancelled'` excluye las canceladas del UPDATE, así que la fila
     ya insertada en ml_ventas_metricas nunca se podía limpiar.

Esta reconciliación lee las cancelaciones que ml-webhook ya registró (event-driven,
sin polling masivo a ML) y:
  A. Descongela el header: tb_mercadolibre_orders_header.mlo_status = 'cancelled' +
     mlo_iscancelled = TRUE. Con esto, los filtros que YA chequean mlo_status
     (ventas_ml.py, agregar_metricas_*) empiezan a funcionar solos.
  B. Marca ml_ventas_metricas.is_cancelled = TRUE + fecha_cancelacion (el dashboard
     filtra is_cancelled = False).
  C. Revierte el consumo de offsets (grupo + individual) de esas operaciones.

Clave de cruce: ml_cancelled_orders.order_id (BIGINT, el número de orden de ML) ↔
ml_ventas_metricas.ml_order_id (String) = tb_mercadolibre_orders_header.ml_id.
NO es id_operacion (ese es el mlo_id interno de GBP).

Idempotente: solo toca filas que aún no estaban canceladas / consumos que aún existen.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.offset_grupo_consumo import OffsetGrupoConsumo, OffsetGrupoResumen
from app.models.offset_individual_consumo import OffsetIndividualConsumo, OffsetIndividualResumen
from app.services.ml_cancelled_orders_service import fetch_cancelled_since

logger = logging.getLogger(__name__)


def _revertir_offsets_grupo(db: Session, id_operacion: int) -> int:
    """Revierte el consumo de offsets de GRUPO de una operación cancelada.

    Resta del resumen lo que esa operación había sumado y borra el consumo.
    Idempotente: si el consumo ya fue borrado, no hace nada.
    """
    consumos = db.query(OffsetGrupoConsumo).filter(OffsetGrupoConsumo.id_operacion == id_operacion).all()
    for c in consumos:
        resumen = db.query(OffsetGrupoResumen).filter(OffsetGrupoResumen.grupo_id == c.grupo_id).first()
        if resumen:
            resumen.total_unidades = (resumen.total_unidades or 0) - (c.cantidad or 0)
            resumen.total_monto_ars = float(resumen.total_monto_ars or 0) - float(c.monto_offset_aplicado or 0)
            resumen.total_monto_usd = float(resumen.total_monto_usd or 0) - float(c.monto_offset_usd or 0)
            resumen.cantidad_ventas = (resumen.cantidad_ventas or 0) - 1
        db.delete(c)
    return len(consumos)


def _revertir_offsets_individual(db: Session, id_operacion: int) -> int:
    """Revierte el consumo de offsets INDIVIDUALES de una operación cancelada."""
    consumos = db.query(OffsetIndividualConsumo).filter(OffsetIndividualConsumo.id_operacion == id_operacion).all()
    for c in consumos:
        resumen = db.query(OffsetIndividualResumen).filter(OffsetIndividualResumen.offset_id == c.offset_id).first()
        if resumen:
            resumen.total_unidades = (resumen.total_unidades or 0) - (c.cantidad or 0)
            resumen.total_monto_ars = float(resumen.total_monto_ars or 0) - float(c.monto_offset_aplicado or 0)
            resumen.total_monto_usd = float(resumen.total_monto_usd or 0) - float(c.monto_offset_usd or 0)
            resumen.cantidad_ventas = (resumen.cantidad_ventas or 0) - 1
        db.delete(c)
    return len(consumos)


def reconciliar_cancelaciones(
    db: Session,
    since: Optional[datetime] = None,
    lookback_days: Optional[int] = 90,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Reconcilia las cancelaciones registradas por ml-webhook contra las métricas locales.

    Args:
        db: sesión de pricing_dev.
        since: solo cancelaciones con cancelled_at > since. Tiene prioridad sobre lookback_days.
        lookback_days: si since es None, usa now() - lookback_days. None = barrido full (todo).
        dry_run: si True, calcula y loguea pero hace rollback (no persiste).

    Returns:
        Dict con contadores: leidas, headers_actualizados, metricas_marcadas,
        offsets_grupo_revertidos, offsets_individual_revertidos.
    """
    if since is None and lookback_days is not None:
        since = datetime.now() - timedelta(days=lookback_days)

    canceladas = fetch_cancelled_since(since=since)

    stats = {
        "leidas": len(canceladas),
        "headers_actualizados": 0,
        "metricas_marcadas": 0,
        "offsets_grupo_revertidos": 0,
        "offsets_individual_revertidos": 0,
    }

    if not canceladas:
        logger.info("✅ Reconciliación: no hay cancelaciones nuevas para procesar")
        return stats

    for row in canceladas:
        order_id = row["order_id"]
        ml_order_id = str(order_id)  # cruce: BIGINT (mlwebhook) ↔ String (pricing)
        # Fecha de cancelación: preferir date_closed (cierre real), fallback cancelled_at
        fecha_cancelacion = row.get("date_closed") or row.get("cancelled_at")

        # A. Descongelar el header (corrige la raíz: status frozen por sync insert-only)
        res_header = db.execute(
            text("""
                UPDATE tb_mercadolibre_orders_header
                SET mlo_status = 'cancelled', mlo_iscancelled = TRUE
                WHERE ml_id = :ml_id
                  AND (mlo_status IS DISTINCT FROM 'cancelled' OR mlo_iscancelled IS NOT TRUE)
            """),
            {"ml_id": ml_order_id},
        )
        stats["headers_actualizados"] += res_header.rowcount or 0

        # B. Marcar métricas + recolectar id_operacion de las que recién se cancelan
        ops = db.execute(
            text("""
                UPDATE ml_ventas_metricas
                SET is_cancelled = TRUE, fecha_cancelacion = :fecha
                WHERE ml_order_id = :ml_order_id
                  AND is_cancelled = FALSE
                RETURNING id_operacion
            """),
            {"ml_order_id": ml_order_id, "fecha": fecha_cancelacion},
        ).fetchall()

        ids_operacion = [r[0] for r in ops]
        stats["metricas_marcadas"] += len(ids_operacion)

        # C. Revertir offsets de las operaciones recién canceladas
        for id_operacion in ids_operacion:
            stats["offsets_grupo_revertidos"] += _revertir_offsets_grupo(db, id_operacion)
            stats["offsets_individual_revertidos"] += _revertir_offsets_individual(db, id_operacion)

    if dry_run:
        db.rollback()
        logger.info(f"🧪 DRY-RUN reconciliación (rollback): {stats}")
    else:
        db.commit()
        logger.info(f"✅ Reconciliación completada: {stats}")

    return stats
