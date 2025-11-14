"""
Script para sincronizar tablas maestras del ERP desde SQL Server a PostgreSQL

Ejecutar:
    python app/scripts/sync_erp_master_tables.py
"""
import sys
from pathlib import Path

# Add backend directory to path
backend_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_dir))

import pyodbc
import os
from sqlalchemy.orm import Session
from dotenv import load_dotenv

from app.core.database import SessionLocal
from app.models.tb_brand import TBBrand
from app.models.tb_category import TBCategory
from app.models.tb_subcategory import TBSubCategory
from app.models.tb_item import TBItem
from app.models.tb_tax_name import TBTaxName
from app.models.tb_item_taxes import TBItemTaxes

# Load environment variables
load_dotenv()

# SQL Server connection
SQL_SERVER_HOST = os.getenv("SQL_SERVER_HOST")
SQL_SERVER_DB = os.getenv("SQL_SERVER_DB")
SQL_SERVER_USER = os.getenv("SQL_SERVER_USER")
SQL_SERVER_PASSWORD = os.getenv("SQL_SERVER_PASSWORD")

def get_sql_server_connection():
    """Conectar a SQL Server"""
    conn_str = (
        f"DRIVER={{ODBC Driver 17 for SQL Server}};"
        f"SERVER={SQL_SERVER_HOST};"
        f"DATABASE={SQL_SERVER_DB};"
        f"UID={SQL_SERVER_USER};"
        f"PWD={SQL_SERVER_PASSWORD};"
        f"TrustServerCertificate=yes;"
    )
    return pyodbc.connect(conn_str, timeout=30)


def sync_brands(db_pg: Session):
    """Sincronizar tabla de marcas"""
    print("\n📦 Sincronizando Marcas...")

    conn_sql = get_sql_server_connection()
    cursor = conn_sql.cursor()

    query = "SELECT comp_id, brand_id, brand_desc, brand_code FROM tbBrand"
    cursor.execute(query)

    total = 0
    for row in cursor:
        comp_id, brand_id, brand_desc, brand_code = row

        # Verificar si existe
        existente = db_pg.query(TBBrand).filter(
            TBBrand.comp_id == comp_id,
            TBBrand.brand_id == brand_id
        ).first()

        if existente:
            existente.brand_desc = brand_desc
            existente.brand_code = brand_code
        else:
            nueva = TBBrand(
                comp_id=comp_id,
                brand_id=brand_id,
                brand_desc=brand_desc,
                brand_code=brand_code
            )
            db_pg.add(nueva)

        total += 1
        if total % 100 == 0:
            db_pg.commit()
            print(f"  Procesadas: {total}")

    db_pg.commit()
    cursor.close()
    conn_sql.close()
    print(f"  ✅ Total marcas sincronizadas: {total}")


def sync_categories(db_pg: Session):
    """Sincronizar tabla de categorías"""
    print("\n📦 Sincronizando Categorías...")

    conn_sql = get_sql_server_connection()
    cursor = conn_sql.cursor()

    query = "SELECT comp_id, cat_id, cat_desc, cat_code FROM tbCategory"
    cursor.execute(query)

    total = 0
    for row in cursor:
        comp_id, cat_id, cat_desc, cat_code = row

        existente = db_pg.query(TBCategory).filter(
            TBCategory.comp_id == comp_id,
            TBCategory.cat_id == cat_id
        ).first()

        if existente:
            existente.cat_desc = cat_desc
            existente.cat_code = cat_code
        else:
            nueva = TBCategory(
                comp_id=comp_id,
                cat_id=cat_id,
                cat_desc=cat_desc,
                cat_code=cat_code
            )
            db_pg.add(nueva)

        total += 1
        if total % 100 == 0:
            db_pg.commit()
            print(f"  Procesadas: {total}")

    db_pg.commit()
    cursor.close()
    conn_sql.close()
    print(f"  ✅ Total categorías sincronizadas: {total}")


def sync_subcategories(db_pg: Session):
    """Sincronizar tabla de subcategorías"""
    print("\n📦 Sincronizando Subcategorías...")

    conn_sql = get_sql_server_connection()
    cursor = conn_sql.cursor()

    query = "SELECT comp_id, cat_id, subcat_id, subcat_desc, subcat_code FROM tbSubCategory"
    cursor.execute(query)

    total = 0
    for row in cursor:
        comp_id, cat_id, subcat_id, subcat_desc, subcat_code = row

        existente = db_pg.query(TBSubCategory).filter(
            TBSubCategory.comp_id == comp_id,
            TBSubCategory.cat_id == cat_id,
            TBSubCategory.subcat_id == subcat_id
        ).first()

        if existente:
            existente.subcat_desc = subcat_desc
            existente.subcat_code = subcat_code
        else:
            nueva = TBSubCategory(
                comp_id=comp_id,
                cat_id=cat_id,
                subcat_id=subcat_id,
                subcat_desc=subcat_desc,
                subcat_code=subcat_code
            )
            db_pg.add(nueva)

        total += 1
        if total % 100 == 0:
            db_pg.commit()
            print(f"  Procesadas: {total}")

    db_pg.commit()
    cursor.close()
    conn_sql.close()
    print(f"  ✅ Total subcategorías sincronizadas: {total}")


