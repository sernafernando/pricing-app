#!/usr/bin/env python3
"""
Script rápido para ver columnas de una tabla
"""
import sys
from pathlib import Path

backend_dir = Path(__file__).parent
sys.path.insert(0, str(backend_dir))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import text
from app.core.database import SessionLocal

def check_columns(table_name):
    db = SessionLocal()
    try:
        cols = db.execute(text(f"""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns 
            WHERE table_name = '{table_name}'
            ORDER BY ordinal_position
        """)).fetchall()
        
        print(f"\nColumnas en {table_name}:")
        print("-" * 60)
        for col in cols:
            print(f"  {col[0]:<40} {col[1]:<20} {'NULL' if col[2]=='YES' else 'NOT NULL'}")
        print(f"\nTotal: {len(cols)} columnas")
    finally:
        db.close()

if __name__ == "__main__":
    tables = [
        'tb_sale_order_header',
        'tb_sale_order_detail',
        'tb_commercial_transactions'
    ]
    
    for table in tables:
        check_columns(table)
