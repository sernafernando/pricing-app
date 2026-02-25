"""
Script para sincronizar tb_sale_order_serials desde el ERP (tbSaleOrderSerials)

Modos de uso:
    # Incremental automático (desde último sose_id en DB)
    python -m app.scripts.sync_sale_order_serials --incremental

    # Incremental desde un ID específico
    python -m app.scripts.sync_sale_order_serials --incremental --from-id 150000

    # Full completo (por rangos de sose_id)
    python -m app.scripts.sync_sale_order_serials --full
    python -m app.scripts.sync_sale_order_serials --full --max-id 300000 --batch-size 5000

    # Por sale order específico
    python -m app.scripts.sync_sale_order_serials --soh-id 853

    # Por item serial específico
    python -m app.scripts.sync_sale_order_serials --is-id 8102
"""

import sys
from pathlib import Path

# Add backend directory to path
backend_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_dir))

from dotenv import load_dotenv

env_path = backend_dir / ".env"
load_dotenv(dotenv_path=env_path)

import argparse
import asyncio
import httpx
from sqlalchemy import func
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert

from app.core.database import SessionLocal
from app.models.tb_sale_order_serial import TbSaleOrderSerial

# URL del gbp-parser
GBP_PARSER_URL = "http://localhost:8002/api/gbp-parser"

VALID_FIELDS = {"comp_id", "is_id", "sose_id", "bra_id", "soh_id", "sose_guid"}

UPDATE_FIELDS = {"is_id", "soh_id", "sose_guid"}


async def fetch_from_erp(params: dict) -> list:
    """Consulta el ERP vía gbp-parser"""
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.get(GBP_PARSER_URL, params=params)
        response.raise_for_status()
        return response.json()


def normalize_row(row: dict) -> dict | None:
    """Normaliza y filtra una fila del ERP. Retorna None si la PK es inválida."""
    if not row.get("comp_id") or not row.get("bra_id") or not row.get("sose_id"):
        return None
    return {k: v for k, v in row.items() if k in VALID_FIELDS}


def upsert_batch(db: Session, rows: list[dict]) -> None:
    """Upsert de un batch de filas en tb_sale_order_serials."""
    stmt = insert(TbSaleOrderSerial)
    stmt = stmt.on_conflict_do_update(
        index_elements=["comp_id", "bra_id", "sose_id"],
        set_={field: stmt.excluded[field] for field in UPDATE_FIELDS},
    )
    db.execute(stmt, rows)
    db.commit()


def get_max_sose_id(db: Session) -> int:
    """Obtiene el máximo sose_id en la DB local."""
    result = db.query(func.max(TbSaleOrderSerial.sose_id)).scalar()
    return result or 0


def sync_full(db: Session, batch_size: int = 10000, max_sose_id: int = 200000) -> None:
    """Sincronización completa por rangos de sose_id"""
    print("\n🔄 Sincronización COMPLETA de tb_sale_order_serials (por rangos de sose_id)")
    print("=" * 60)
    print(f"Tamaño de lote: {batch_size} registros")
    print(f"Rango máximo: hasta sose_id={max_sose_id}")
    print()

    current_from = 1
    total_procesado = 0
    batch_num = 1

    while current_from < max_sose_id:
        current_to = current_from + batch_size - 1
        if current_to > max_sose_id:
            current_to = max_sose_id

        print(f"📦 Lote #{batch_num} (sose_id: {current_from} - {current_to})...")

        params = {
            "strScriptLabel": "scriptSaleOrderSerials",
            "soseIDfrom": current_from,
            "soseIDto": current_to,
        }

        try:
            data = asyncio.run(fetch_from_erp(params))

            if not data or len(data) == 0:
                print("   ⚠️  Sin registros en este rango")
            else:
                print(f"   ✓ Obtenidos {len(data)} registros")

                normalized_data = []
                for row in data:
                    normalized = normalize_row(row)
                    if normalized:
                        normalized_data.append(normalized)

                # Procesar en sub-batches para INSERT
                insert_batch_size = 500
                for i in range(0, len(normalized_data), insert_batch_size):
                    batch = normalized_data[i : i + insert_batch_size]
                    upsert_batch(db, batch)

                total_procesado += len(normalized_data)
                print(f"   💾 Insertados en DB (Total acumulado: {total_procesado})")

        except httpx.HTTPStatusError as e:
            print(f"   ❌ Error HTTP: {e.response.status_code} - {e.response.text[:200]}")
        except Exception as e:
            print(f"   ❌ Error: {str(e)}")
            import traceback

            traceback.print_exc()

        # Avanzar al siguiente rango
        current_from = current_to + 1
        batch_num += 1

    print("\n✅ Sincronización completa finalizada")
    print(f"   Total procesado: {total_procesado} registros")


