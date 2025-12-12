"""
Script INCREMENTAL para sincronizar tablas maestras del ERP usando gbp-parser
Diseñado para ejecutarse cada 10 minutos en cron

Tablas sincronizadas:
- tbBrand (marcas) - sync completo (pocas filas)
- tbCategory (categorías) - sync completo (pocas filas)
- tbSubCategory (subcategorías) - sync completo (pocas filas)
- tbTaxName (impuestos) - sync completo (pocas filas)
- tbItem (items) - INCREMENTAL por lastUpdate
- tbItemTaxes (impuestos por item) - sync de items nuevos/actualizados

Ejecutar:
    python -m app.scripts.sync_erp_master_tables_incremental
    python -m app.scripts.sync_erp_master_tables_incremental --minutes 30
"""
import sys
import os

if __name__ == "__main__":
    backend_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if backend_path not in sys.path:
        sys.path.insert(0, backend_path)

import asyncio
import argparse
import httpx
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func, text
from app.core.database import SessionLocal
import app.models  # noqa - importar todos los modelos
from app.models.tb_brand import TBBrand
from app.models.tb_category import TBCategory
from app.models.tb_subcategory import TBSubCategory
from app.models.tb_item import TBItem
from app.models.tb_tax_name import TBTaxName
from app.models.tb_item_taxes import TBItemTaxes

# URL del endpoint local que proxea al ERP
GBP_PARSER_URL = "http://localhost:8002/api/gbp-parser"


def parse_date(date_str):
    """Parsear fecha desde string"""
    if not date_str:
        return None
    try:
        if isinstance(date_str, str):
            return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return date_str
    except:
        return None


def to_int(value):
    """Convertir a entero"""
    if value is None or value == '':
        return None
    try:
        return int(value)
    except:
        return None


def to_decimal(value):
    """Convertir a decimal"""
    if value is None or value == '':
        return None
    try:
        return float(value)
    except:
        return None


async def sync_brands(db: Session):
    """Sincronizar tabla de marcas (completo - pocas filas)"""
    print("  📦 Marcas...", end=" ", flush=True)

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(GBP_PARSER_URL, params={
                "strScriptLabel": "scriptBrand"
            })
            response.raise_for_status()
            data = response.json()

        if not isinstance(data, list) or len(data) == 0:
            print("✓ (sin datos)")
            return {"nuevos": 0, "actualizados": 0}

        # Verificar si es error
        if len(data) == 1 and "Column1" in data[0]:
            print("⚠️ (sin datos disponibles)")
            return {"nuevos": 0, "actualizados": 0}

        nuevos = 0
        actualizados = 0

        for row in data:
            comp_id = to_int(row.get("comp_id"))
            brand_id = to_int(row.get("brand_id"))
            bra_id = to_int(row.get("bra_id"))
            brand_desc = row.get("brand_desc")

            existente = db.query(TBBrand).filter(
                TBBrand.comp_id == comp_id,
                TBBrand.brand_id == brand_id
            ).first()

            if existente:
                if existente.brand_desc != brand_desc or existente.bra_id != bra_id:
                    existente.brand_desc = brand_desc
                    existente.bra_id = bra_id
                    actualizados += 1
            else:
                nueva = TBBrand(
                    comp_id=comp_id,
                    brand_id=brand_id,
                    bra_id=bra_id,
                    brand_desc=brand_desc
                )
                db.add(nueva)
                nuevos += 1

        db.commit()
        print(f"✓ ({nuevos} nuevos, {actualizados} actualizados)")
        return {"nuevos": nuevos, "actualizados": actualizados}

    except Exception as e:
        print(f"❌ Error: {str(e)}")
        db.rollback()
        return {"nuevos": 0, "actualizados": 0, "error": str(e)}


async def sync_categories(db: Session):
    """Sincronizar tabla de categorías (completo - pocas filas)"""
    print("  📦 Categorías...", end=" ", flush=True)

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(GBP_PARSER_URL, params={
                "strScriptLabel": "scriptCategory"
            })
            response.raise_for_status()
            data = response.json()

        if not isinstance(data, list) or len(data) == 0:
            print("✓ (sin datos)")
            return {"nuevos": 0, "actualizados": 0}

        if len(data) == 1 and "Column1" in data[0]:
            print("⚠️ (sin datos disponibles)")
            return {"nuevos": 0, "actualizados": 0}

        nuevos = 0
        actualizados = 0

        for row in data:
            comp_id = to_int(row.get("comp_id"))
            cat_id = to_int(row.get("cat_id"))
            cat_desc = row.get("cat_desc")

            existente = db.query(TBCategory).filter(
                TBCategory.comp_id == comp_id,
                TBCategory.cat_id == cat_id
            ).first()

            if existente:
                if existente.cat_desc != cat_desc:
                    existente.cat_desc = cat_desc
                    actualizados += 1
            else:
                nueva = TBCategory(
                    comp_id=comp_id,
                    cat_id=cat_id,
                    cat_desc=cat_desc
                )
                db.add(nueva)
                nuevos += 1

        db.commit()
        print(f"✓ ({nuevos} nuevos, {actualizados} actualizados)")
        return {"nuevos": nuevos, "actualizados": actualizados}

    except Exception as e:
        print(f"❌ Error: {str(e)}")
        db.rollback()
        return {"nuevos": 0, "actualizados": 0, "error": str(e)}


