"""
Script INCREMENTAL para sincronizar tablas maestras del ERP desde SQL Server a PostgreSQL
Diseñado para ejecutarse cada 10 minutos en cron

Tablas sincronizadas:
- tbBrand (marcas) - sync completo (pocas filas)
- tbCategory (categorías) - sync completo (pocas filas)
- tbSubCategory (subcategorías) - sync completo (pocas filas)
- tbTaxName (impuestos) - sync completo (pocas filas)
- tbItem (items) - INCREMENTAL por item_LastUpdate
- tbItemTaxes (impuestos por item) - sync de items nuevos/actualizados

Ejecutar:
    python -m app.scripts.sync_erp_master_tables_incremental
    python -m app.scripts.sync_erp_master_tables_incremental --minutes 30
"""
import sys
import argparse
from pathlib import Path
from datetime import datetime, timedelta

# Add backend directory to path
backend_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_dir))

import pymssql
import os
from sqlalchemy.orm import Session
from sqlalchemy import text
from dotenv import load_dotenv

from app.core.database import SessionLocal
from app.models.tb_brand import TBBrand
from app.models.tb_category import TBCategory
from app.models.tb_subcategory import TBSubCategory
from app.models.tb_item import TBItem
from app.models.tb_tax_name import TBTaxName
from app.models.tb_item_taxes import TBItemTaxes

# Load environment variables
env_path = backend_dir / '.env'
load_dotenv(dotenv_path=env_path)

# SQL Server connection
SQL_SERVER_HOST = os.getenv("SQL_SERVER_HOST")
SQL_SERVER_DB = os.getenv("SQL_SERVER_DB")
SQL_SERVER_USER = os.getenv("SQL_SERVER_USER")
SQL_SERVER_PASSWORD = os.getenv("SQL_SERVER_PASSWORD")


def get_sql_server_connection():
    """Conectar a SQL Server"""
    return pymssql.connect(
        server=SQL_SERVER_HOST,
        database=SQL_SERVER_DB,
        user=SQL_SERVER_USER,
        password=SQL_SERVER_PASSWORD,
        timeout=60
    )


