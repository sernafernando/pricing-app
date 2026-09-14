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

import httpx
from sqlalchemy.orm import Session

from app.models.tb_item_taxes import TBItemTaxes

# URL del endpoint local que proxea al ERP
GBP_PARSER_URL = "http://localhost:8002/api/gbp-parser"


def to_int(value):
    """Convertir a entero"""
    if value is None or value == "":
        return None
    try:
        return int(value)
    except:
        return None


async def sync_item_taxes_full(db: Session):
    """
    Sincronizar TODOS los impuestos por item.

    Estrategia REPLACE: borra las filas locales de los item_ids que vinieron
    del ERP y reinserta todo lo recibido. Esto refleja cambios de tax_id
    (el sync viejo solo insertaba, dejando filas huérfanas que rompían el
    IVA del producto en la query local). Si el ERP devuelve vacío, NO se
    borra nada (safeguard ante fallos transitorios).
    """
    print("  📦 Impuestos por item (TODOS)...", end=" ", flush=True)

    try:
        # Sin parámetro para traer TODOS
        async with httpx.AsyncClient(timeout=600.0) as client:  # 10 min timeout
            response = await client.get(GBP_PARSER_URL, params={"strScriptLabel": "scriptItemTaxes"})
            response.raise_for_status()
            data = response.json()

        if not isinstance(data, list) or len(data) == 0:
            print("✓ (sin datos)")
            return {"insertados": 0, "items_reemplazados": 0}

        if len(data) == 1 and "Column1" in data[0]:
            print("⚠️ (sin datos disponibles)")
            return {"insertados": 0, "items_reemplazados": 0}

        print(f"recibidos {len(data)} registros...", end=" ", flush=True)

        item_ids_recibidos = {to_int(row.get("item_id")) for row in data if to_int(row.get("item_id"))}

        # Delete + insert van en UNA sola transacción: si algo se rompe a mitad,
        # el rollback restaura las filas viejas y no queda la tabla en estado parcial.
        delete_batch = 500
        item_ids_list = list(item_ids_recibidos)
        for i in range(0, len(item_ids_list), delete_batch):
            batch_ids = item_ids_list[i : i + delete_batch]
            db.query(TBItemTaxes).filter(TBItemTaxes.item_id.in_(batch_ids)).delete(synchronize_session=False)

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
        print(f"✓ ({insertados} insertados, {len(item_ids_recibidos)} items reemplazados)")
        return {"insertados": insertados, "items_reemplazados": len(item_ids_recibidos)}

    except Exception as e:
        print(f"❌ Error: {str(e)}")
        db.rollback()
        import traceback

        traceback.print_exc()
        return {"insertados": 0, "items_reemplazados": 0, "error": str(e)}
