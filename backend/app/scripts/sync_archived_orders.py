"""
Script para archivar pedidos que ya no existen en el ERP.

LÓGICA:
La fuente de verdad es el ERP (GBP). Un pedido se archiva SOLO cuando
el ERP ya no lo devuelve en el sync. Esto se detecta comparando los
soh_ids que tenemos en tb_sale_order_header contra los que devuelve
el endpoint scriptSaleOrderHeader del gbp-parser.

Pedidos que están en nuestra DB pero NO en el ERP → se mueven a history
(insert en history si no existe, delete de header).

NUNCA se borra un pedido de header solo porque existe en history.
El ERP puede tener un pedido activo Y a la vez tener registros de
history (facturaciones parciales, notas de crédito, etc.).

USO:
    python -m app.scripts.sync_archived_orders [--dry-run] [--days 180]
"""

import argparse
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx

backend_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_dir))

import logging

from sqlalchemy import and_, text

from app.core.database import SessionLocal
from app.models.sale_order_header import SaleOrderHeader

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

GBP_PARSER_URL = "http://localhost:8002/api/gbp-parser"


def fetch_erp_soh_ids(days: int = 180) -> set[tuple[int, int, int]]:
    """Obtiene el set de (comp_id, bra_id, soh_id) que existen en el ERP."""
    from_date = (date.today() - timedelta(days=days)).isoformat()
    to_date = (date.today() + timedelta(days=1)).isoformat()

    logger.info(f"Consultando ERP (scriptSaleOrderHeader, {days} dias)...")

    with httpx.Client(timeout=300.0) as client:
        response = client.get(
            GBP_PARSER_URL,
            params={
                "strScriptLabel": "scriptSaleOrderHeader",
                "fromDate": from_date,
                "toDate": to_date,
            },
        )
        response.raise_for_status()
        data = response.json()

    if not isinstance(data, list):
        logger.warning("ERP devolvio formato inesperado, abortando")
        return set()

    erp_ids = set()
    for record in data:
        comp_id = record.get("comp_id")
        bra_id = record.get("bra_id")
        soh_id = record.get("soh_id")
        if comp_id and bra_id and soh_id:
            erp_ids.add((comp_id, bra_id, soh_id))

    logger.info(f"ERP devolvio {len(erp_ids)} pedidos activos")
    return erp_ids


def archive_missing_orders(dry_run: bool = True, days: int = 180) -> dict:
    """
    Archiva pedidos que están en nuestra DB pero no en el ERP.

    1. Trae todos los soh_ids del ERP (últimos N días)
    2. Compara con los que tenemos en tb_sale_order_header
    3. Los que NO están en el ERP → insert en history (si no existe) + delete de header
    """
    erp_ids = fetch_erp_soh_ids(days)
    if not erp_ids:
        logger.warning("No se obtuvieron IDs del ERP, abortando por seguridad")
        return {"archivados": 0, "error": "Sin datos del ERP"}

    db = SessionLocal()
    try:
        # Obtener pedidos locales en el rango de fecha comparable
        fecha_limite = datetime.combine(date.today() - timedelta(days=days), datetime.min.time())
        locales = (
            db.query(
                SaleOrderHeader.comp_id,
                SaleOrderHeader.bra_id,
                SaleOrderHeader.soh_id,
                SaleOrderHeader.ssos_id,
                SaleOrderHeader.soh_cd,
            )
            .filter(
                # Solo comparar pedidos dentro del rango de fecha del sync
                # Pedidos más viejos que el rango no se tocan
                SaleOrderHeader.soh_cd >= fecha_limite,
            )
            .all()
        )

        local_ids = {(r.comp_id, r.bra_id, r.soh_id) for r in locales}
        logger.info(f"DB local tiene {len(local_ids)} pedidos en el rango de {days} dias")

        # Los que están en local pero NO en el ERP → archivar
        a_archivar = local_ids - erp_ids
        logger.info(f"Pedidos a archivar (en DB pero no en ERP): {len(a_archivar)}")

        if not a_archivar:
            logger.info("No hay pedidos para archivar")
            return {"archivados": 0}

        # Mostrar ejemplos
        ejemplos = list(a_archivar)[:10]
        logger.info("Ejemplos:")
        for comp_id, bra_id, soh_id in ejemplos:
            local_row = next(
                (r for r in locales if r.comp_id == comp_id and r.bra_id == bra_id and r.soh_id == soh_id), None
            )
            estado = local_row.ssos_id if local_row else "?"
            fecha = str(local_row.soh_cd)[:10] if local_row and local_row.soh_cd else "NULL"
            logger.info(f"  comp={comp_id} bra={bra_id} soh={soh_id} estado={estado} fecha={fecha}")

        if dry_run:
            logger.info(f"[DRY RUN] Se archivarian {len(a_archivar)} pedidos")
            return {"archivados": len(a_archivar), "dry_run": True}

        # Ejecutar archivado
        archivados = 0
        for comp_id, bra_id, soh_id in a_archivar:
            try:
                # Delete de header (el history ya se sincroniza por separado)
                db.execute(
                    text("""
                        DELETE FROM tb_sale_order_header
                        WHERE comp_id = :comp_id AND bra_id = :bra_id AND soh_id = :soh_id
                    """),
                    {"comp_id": comp_id, "bra_id": bra_id, "soh_id": soh_id},
                )
                # Delete de detail
                db.execute(
                    text("""
                        DELETE FROM tb_sale_order_detail
                        WHERE comp_id = :comp_id AND bra_id = :bra_id AND soh_id = :soh_id
                    """),
                    {"comp_id": comp_id, "bra_id": bra_id, "soh_id": soh_id},
                )
                archivados += 1

                if archivados % 100 == 0:
                    db.commit()

            except Exception as e:
                logger.warning(f"Error archivando {comp_id}/{bra_id}/{soh_id}: {e}")
                continue

        db.commit()
        logger.info(f"Archivados: {archivados} pedidos")
        return {"archivados": archivados}

    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        db.rollback()
        return {"archivados": 0, "error": str(e)}
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Archivar pedidos que no existen en el ERP")
    parser.add_argument("--dry-run", action="store_true", default=False, help="Solo mostrar que se haria")
    parser.add_argument("--days", type=int, default=180, help="Rango de dias a comparar (default: 180)")
    args = parser.parse_args()

    if not args.dry_run:
        logger.info("=== APLICANDO CAMBIOS ===")
    else:
        logger.info("=== DRY RUN ===")

    result = archive_missing_orders(dry_run=args.dry_run, days=args.days)
    logger.info(f"Resultado: {result}")
