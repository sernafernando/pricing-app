"""
Script para sincronización COMPLETA de tablas maestras del ERP usando gbp-parser
Diseñado para carga inicial - trae TODOS los datos sin filtro de fecha

Tablas sincronizadas:
- tbBrand (marcas)
- tbCategory (categorías)
- tbSubCategory (subcategorías)
- tbTaxName (impuestos)
- tbItem (items) - TODOS
- tbItemTaxes (impuestos por item) - TODOS

Ejecutar:
    python -m app.scripts.sync_erp_master_tables_full
"""
import sys
import os

if __name__ == "__main__":
    backend_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if backend_path not in sys.path:
        sys.path.insert(0, backend_path)

import asyncio
import httpx
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import text
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
    """Sincronizar tabla de marcas (completo)"""
    print("  📦 Marcas...", end=" ", flush=True)

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.get(GBP_PARSER_URL, params={
                "strScriptLabel": "scriptBrand"
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
    """Sincronizar tabla de categorías (completo)"""
    print("  📦 Categorías...", end=" ", flush=True)

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
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
    """Sincronizar tabla de subcategorías (completo)"""
    print("  📦 Subcategorías...", end=" ", flush=True)

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
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
    """Sincronizar nombres de impuestos (completo)"""
    print("  📦 Impuestos...", end=" ", flush=True)

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
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


async def sync_items_full(db: Session):
    """
    Sincronizar TODOS los items (sin filtro de fecha)
    """
    print("  📦 Items (TODOS)...", end=" ", flush=True)

    try:
        # Sin parámetro lastUpdate para traer TODOS
        async with httpx.AsyncClient(timeout=600.0) as client:  # 10 min timeout
            response = await client.get(GBP_PARSER_URL, params={
                "strScriptLabel": "scriptItem"
            })
            response.raise_for_status()
            data = response.json()

        if not isinstance(data, list) or len(data) == 0:
            print("✓ (sin datos)")
            return {"nuevos": 0, "actualizados": 0}

        if len(data) == 1 and "Column1" in data[0]:
            print("⚠️ (sin datos disponibles)")
            return {"nuevos": 0, "actualizados": 0}

        print(f"recibidos {len(data)} items...", end=" ", flush=True)

        nuevos = 0
        actualizados = 0

        for i, row in enumerate(data):
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
            item_lastUpdate_byProcess = parse_date(row.get("item_lastUpdate_byProcess"))

            existente = db.query(TBItem).filter(
                TBItem.comp_id == comp_id,
                TBItem.item_id == item_id
            ).first()

            if existente:
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
                    existente.item_lastUpdate_byProcess = item_lastUpdate_byProcess
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
                    item_LastUpdate=item_LastUpdate,
                    item_lastUpdate_byProcess=item_lastUpdate_byProcess
                )
                db.add(nuevo)
                nuevos += 1

            # Commit cada 500 registros
            if (i + 1) % 500 == 0:
                db.commit()
                print(f"{i+1}...", end=" ", flush=True)

        db.commit()
        print(f"✓ ({nuevos} nuevos, {actualizados} actualizados)")
        return {"nuevos": nuevos, "actualizados": actualizados}

    except Exception as e:
        print(f"❌ Error: {str(e)}")
        db.rollback()
        import traceback
        traceback.print_exc()
        return {"nuevos": 0, "actualizados": 0, "error": str(e)}


async def sync_item_taxes_full(db: Session):
    """
    Sincronizar TODOS los impuestos por item
    """
    print("  📦 Impuestos por item (TODOS)...", end=" ", flush=True)

    try:
        # Sin parámetro para traer TODOS
        async with httpx.AsyncClient(timeout=600.0) as client:  # 10 min timeout
            response = await client.get(GBP_PARSER_URL, params={
                "strScriptLabel": "scriptItemTaxes"
            })
            response.raise_for_status()
            data = response.json()

        if not isinstance(data, list) or len(data) == 0:
            print("✓ (sin datos)")
            return {"nuevos": 0, "actualizados": 0}

        if len(data) == 1 and "Column1" in data[0]:
            print("⚠️ (sin datos disponibles)")
            return {"nuevos": 0, "actualizados": 0}

        print(f"recibidos {len(data)} registros...", end=" ", flush=True)

        nuevos = 0
        actualizados = 0

        for i, row in enumerate(data):
            comp_id = to_int(row.get("comp_id"))
            item_id = to_int(row.get("item_id"))
            tax_id = to_int(row.get("tax_id"))
            tax_class = to_int(row.get("tax_class"))

            existente = db.query(TBItemTaxes).filter(
                TBItemTaxes.comp_id == comp_id,
                TBItemTaxes.item_id == item_id,
                TBItemTaxes.tax_id == tax_id
            ).first()

            if existente:
                if existente.tax_class != tax_class:
                    existente.tax_class = tax_class
                    actualizados += 1
            else:
                nuevo = TBItemTaxes(
                    comp_id=comp_id,
                    item_id=item_id,
                    tax_id=tax_id,
                    tax_class=tax_class
                )
                db.add(nuevo)
                nuevos += 1

            # Commit cada 500 registros
            if (i + 1) % 500 == 0:
                db.commit()
                print(f"{i+1}...", end=" ", flush=True)

        db.commit()
        print(f"✓ ({nuevos} nuevos, {actualizados} actualizados)")
        return {"nuevos": nuevos, "actualizados": actualizados}

    except Exception as e:
        print(f"❌ Error: {str(e)}")
        db.rollback()
        import traceback
        traceback.print_exc()
        return {"nuevos": 0, "actualizados": 0, "error": str(e)}


async def main_async():
    """Función principal async"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print("=" * 60)
    print(f"SYNC COMPLETO TABLAS MAESTRAS ERP - {timestamp}")
    print("=" * 60)

    db = SessionLocal()
    try:
        # Tablas pequeñas
        await sync_brands(db)
        await sync_categories(db)
        await sync_subcategories(db)
        await sync_tax_names(db)

        # Items - TODOS
        await sync_items_full(db)

        # Impuestos por item - TODOS
        await sync_item_taxes_full(db)

        print("\n" + "=" * 60)
        print("✅ SINCRONIZACIÓN COMPLETA FINALIZADA")
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
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
