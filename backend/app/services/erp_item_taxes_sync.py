"""
Servicio de sincronización standalone de impuestos por item (tb_item_taxes).

El sync incremental de tablas maestras (`sync_erp_master_tables_incremental.py`)
solo trae impuestos de los items devueltos por `scriptItem`, filtrado por
`item_LastUpdate`/`item_lastUpdate_byProcess` de `tb_item`. Cuando en el ERP
corrigen el IVA de un producto tocan `tb_item_taxes` (tax_id) pero NO
`tb_item`, así que esos items nunca entran al incremental y el espejo local
queda con el tax_id viejo para siempre.

Esta función vive separada del sync completo de tablas maestras
(`sync_erp_master_tables_full.py`) para poder engancharla a un cron propio
que la corra sola, sin cargar con el resto del sync completo (pesado y poco
frecuente).
"""

import logging

import httpx
from sqlalchemy import tuple_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.tb_item_taxes import TBItemTaxes

logger = logging.getLogger(__name__)


def to_int(value):
    """Convertir a entero"""
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


async def sync_item_taxes_full(db: Session):
    """
    Sincronizar TODOS los impuestos por item.

    Estrategia REPLACE: borra las filas locales de los pares (comp_id, item_id)
    que vinieron del ERP y reinserta todo lo recibido. Esto refleja cambios de
    tax_id (el sync viejo solo insertaba, dejando filas huérfanas que rompían
    el IVA del producto en la query local). Si el ERP devuelve vacío, NO se
    borra nada (safeguard ante fallos transitorios).

    El delete filtra por el PAR (comp_id, item_id), no solo por item_id: la PK
    de TBItemTaxes es (comp_id, item_id, tax_id), y un item_id puede repetirse
    en distintas comp_id. Filtrar solo por item_id borraría filas de otra
    comp_id que el ERP no devolvió y que nunca se reinsertan.
    """
    logger.info("Sincronizando impuestos por item (TODOS)...")

    try:
        # Sin parámetro para traer TODOS
        async with httpx.AsyncClient(timeout=600.0) as client:  # 10 min timeout
            response = await client.get(settings.GBP_PARSER_URL, params={"strScriptLabel": "scriptItemTaxes"})
            response.raise_for_status()
            data = response.json()

        if not isinstance(data, list) or len(data) == 0:
            logger.info("Sin datos de impuestos por item")
            return {"insertados": 0, "items_reemplazados": 0}

        if len(data) == 1 and "Column1" in data[0]:
            logger.warning("Sin datos disponibles de impuestos por item (respuesta centinela)")
            return {"insertados": 0, "items_reemplazados": 0}

        logger.info("Recibidos %d registros de impuestos por item", len(data))

        pares_recibidos = {
            (to_int(row.get("comp_id")), to_int(row.get("item_id")))
            for row in data
            if to_int(row.get("comp_id")) is not None and to_int(row.get("item_id")) is not None
        }

        # Delete + insert van en UNA sola transacción: si algo se rompe a mitad,
        # el rollback restaura las filas viejas y no queda la tabla en estado parcial.
        delete_batch = 500
        pares_list = list(pares_recibidos)
        for i in range(0, len(pares_list), delete_batch):
            batch_pares = pares_list[i : i + delete_batch]
            db.query(TBItemTaxes).filter(tuple_(TBItemTaxes.comp_id, TBItemTaxes.item_id).in_(batch_pares)).delete(
                synchronize_session=False
            )

        nuevos = [
            TBItemTaxes(
                comp_id=to_int(row.get("comp_id")),
                item_id=to_int(row.get("item_id")),
                tax_id=to_int(row.get("tax_id")),
                tax_class=to_int(row.get("tax_class")),
            )
            for row in data
        ]
        db.bulk_save_objects(nuevos)
        db.commit()

        insertados = len(nuevos)
        logger.info("Sync IVA completo: %d insertados, %d items reemplazados", insertados, len(pares_recibidos))
        return {"insertados": insertados, "items_reemplazados": len(pares_recibidos)}

    except Exception as e:
        logger.error("Sync IVA falló: %s", e, exc_info=True)
        db.rollback()
        return {"insertados": 0, "items_reemplazados": 0, "error": str(e)}