async def sync_subcategories(db: Session):
    """Sincronizar tabla de subcategorías (completo - pocas filas)"""
    print("  📦 Subcategorías...", end=" ", flush=True)

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(GBP_PARSER_URL, params={
                "strScriptLabel": "scriptSubCategory"
            })
            response.raise_for_status()
            data = response.json()

        if not isinstance(data, list) or len(data) == 0:
            print("✓ (sin datos)")
            return {"nuevos": 0, "actualizados": 0}

        if len(data) == 1 and "Column1" in data[0]:
            print("⚠️ (sin datos disponibles)")
            return {"nuevos": 0, "actualizados": 0}

        nuevos = 0
        actualizados = 0

        for row in data:
            comp_id = to_int(row.get("comp_id"))
            cat_id = to_int(row.get("cat_id"))
            subcat_id = to_int(row.get("subcat_id"))
            subcat_desc = row.get("subcat_desc")

            existente = db.query(TBSubCategory).filter(
                TBSubCategory.comp_id == comp_id,
                TBSubCategory.cat_id == cat_id,
                TBSubCategory.subcat_id == subcat_id
            ).first()

            if existente:
                if existente.subcat_desc != subcat_desc:
                    existente.subcat_desc = subcat_desc
                    actualizados += 1
            else:
                nueva = TBSubCategory(
                    comp_id=comp_id,
                    cat_id=cat_id,
                    subcat_id=subcat_id,
                    subcat_desc=subcat_desc
                )
                db.add(nueva)
                nuevos += 1

        db.commit()
        print(f"✓ ({nuevos} nuevos, {actualizados} actualizados)")
        return {"nuevos": nuevos, "actualizados": actualizados}

    except Exception as e:
        print(f"❌ Error: {str(e)}")
        db.rollback()
        return {"nuevos": 0, "actualizados": 0, "error": str(e)}


async def sync_tax_names(db: Session):
    """Sincronizar nombres de impuestos (completo - pocas filas)"""
    print("  📦 Impuestos...", end=" ", flush=True)

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(GBP_PARSER_URL, params={
                "strScriptLabel": "scriptTaxName"
            })
            response.raise_for_status()
            data = response.json()

        if not isinstance(data, list) or len(data) == 0:
            print("✓ (sin datos)")
            return {"nuevos": 0, "actualizados": 0}

        if len(data) == 1 and "Column1" in data[0]:
            print("⚠️ (sin datos disponibles)")
            return {"nuevos": 0, "actualizados": 0}

        nuevos = 0
        actualizados = 0

        for row in data:
            comp_id = to_int(row.get("comp_id"))
            tax_id = to_int(row.get("tax_id"))
            tax_desc = row.get("tax_desc")
            tax_percentage = to_decimal(row.get("tax_percentage"))

            existente = db.query(TBTaxName).filter(
                TBTaxName.comp_id == comp_id,
                TBTaxName.tax_id == tax_id
            ).first()

            if existente:
                if existente.tax_desc != tax_desc or existente.tax_percentage != tax_percentage:
                    existente.tax_desc = tax_desc
                    existente.tax_percentage = tax_percentage
                    actualizados += 1
            else:
                nuevo = TBTaxName(
                    comp_id=comp_id,
                    tax_id=tax_id,
                    tax_desc=tax_desc,
                    tax_percentage=tax_percentage
                )
                db.add(nuevo)
                nuevos += 1

        db.commit()
        print(f"✓ ({nuevos} nuevos, {actualizados} actualizados)")
        return {"nuevos": nuevos, "actualizados": actualizados}

    except Exception as e:
        print(f"❌ Error: {str(e)}")
        db.rollback()
        return {"nuevos": 0, "actualizados": 0, "error": str(e)}


