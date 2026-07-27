"""
Debug: Verificar si el item 3984 existe en tb_item local y en SQL Server
"""
import sys
from pathlib import Path

backend_dir = Path(__file__).parent
sys.path.insert(0, str(backend_dir))

from dotenv import load_dotenv
env_path = backend_dir / '.env'
load_dotenv(dotenv_path=env_path)

import os
import pymssql
from sqlalchemy import text
from app.core.database import SessionLocal

db = SessionLocal()

# Verificar en PostgreSQL local
print("=" * 80)
print("VERIFICACIÓN EN POSTGRESQL LOCAL")
print("=" * 80)

query_pg = text("""
SELECT
    ti.item_id,
    ti.comp_id,
    ti.item_code,
    ti.item_desc,
    ti.cat_id,
    ti.subcat_id,
    ti.brand_id
FROM tb_item ti
WHERE ti.item_id = 3984
""")

result = db.execute(query_pg)
row = result.fetchone()

if row:
    print(f"✓ Item encontrado en tb_item PostgreSQL:")
    print(f"  item_id: {row.item_id}")
    print(f"  comp_id: {row.comp_id}")
    print(f"  item_code: {row.item_code}")
    print(f"  item_desc: {row.item_desc[:50] if row.item_desc else None}...")
    print(f"  cat_id: {row.cat_id}")
    print(f"  subcat_id: {row.subcat_id}")
    print(f"  brand_id: {row.brand_id}")
else:
    print("✗ Item NO encontrado en tb_item PostgreSQL")

# Contar total de items en tb_item
count_pg = db.execute(text("SELECT COUNT(*) FROM tb_item")).fetchone()[0]
print(f"\nTotal items en tb_item PostgreSQL: {count_pg}")

db.close()

# Verificar en SQL Server
print("\n" + "=" * 80)
print("VERIFICACIÓN EN SQL SERVER (ERP)")
print("=" * 80)

SQL_SERVER_HOST = os.getenv("SQL_SERVER_HOST")
SQL_SERVER_DB = os.getenv("SQL_SERVER_DB")
SQL_SERVER_USER = os.getenv("SQL_SERVER_USER")
SQL_SERVER_PASSWORD = os.getenv("SQL_SERVER_PASSWORD")

conn_sql = pymssql.connect(
    server=SQL_SERVER_HOST,
    database=SQL_SERVER_DB,
    user=SQL_SERVER_USER,
    password=SQL_SERVER_PASSWORD,
    timeout=30
)
cursor = conn_sql.cursor()

cursor.execute("""
SELECT
    item_id,
    comp_id,
    item_code,
    item_desc,
    cat_id,
    subcat_id,
    brand_id,
    item_cd,
    item_LastUpdate
FROM tbItem
WHERE item_id = 3984
""")

row = cursor.fetchone()

if row:
    print(f"✓ Item encontrado en tbItem SQL Server:")
    print(f"  item_id: {row[0]}")
    print(f"  comp_id: {row[1]}")
    print(f"  item_code: {row[2]}")
    print(f"  item_desc: {row[3][:50] if row[3] else None}...")
    print(f"  cat_id: {row[4]}")
    print(f"  subcat_id: {row[5]}")
    print(f"  brand_id: {row[6]}")
    print(f"  item_cd: {row[7]}")
    print(f"  item_LastUpdate: {row[8]}")
else:
    print("✗ Item NO encontrado en tbItem SQL Server")

# Contar total de items en tbItem
cursor.execute("SELECT COUNT(*) FROM tbItem")
count_sql = cursor.fetchone()[0]
print(f"\nTotal items en tbItem SQL Server: {count_sql}")

cursor.close()
conn_sql.close()

print("\n" + "=" * 80)
print("COMPARACIÓN")
print("=" * 80)
print(f"PostgreSQL: {count_pg} items")
print(f"SQL Server: {count_sql} items")
if count_pg != count_sql:
    print(f"⚠️ DIFERENCIA: {count_sql - count_pg} items no sincronizados")
