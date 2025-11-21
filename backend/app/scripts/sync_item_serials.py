"""
Script para sincronizar tb_item_serials desde el ERP
Ejecutar: python app/scripts/sync_item_serials.py [--full | --incremental]
"""
import sys
from pathlib import Path

# Add backend directory to path
backend_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_dir))

from dotenv import load_dotenv
env_path = backend_dir / '.env'
load_dotenv(dotenv_path=env_path)

import argparse
import asyncio
import httpx
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert

from app.core.database import SessionLocal
from app.models.tb_item_serials import TbItemSerial

# URL del gbp-parser
GBP_PARSER_URL = "http://localhost:8002/api/gbp-parser"


async def fetch_from_erp(params: dict) -> list:
    """Consulta el ERP vía gbp-parser"""
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.get(GBP_PARSER_URL, params=params)
        response.raise_for_status()
        return response.json()


def sync_full(db: Session):
    """Sincronización completa desde el inicio"""
    print("\n🔄 Sincronización COMPLETA de tb_item_serials")
    print("=" * 60)

    # Obtener todos los registros
    params = {
        "strScriptLabel": "scriptItemSerials",
        # Sin filtros para obtener todos
    }

    print(f"📡 Consultando ERP (todos los registros)...")
    data = asyncio.run(fetch_from_erp(params))

    if not data:
        print("⚠️  No se obtuvieron datos del ERP")
        return

    print(f"✓ Obtenidos {len(data)} registros del ERP")

    # Insertar/actualizar en batch
    print("💾 Insertando en base de datos...")

    batch_size = 500
    total_inserted = 0
    total_updated = 0

    for i in range(0, len(data), batch_size):
        batch = data[i:i + batch_size]

        for row in batch:
            # Convertir booleanos
            for bool_field in ['is_available', 'is_IsOwnGeneration', 'is_checked', 'is_printed']:
                if bool_field in row and row[bool_field] is not None:
                    row[bool_field] = bool(row[bool_field])

            # Convertir fechas
            if 'is_cd' in row and row['is_cd']:
                try:
                    row['is_cd'] = datetime.fromisoformat(row['is_cd'].replace('Z', '+00:00'))
                except:
                    row['is_cd'] = None

        # Upsert using PostgreSQL ON CONFLICT
        stmt = insert(TbItemSerial).values(batch)
        stmt = stmt.on_conflict_do_update(
            index_elements=['comp_id', 'is_id', 'bra_id'],
            set_={
                'ct_transaction': stmt.excluded.ct_transaction,
                'it_transaction': stmt.excluded.it_transaction,
                'item_id': stmt.excluded.item_id,
                'stor_id': stmt.excluded.stor_id,
                'is_serial': stmt.excluded.is_serial,
                'is_cd': stmt.excluded.is_cd,
                'is_available': stmt.excluded.is_available,
                'is_guid': stmt.excluded.is_guid,
                'is_IsOwnGeneration': stmt.excluded.is_IsOwnGeneration,
                'is_checked': stmt.excluded.is_checked,
                'is_printed': stmt.excluded.is_printed,
            }
        )

        result = db.execute(stmt)
        db.commit()

        total_inserted += len(batch)
        print(f"  ✓ Procesados {total_inserted}/{len(data)} registros")

    print(f"\n✅ Sincronización completa finalizada")
    print(f"   Total procesado: {total_inserted} registros")


def sync_incremental(db: Session, days_back: int = 7):
    """Sincronización incremental (últimos N días)"""
    print(f"\n🔄 Sincronización INCREMENTAL de tb_item_serials (últimos {days_back} días)")
    print("=" * 60)

    # Fecha desde
    from_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d')
    to_date = datetime.now().strftime('%Y-%m-%d')

    params = {
        "strScriptLabel": "scriptItemSerials",
        "fromDate": from_date,
        "toDate": to_date
    }

    print(f"📡 Consultando ERP (desde {from_date} hasta {to_date})...")
    data = asyncio.run(fetch_from_erp(params))

    if not data:
        print("⚠️  No se obtuvieron datos del ERP")
        return

    print(f"✓ Obtenidos {len(data)} registros del ERP")

    # Insertar/actualizar
    print("💾 Actualizando base de datos...")

    total_updated = 0

    for row in data:
        # Convertir booleanos
        for bool_field in ['is_available', 'is_IsOwnGeneration', 'is_checked', 'is_printed']:
            if bool_field in row and row[bool_field] is not None:
                row[bool_field] = bool(row[bool_field])

        # Convertir fechas
        if 'is_cd' in row and row['is_cd']:
            try:
                row['is_cd'] = datetime.fromisoformat(row['is_cd'].replace('Z', '+00:00'))
            except:
                row['is_cd'] = None

        # Upsert
        stmt = insert(TbItemSerial).values(row)
        stmt = stmt.on_conflict_do_update(
            index_elements=['comp_id', 'is_id', 'bra_id'],
            set_={
                'ct_transaction': stmt.excluded.ct_transaction,
                'it_transaction': stmt.excluded.it_transaction,
                'item_id': stmt.excluded.item_id,
                'stor_id': stmt.excluded.stor_id,
                'is_serial': stmt.excluded.is_serial,
                'is_cd': stmt.excluded.is_cd,
                'is_available': stmt.excluded.is_available,
                'is_guid': stmt.excluded.is_guid,
                'is_IsOwnGeneration': stmt.excluded.is_IsOwnGeneration,
                'is_checked': stmt.excluded.is_checked,
                'is_printed': stmt.excluded.is_printed,
            }
        )

        db.execute(stmt)
        total_updated += 1

        if total_updated % 100 == 0:
            db.commit()
            print(f"  ✓ Procesados {total_updated}/{len(data)} registros")

    db.commit()

    print(f"\n✅ Sincronización incremental finalizada")
    print(f"   Total actualizado: {total_updated} registros")


def main():
    parser = argparse.ArgumentParser(description='Sincronizar tb_item_serials')
    parser.add_argument('--full', action='store_true', help='Sincronización completa')
    parser.add_argument('--incremental', action='store_true', help='Sincronización incremental (últimos 7 días)')
    parser.add_argument('--days', type=int, default=7, help='Días hacia atrás para incremental (default: 7)')

    args = parser.parse_args()

    if not args.full and not args.incremental:
        print("❌ Debe especificar --full o --incremental")
        sys.exit(1)

    db = SessionLocal()

    try:
        if args.full:
            sync_full(db)
        else:
            sync_incremental(db, args.days)

    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