async def sync_items_incremental(db: Session, minutes: int = 15):
    """
    Sincronizar items INCREMENTALMENTE
    Solo trae items con item_LastUpdate en los últimos X minutos
    """
    print(f"  📦 Items (últimos {minutes} min)...", end=" ", flush=True)

    try:
        # Calcular fecha límite
        fecha_limite = datetime.now() - timedelta(minutes=minutes)
        fecha_str = fecha_limite.strftime("%Y-%m-%d")

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.get(GBP_PARSER_URL, params={
                "strScriptLabel": "scriptItem",
                "lastUpdate": fecha_str
            })
            response.raise_for_status()
            data = response.json()

        if not isinstance(data, list) or len(data) == 0:
            print("✓ (sin datos)")
            return {"nuevos": 0, "actualizados": 0, "items": []}

        if len(data) == 1 and "Column1" in data[0]:
            print("✓ (sin cambios recientes)")
            return {"nuevos": 0, "actualizados": 0, "items": []}

        nuevos = 0
        actualizados = 0
        items_procesados = []

        for row in data:
            comp_id = to_int(row.get("comp_id"))
            item_id = to_int(row.get("item_id"))
            item_code = row.get("item_code")
            item_desc = row.get("item_desc")
            cat_id = to_int(row.get("cat_id"))
            subcat_id = to_int(row.get("subcat_id"))
            brand_id = to_int(row.get("brand_id"))
            item_liquidation = row.get("item_liquidation")
            item_cd = parse_date(row.get("item_cd"))
            item_LastUpdate = parse_date(row.get("item_LastUpdate"))

            items_procesados.append(item_id)

            existente = db.query(TBItem).filter(
                TBItem.comp_id == comp_id,
                TBItem.item_id == item_id
            ).first()

            if existente:
                # Actualizar si hay cambios
                if (existente.item_code != item_code or
                    existente.item_desc != item_desc or
                    existente.cat_id != cat_id or
                    existente.subcat_id != subcat_id or
                    existente.brand_id != brand_id):
                    existente.item_code = item_code
                    existente.item_desc = item_desc
                    existente.cat_id = cat_id
                    existente.subcat_id = subcat_id
                    existente.brand_id = brand_id
                    existente.item_liquidation = item_liquidation
                    existente.item_LastUpdate = item_LastUpdate
                    actualizados += 1
            else:
                nuevo = TBItem(
                    comp_id=comp_id,
                    item_id=item_id,
                    item_code=item_code,
                    item_desc=item_desc,
                    cat_id=cat_id,
                    subcat_id=subcat_id,
                    brand_id=brand_id,
                    item_liquidation=item_liquidation,
                    item_cd=item_cd,
                    item_LastUpdate=item_LastUpdate
                )
                db.add(nuevo)
                nuevos += 1

            if (nuevos + actualizados) % 100 == 0:
                db.commit()

        db.commit()
        print(f"✓ ({nuevos} nuevos, {actualizados} actualizados)")
        return {"nuevos": nuevos, "actualizados": actualizados, "items": items_procesados}

    except Exception as e:
        print(f"❌ Error: {str(e)}")
        db.rollback()
        return {"nuevos": 0, "actualizados": 0, "items": [], "error": str(e)}


async def sync_item_taxes_for_items(db: Session, item_ids: list):
    """
    Sincronizar impuestos solo para los items que se actualizaron
    """
    if not item_ids:
        print("  📦 Impuestos por item... ✓ (sin items nuevos)")
        return {"nuevos": 0, "actualizados": 0}

    print(f"  📦 Impuestos por item ({len(item_ids)} items)...", end=" ", flush=True)

    try:
        nuevos = 0
        actualizados = 0

        # Procesar en lotes de 50 items para no sobrecargar el endpoint
        batch_size = 50
        for i in range(0, len(item_ids), batch_size):
            batch = item_ids[i:i+batch_size]

            for item_id in batch:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    response = await client.get(GBP_PARSER_URL, params={
                        "strScriptLabel": "scriptItemTaxes",
                        "itemID": item_id
                    })
                    response.raise_for_status()
                    data = response.json()

                if not isinstance(data, list) or len(data) == 0:
                    continue

                if len(data) == 1 and "Column1" in data[0]:
                    continue

                for row in data:
                    comp_id = to_int(row.get("comp_id"))
                    row_item_id = to_int(row.get("item_id"))
                    tax_id = to_int(row.get("tax_id"))
                    tax_class = to_int(row.get("tax_class"))

                    existente = db.query(TBItemTaxes).filter(
                        TBItemTaxes.comp_id == comp_id,
                        TBItemTaxes.item_id == row_item_id,
                        TBItemTaxes.tax_id == tax_id
                    ).first()

                    if existente:
                        if existente.tax_class != tax_class:
                            existente.tax_class = tax_class
                            actualizados += 1
                    else:
                        nuevo = TBItemTaxes(
                            comp_id=comp_id,
                            item_id=row_item_id,
                            tax_id=tax_id,
                            tax_class=tax_class
                        )
                        db.add(nuevo)
                        nuevos += 1

            db.commit()

        print(f"✓ ({nuevos} nuevos, {actualizados} actualizados)")
        return {"nuevos": nuevos, "actualizados": actualizados}

    except Exception as e:
        print(f"❌ Error: {str(e)}")
        db.rollback()
        return {"nuevos": 0, "actualizados": 0, "error": str(e)}