def sync_items(db_pg: Session):
    """Sincronizar tabla de items"""
    print("\n📦 Sincronizando Items...")

    conn_sql = get_sql_server_connection()
    cursor = conn_sql.cursor()

    query = """
        SELECT comp_id, item_id, item_code, item_desc,
               cat_id, subcat_id, brand_id, item_liquidation,
               item_active, item_cd, item_chd
        FROM tbItem
    """
    cursor.execute(query)

    total = 0
    for row in cursor:
        (comp_id, item_id, item_code, item_desc, cat_id, subcat_id,
         brand_id, item_liquidation, item_active, created_at, updated_at) = row

        existente = db_pg.query(TBItem).filter(
            TBItem.comp_id == comp_id,
            TBItem.item_id == item_id
        ).first()

        if existente:
            existente.item_code = item_code
            existente.item_desc = item_desc
            existente.cat_id = cat_id
            existente.subcat_id = subcat_id
            existente.brand_id = brand_id
            existente.item_liquidation = item_liquidation
            existente.item_active = item_active
            existente.updated_at = updated_at
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
                item_active=item_active,
                created_at=created_at,
                updated_at=updated_at
            )
            db_pg.add(nuevo)

        total += 1
        if total % 500 == 0:
            db_pg.commit()
            print(f"  Procesados: {total}")

    db_pg.commit()
    cursor.close()
    conn_sql.close()
    print(f"  ✅ Total items sincronizados: {total}")


def sync_tax_names(db_pg: Session):
    """Sincronizar nombres de impuestos"""
    print("\n📦 Sincronizando Nombres de Impuestos...")

    conn_sql = get_sql_server_connection()
    cursor = conn_sql.cursor()

    query = "SELECT comp_id, tax_id, tax_name, tax_desc FROM tbTaxName"
    cursor.execute(query)

    total = 0
    for row in cursor:
        comp_id, tax_id, tax_name, tax_desc = row

        existente = db_pg.query(TBTaxName).filter(
            TBTaxName.comp_id == comp_id,
            TBTaxName.tax_id == tax_id
        ).first()

        if existente:
            existente.tax_name = tax_name
            existente.tax_desc = tax_desc
        else:
            nuevo = TBTaxName(
                comp_id=comp_id,
                tax_id=tax_id,
                tax_name=tax_name,
                tax_desc=tax_desc
            )
            db_pg.add(nuevo)

        total += 1

    db_pg.commit()
    cursor.close()
    conn_sql.close()
    print(f"  ✅ Total impuestos sincronizados: {total}")


def sync_item_taxes(db_pg: Session):
    """Sincronizar impuestos por item"""
    print("\n📦 Sincronizando Impuestos por Item...")

    conn_sql = get_sql_server_connection()
    cursor = conn_sql.cursor()

    query = "SELECT comp_id, item_id, tax_id, tax_percentage FROM tbItemTaxes"
    cursor.execute(query)

    total = 0
    for row in cursor:
        comp_id, item_id, tax_id, tax_percentage = row

        existente = db_pg.query(TBItemTaxes).filter(
            TBItemTaxes.comp_id == comp_id,
            TBItemTaxes.item_id == item_id,
            TBItemTaxes.tax_id == tax_id
        ).first()

        if existente:
            existente.tax_percentage = tax_percentage
        else:
            nuevo = TBItemTaxes(
                comp_id=comp_id,
                item_id=item_id,
                tax_id=tax_id,
                tax_percentage=tax_percentage
            )
            db_pg.add(nuevo)

        total += 1
        if total % 500 == 0:
            db_pg.commit()
            print(f"  Procesados: {total}")

    db_pg.commit()
    cursor.close()
    conn_sql.close()
    print(f"  ✅ Total impuestos de items sincronizados: {total}")


def main():
    print("="*60)
    print("SINCRONIZACIÓN DE TABLAS MAESTRAS DEL ERP")
    print("="*60)

    db = SessionLocal()
    try:
        sync_brands(db)
        sync_categories(db)
        sync_subcategories(db)
        sync_tax_names(db)
        sync_items(db)
        sync_item_taxes(db)

        print("\n" + "="*60)
        print("✅ SINCRONIZACIÓN COMPLETADA")
        print("="*60)
    except Exception as e:
        print(f"\n❌ Error durante la sincronización: {str(e)}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