def sync_brands(db_pg: Session):
    """Sincronizar tabla de marcas (completo - pocas filas)"""
    print("  📦 Marcas...", end=" ", flush=True)

    conn_sql = get_sql_server_connection()
    cursor = conn_sql.cursor()

    query = "SELECT comp_id, brand_id, bra_id, brand_desc FROM tbBrand"
    cursor.execute(query)

    nuevos = 0
    actualizados = 0
    for row in cursor:
        comp_id, brand_id, bra_id, brand_desc = row

        existente = db_pg.query(TBBrand).filter(
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
            db_pg.add(nueva)
            nuevos += 1

    db_pg.commit()
    cursor.close()
    conn_sql.close()
    print(f"✓ ({nuevos} nuevos, {actualizados} actualizados)")
    return {"nuevos": nuevos, "actualizados": actualizados}


def sync_categories(db_pg: Session):
    """Sincronizar tabla de categorías (completo - pocas filas)"""
    print("  📦 Categorías...", end=" ", flush=True)

    conn_sql = get_sql_server_connection()
    cursor = conn_sql.cursor()

    query = "SELECT comp_id, cat_id, cat_desc FROM tbCategory"
    cursor.execute(query)

    nuevos = 0
    actualizados = 0
    for row in cursor:
        comp_id, cat_id, cat_desc = row

        existente = db_pg.query(TBCategory).filter(
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
            db_pg.add(nueva)
            nuevos += 1

    db_pg.commit()
    cursor.close()
    conn_sql.close()
    print(f"✓ ({nuevos} nuevos, {actualizados} actualizados)")
    return {"nuevos": nuevos, "actualizados": actualizados}


def sync_subcategories(db_pg: Session):
    """Sincronizar tabla de subcategorías (completo - pocas filas)"""
    print("  📦 Subcategorías...", end=" ", flush=True)

    conn_sql = get_sql_server_connection()
    cursor = conn_sql.cursor()

    query = "SELECT comp_id, cat_id, subcat_id, subcat_desc FROM tbSubCategory"
    cursor.execute(query)

    nuevos = 0
    actualizados = 0
    for row in cursor:
        comp_id, cat_id, subcat_id, subcat_desc = row

        existente = db_pg.query(TBSubCategory).filter(
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
            db_pg.add(nueva)
            nuevos += 1

    db_pg.commit()
    cursor.close()
    conn_sql.close()
    print(f"✓ ({nuevos} nuevos, {actualizados} actualizados)")
    return {"nuevos": nuevos, "actualizados": actualizados}


def sync_tax_names(db_pg: Session):
    """Sincronizar nombres de impuestos (completo - pocas filas)"""
    print("  📦 Impuestos...", end=" ", flush=True)

    conn_sql = get_sql_server_connection()
    cursor = conn_sql.cursor()

    query = "SELECT comp_id, tax_id, tax_desc, tax_percentage FROM tbTaxName"
    cursor.execute(query)

    nuevos = 0
    actualizados = 0
    for row in cursor:
        comp_id, tax_id, tax_desc, tax_percentage = row

        existente = db_pg.query(TBTaxName).filter(
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
            db_pg.add(nuevo)
            nuevos += 1

    db_pg.commit()
    cursor.close()
    conn_sql.close()
    print(f"✓ ({nuevos} nuevos, {actualizados} actualizados)")
    return {"nuevos": nuevos, "actualizados": actualizados}


def sync_items_incremental(db_pg: Session, minutes: int = 15):
    """
    Sincronizar items INCREMENTALMENTE
    Solo trae items con item_LastUpdate en los últimos X minutos
    """
    print(f"  📦 Items (últimos {minutes} min)...", end=" ", flush=True)

    conn_sql = get_sql_server_connection()
    cursor = conn_sql.cursor()

    # Calcular fecha límite
    fecha_limite = datetime.now() - timedelta(minutes=minutes)

    # Query incremental - solo items actualizados recientemente
    # También incluye items que no existen en PostgreSQL (por si se perdieron)
    query = """
        SELECT comp_id, item_id, item_code, item_desc,
               cat_id, subcat_id, brand_id, item_liquidation,
               item_cd, item_LastUpdate
        FROM tbItem
        WHERE item_LastUpdate >= %s
           OR item_cd >= %s
    """
    cursor.execute(query, (fecha_limite, fecha_limite))

    nuevos = 0
    actualizados = 0
    items_procesados = []

    for row in cursor:
        (comp_id, item_id, item_code, item_desc, cat_id, subcat_id,
         brand_id, item_liquidation, item_cd, item_LastUpdate) = row

        items_procesados.append(item_id)

        existente = db_pg.query(TBItem).filter(
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
            db_pg.add(nuevo)
            nuevos += 1

    db_pg.commit()
    cursor.close()
    conn_sql.close()
    print(f"✓ ({nuevos} nuevos, {actualizados} actualizados)")
    return {"nuevos": nuevos, "actualizados": actualizados, "items": items_procesados}


def sync_item_taxes_for_items(db_pg: Session, item_ids: list):
    """
    Sincronizar impuestos solo para los items que se actualizaron
    """
    if not item_ids:
        print("  📦 Impuestos por item... ✓ (sin items nuevos)")
        return {"nuevos": 0, "actualizados": 0}

    print(f"  📦 Impuestos por item ({len(item_ids)} items)...", end=" ", flush=True)

    conn_sql = get_sql_server_connection()
    cursor = conn_sql.cursor()

    # Solo traer impuestos de los items actualizados
    placeholders = ','.join(['%s'] * len(item_ids))
    query = f"SELECT comp_id, item_id, tax_id, tax_class FROM tbItemTaxes WHERE item_id IN ({placeholders})"
    cursor.execute(query, tuple(item_ids))

    nuevos = 0
    actualizados = 0
    for row in cursor:
        comp_id, item_id, tax_id, tax_class = row

        existente = db_pg.query(TBItemTaxes).filter(
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
            db_pg.add(nuevo)
            nuevos += 1

    db_pg.commit()
    cursor.close()
    conn_sql.close()
    print(f"✓ ({nuevos} nuevos, {actualizados} actualizados)")
    return {"nuevos": nuevos, "actualizados": actualizados}


def verificar_items_faltantes(db_pg: Session):
    """
    Verifica si hay items en ventas ML que no existen en tb_item
    y los sincroniza si es necesario
    """
    print("  🔍 Verificando items faltantes...", end=" ", flush=True)

    # Buscar item_ids que están en ventas pero no en tb_item
    query = text("""
        SELECT DISTINCT tmlod.item_id
        FROM tb_mercadolibre_orders_detail tmlod
        LEFT JOIN tb_item ti ON ti.item_id = tmlod.item_id
        WHERE ti.item_id IS NULL
          AND tmlod.item_id IS NOT NULL
        LIMIT 100
    """)

    result = db_pg.execute(query)
    items_faltantes = [row[0] for row in result.fetchall()]

    if not items_faltantes:
        print("✓ (ninguno)")
        return {"sincronizados": 0}

    print(f"encontrados {len(items_faltantes)}", end=" ", flush=True)

    # Sincronizar estos items específicos desde SQL Server
    conn_sql = get_sql_server_connection()
    cursor = conn_sql.cursor()

    placeholders = ','.join(['%s'] * len(items_faltantes))
    query = f"""
        SELECT comp_id, item_id, item_code, item_desc,
               cat_id, subcat_id, brand_id, item_liquidation,
               item_cd, item_LastUpdate
        FROM tbItem
        WHERE item_id IN ({placeholders})
    """
    cursor.execute(query, tuple(items_faltantes))

    sincronizados = 0
    items_sync = []
    for row in cursor:
        (comp_id, item_id, item_code, item_desc, cat_id, subcat_id,
         brand_id, item_liquidation, item_cd, item_LastUpdate) = row

        # Verificar que no exista (doble check)
        existente = db_pg.query(TBItem).filter(
            TBItem.comp_id == comp_id,
            TBItem.item_id == item_id
        ).first()

        if not existente:
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
            db_pg.add(nuevo)
            items_sync.append(item_id)
            sincronizados += 1

    db_pg.commit()
    cursor.close()
    conn_sql.close()

    # Sincronizar impuestos de estos items
    if items_sync:
        sync_item_taxes_for_items(db_pg, items_sync)

    print(f"✓ ({sincronizados} sincronizados)")
    return {"sincronizados": sincronizados}


def main():
    parser = argparse.ArgumentParser(description='Sync incremental de tablas maestras ERP')
    parser.add_argument('--minutes', type=int, default=15,
                        help='Minutos hacia atrás para buscar cambios (default: 15)')
    args = parser.parse_args()

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print("=" * 60)
    print(f"SYNC INCREMENTAL TABLAS MAESTRAS ERP - {timestamp}")
    print("=" * 60)

    db = SessionLocal()
    try:
        # Tablas pequeñas - sync completo (rápido)
        sync_brands(db)
        sync_categories(db)
        sync_subcategories(db)
        sync_tax_names(db)

        # Items - sync incremental
        result_items = sync_items_incremental(db, minutes=args.minutes)

        # Impuestos de items actualizados
        sync_item_taxes_for_items(db, result_items.get("items", []))

        # Verificar items faltantes (por si hay ventas de items que no sincronizamos)
        verificar_items_faltantes(db)

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


if __name__ == "__main__":
    main()
