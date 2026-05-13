"""
Matcher de prearmados con sales orders.

Compara los seriales validados de cada prearmado activo contra `tb_sale_order_serials`
(populada por `sync_sale_order_serials.py`). Si TODOS los seriales serializables del
prearmado aparecen asignados al mismo `soh_id`, se marca el prearmado como `consumido`.

Reglas:
- Solo se consideran seriales con `requiere_serie=true AND validado=true AND is_id NOT NULL`.
- Items con `requiere_serie=false` (gabinete, descuento, Win11 implícito) NO entran al check.
- Match por completitud de set: un `soh_id` debe contener TODOS los is_ids del prearmado.
- Prearmados en estado `consumido` o `anulado` se ignoran (terminales).
- Errores por prearmado se acumulan pero no abortan el resto.
"""

import logging
from typing import Dict, List

from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from app.models.prearmado import Prearmado


logger = logging.getLogger(__name__)


_ESTADOS_ACTIVOS = ("pendiente", "en_proceso", "armado")


def match_prearmados_with_sales_orders(db: Session) -> Dict[str, object]:
    """
    Itera los prearmados activos y los marca como `consumido` si sus seriales matchean
    un sales order completo.

    Returns:
        Dict con `matched` (cuántos pasaron a consumido), `total_checked` (cuántos
        prearmados activos se evaluaron) y `errors` (lista de mensajes por prearmado).
    """
    activos: List[Prearmado] = db.query(Prearmado).filter(Prearmado.estado.in_(_ESTADOS_ACTIVOS)).all()

    matched = 0
    errors: List[str] = []

    for p in activos:
        try:
            is_ids = [s.is_id for s in p.seriales if s.requiere_serie and s.validado and s.is_id is not None]
            if not is_ids:
                # Sin seriales serializables válidos no podemos matchear todavía
                continue

            # Buscar un soh_id que contenga TODOS los is_ids del prearmado.
            # GROUP BY soh_id + HAVING COUNT(DISTINCT is_id) = N.
            result = db.execute(
                text(
                    """
                    SELECT soh_id
                    FROM tb_sale_order_serials
                    WHERE is_id = ANY(:is_ids)
                      AND comp_id = :comp_id
                    GROUP BY soh_id
                    HAVING COUNT(DISTINCT is_id) = :n
                    LIMIT 1
                    """
                ),
                {"is_ids": is_ids, "comp_id": p.comp_id, "n": len(is_ids)},
            ).first()

            if result:
                p.estado = "consumido"
                p.consumido_por_soh_id = result.soh_id
                p.consumido_at = func.now()
                matched += 1
                logger.info(f"✅ Prearmado {p.codigo} → consumido (soh_id={result.soh_id}, is_ids={is_ids})")
        except Exception as e:
            msg = f"prearmado {p.id} ({p.codigo}): {e}"
            errors.append(msg)
            logger.error(f"❌ Error matching {msg}", exc_info=True)

    if matched > 0:
        db.commit()

    return {
        "matched": matched,
        "total_checked": len(activos),
        "errors": errors,
    }
