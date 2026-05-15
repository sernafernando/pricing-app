"""
Matcher de prearmados con sales orders.

Compara los seriales validados de cada prearmado activo contra el ERP buscando un
sales order que contenga TODOS los is_ids del prearmado. Si lo encuentra, marca
el prearmado como `consumido`.

Dos caminos de match en orden:
1. `tb_sale_order_serials` — pedidos de venta PENDIENTES (no facturados aún).
   Es lo que llena `sync_sale_order_serials.py` desde el ERP.
2. `tb_item_transaction_serials` + `tb_commercial_transactions` — pedidos ya
   FACTURADOS. Cuando GBP factura un pedido, los seriales se mueven de
   `tb_sale_order_serials` a la transacción comercial. Sin este fallback los
   prearmados que se facturan entre dos corridas del sync nunca se marcaban
   consumidos. Recuperamos el `soh_id` original via `ct_soh_id` de la factura.

Reglas:
- Solo se consideran seriales con `requiere_serie=true AND validado=true AND is_id NOT NULL`.
- Items con `requiere_serie=false` (gabinete, descuento, Win11 implícito) NO entran al check.
- Match por completitud de set: el sales order debe contener TODOS los is_ids del prearmado.
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

            params = {"is_ids": is_ids, "comp_id": p.comp_id, "n": len(is_ids)}

            # Camino 1: pedido pendiente — sales order todavía no facturado.
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
                params,
            ).first()
            via = "sale_order_pendiente"

            # Camino 2 (fallback): pedido ya facturado — los seriales pasaron a la
            # transacción comercial. Recuperamos el soh_id origen via ct_soh_id.
            if not result:
                result = db.execute(
                    text(
                        """
                        SELECT ct.ct_soh_id AS soh_id
                        FROM tb_item_transaction_serials its
                        INNER JOIN tb_commercial_transactions ct
                            ON ct.ct_transaction = its.ct_transaction
                        WHERE its.is_id = ANY(:is_ids)
                          AND its.comp_id = :comp_id
                          AND ct.ct_soh_id IS NOT NULL
                        GROUP BY ct.ct_soh_id
                        HAVING COUNT(DISTINCT its.is_id) = :n
                        LIMIT 1
                        """
                    ),
                    params,
                ).first()
                via = "factura"

            if result:
                p.estado = "consumido"
                p.consumido_por_soh_id = result.soh_id
                p.consumido_at = func.now()
                matched += 1
                logger.info(f"✅ Prearmado {p.codigo} → consumido (soh_id={result.soh_id}, via={via}, is_ids={is_ids})")
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