def sync_incremental(db: Session, from_id: int | None = None) -> None:
    """Sincronización incremental desde el último sose_id en la DB (o desde from_id)"""
    last_sose_id = from_id if from_id is not None else get_max_sose_id(db)

    print(f"\n🔄 Sincronización INCREMENTAL de tb_sale_order_serials (desde sose_id > {last_sose_id})")
    print("=" * 60)

    params = {
        "strScriptLabel": "scriptSaleOrderSerials",
        "soseID": last_sose_id,
    }

    print(f"📡 Consultando ERP (sose_id > {last_sose_id})...")
    data = asyncio.run(fetch_from_erp(params))

    if not data:
        print("⚠️  No se obtuvieron datos del ERP (sin registros nuevos)")
        return

    print(f"✓ Obtenidos {len(data)} registros del ERP")
    print("💾 Actualizando base de datos...")

    normalized_data = []
    for row in data:
        normalized = normalize_row(row)
        if normalized:
            normalized_data.append(normalized)

    # Procesar en batches
    insert_batch_size = 500
    total_procesado = 0
    for i in range(0, len(normalized_data), insert_batch_size):
        batch = normalized_data[i : i + insert_batch_size]
        upsert_batch(db, batch)
        total_procesado += len(batch)
        print(f"  ✓ Procesados {total_procesado}/{len(normalized_data)} registros")

    print("\n✅ Sincronización incremental finalizada")
    print(f"   Total actualizado: {total_procesado} registros")


def sync_by_filter(db: Session, filter_name: str, filter_value: int) -> None:
    """Sincronización por filtro específico (soh_id o is_id)"""
    label = "sale order" if filter_name == "sohID" else "item serial"
    print(f"\n🔄 Sincronización por {label} ({filter_name}={filter_value})")
    print("=" * 60)

    params = {
        "strScriptLabel": "scriptSaleOrderSerials",
        filter_name: filter_value,
    }

    print(f"📡 Consultando ERP ({filter_name}={filter_value})...")
    data = asyncio.run(fetch_from_erp(params))

    if not data:
        print(f"⚠️  No se encontraron registros para {filter_name}={filter_value}")
        return

    print(f"✓ Obtenidos {len(data)} registros del ERP")
    print("💾 Actualizando base de datos...")

    normalized_data = []
    for row in data:
        normalized = normalize_row(row)
        if normalized:
            normalized_data.append(normalized)

    if not normalized_data:
        print("⚠️  Ningún registro válido para insertar")
        return

    upsert_batch(db, normalized_data)

    print(f"\n✅ Sincronización por {label} finalizada")
    print(f"   Total actualizado: {len(normalized_data)} registros")


def main() -> None:
    parser = argparse.ArgumentParser(description="Sincronizar tb_sale_order_serials")

    # Modos de ejecución
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--full", action="store_true", help="Sincronización completa por rangos de sose_id")
    mode.add_argument("--incremental", action="store_true", help="Incremental desde último sose_id en DB")
    mode.add_argument("--soh-id", type=int, help="Sincronizar serials de un sale order específico")
    mode.add_argument("--is-id", type=int, help="Sincronizar registros de un item serial específico")

    # Opciones para full
    parser.add_argument("--batch-size", type=int, default=10000, help="Tamaño de lote para full (default: 10000)")
    parser.add_argument("--max-id", type=int, default=200000, help="ID máximo para full (default: 200000)")

    # Opciones para incremental
    parser.add_argument(
        "--from-id", type=int, default=None, help="Forzar sose_id inicial para incremental (override auto-detect)"
    )

    args = parser.parse_args()

    db = SessionLocal()

    try:
        if args.full:
            sync_full(db, batch_size=args.batch_size, max_sose_id=args.max_id)
        elif args.incremental:
            sync_incremental(db, from_id=args.from_id)
        elif args.soh_id:
            sync_by_filter(db, "sohID", args.soh_id)
        elif args.is_id:
            sync_by_filter(db, "isID", args.is_id)

    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