async def verificar_items_faltantes(db: Session):
    """
    Verifica si hay items en ventas ML que no existen en tb_item
    y los sincroniza si es necesario
    """
    print("  🔍 Verificando items faltantes...", end=" ", flush=True)

    try:
        # Buscar item_ids que están en ventas pero no en tb_item
        query = text("""
            SELECT DISTINCT tmlod.item_id
            FROM tb_mercadolibre_orders_detail tmlod
            LEFT JOIN tb_item ti ON ti.item_id = tmlod.item_id
            WHERE ti.item_id IS NULL
              AND tmlod.item_id IS NOT NULL
            LIMIT 100
        """)

        result = db.execute(query)
        items_faltantes = [row[0] for row in result.fetchall()]

        if not items_faltantes:
            print("✓ (ninguno)")
            return {"sincronizados": 0}

        print(f"encontrados {len(items_faltantes)}", end=" ", flush=True)

        # Sincronizar estos items específicos desde el ERP
        sincronizados = 0
        items_sync = []

        for item_id in items_faltantes:
            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    response = await client.get(GBP_PARSER_URL, params={
                        "strScriptLabel": "scriptItem",
                        "itemID": item_id
                    })
                    response.raise_for_status()
                    data = response.json()

                if not isinstance(data, list) or len(data) == 0:
                    continue

                if len(data) == 1 and "Column1" in data[0]:
                    continue

                for row in data:
                    comp_id = to_int(row.get("comp_id"))
                    row_item_id = to_int(row.get("item_id"))

                    # Verificar que no exista
                    existente = db.query(TBItem).filter(
                        TBItem.comp_id == comp_id,
                        TBItem.item_id == row_item_id
                    ).first()

                    if not existente:
                        nuevo = TBItem(
                            comp_id=comp_id,
                            item_id=row_item_id,
                            item_code=row.get("item_code"),
                            item_desc=row.get("item_desc"),
                            cat_id=to_int(row.get("cat_id")),
                            subcat_id=to_int(row.get("subcat_id")),
                            brand_id=to_int(row.get("brand_id")),
                            item_liquidation=row.get("item_liquidation"),
                            item_cd=parse_date(row.get("item_cd")),
                            item_LastUpdate=parse_date(row.get("item_LastUpdate"))
                        )
                        db.add(nuevo)
                        items_sync.append(row_item_id)
                        sincronizados += 1

            except Exception as e:
                continue

        db.commit()

        # Sincronizar impuestos de estos items
        if items_sync:
            await sync_item_taxes_for_items(db, items_sync)

        print(f"✓ ({sincronizados} sincronizados)")
        return {"sincronizados": sincronizados}

    except Exception as e:
        print(f"❌ Error: {str(e)}")
        db.rollback()
        return {"sincronizados": 0, "error": str(e)}


async def main_async(minutes: int = 15):
    """Función principal async"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print("=" * 60)
    print(f"SYNC INCREMENTAL TABLAS MAESTRAS ERP - {timestamp}")
    print("=" * 60)

    db = SessionLocal()
    try:
        # Tablas pequeñas - sync completo (rápido)
        await sync_brands(db)
        await sync_categories(db)
        await sync_subcategories(db)
        await sync_tax_names(db)

        # Items - sync incremental
        result_items = await sync_items_incremental(db, minutes=minutes)

        # Impuestos de items actualizados
        await sync_item_taxes_for_items(db, result_items.get("items", []))

        # Verificar items faltantes
        await verificar_items_faltantes(db)

        print("\n" + "=" * 60)
        print("✅ SINCRONIZACIÓN COMPLETADA")
        print("=" * 60)

    except Exception as e:
        print(f"\n❌ Error durante la sincronización: {str(e)}")
        import traceback
        traceback.print_exc()
        db.rollback()
        sys.exit(1)
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description='Sync incremental de tablas maestras ERP')
    parser.add_argument('--minutes', type=int, default=15,
                        help='Minutos hacia atrás para buscar cambios (default: 15)')
    args = parser.parse_args()

    asyncio.run(main_async(args.minutes))


if __name__ == "__main__":
    main()
