"""
Script para sincronizar tb_rma_add_items desde el ERP (tbRMA_AddItems)

Modos de uso:
    # Full - toda la tabla del ERP (paginado por cursor)
    python -m app.scripts.sync_rma_add_items --full

    # Incremental automático (desde último rmaai_id en DB)
    python -m app.scripts.sync_rma_add_items --incremental

    # Incremental desde un ID específico
    python -m app.scripts.sync_rma_add_items --incremental --from-id 500

    # Por RMA header específico
    python -m app.scripts.sync_rma_add_items --rmah-id 320

    # Por RMA detail específico
    python -m app.scripts.sync_rma_add_items --rmad-id 83579
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
from app.models.tb_rma_add_items import TbRMAAddItems

# URL del gbp-parser
GBP_PARSER_URL = "http://localhost:8002/api/gbp-parser"

VALID_FIELDS = {
    "comp_id",
    "rmah_id",
    "rmad_id",
    "rmaai_id",
    "item_id",
    "rmaai_qty",
    "rmaai_price",
    "curr_id",
}

PK_FIELDS = {"comp_id", "rmah_id", "rmad_id", "rmaai_id"}

UPDATE_FIELDS = VALID_FIELDS - PK_FIELDS


def is_erp_error(data: list) -> bool:
    """Detecta respuestas de error del ERP (ej: [{"Column1":"-9"}])"""
    if len(data) == 1 and isinstance(data[0], dict):
        first = data[0]
        if "Column1" in first:
            try:
                return int(first["Column1"]) < 0
            except (ValueError, TypeError):
                return False
        if not any(field in first for field in VALID_FIELDS):
            return True
    return False


async def fetch_from_erp(params: dict) -> list:
    """Consulta el ERP vía gbp-parser. Retorna lista vacía si el ERP devuelve error."""
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.get(GBP_PARSER_URL, params=params)
        response.raise_for_status()
        data = response.json()
        if not data or not isinstance(data, list) or is_erp_error(data):
            return []
        return data


def clean_value(value: str | None) -> str | None:
    """Limpia valores vacíos o whitespace-only del ERP."""
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped if stripped else None
    return value


def normalize_row(row: dict) -> dict | None:
    """Normaliza y filtra una fila del ERP. Retorna None si la PK es inválida."""
    if not row.get("comp_id") or not row.get("rmah_id") or not row.get("rmad_id") or not row.get("rmaai_id"):
        return None
    cleaned = {}
    for k, v in row.items():
        if k in VALID_FIELDS:
            cleaned[k] = clean_value(v)
    return cleaned


def upsert_batch(db: Session, rows: list[dict]) -> None:
    """Upsert de un batch de filas en tb_rma_add_items."""
    stmt = insert(TbRMAAddItems)
    stmt = stmt.on_conflict_do_update(
        index_elements=["comp_id", "rmah_id", "rmad_id", "rmaai_id"],
        set_={field: stmt.excluded[field] for field in UPDATE_FIELDS},
    )
    db.execute(stmt, rows)
    db.commit()


def get_max_rmaai_id(db: Session) -> int:
    """Obtiene el máximo rmaai_id en la DB local."""
    result = db.query(func.max(TbRMAAddItems.rmaai_id)).scalar()
    return result or 0


def sync_full(db: Session) -> None:
    """Sincronización completa usando cursor por rmaai_id (rmaai_id > X)"""
    print("\n🔄 Sincronización COMPLETA de tb_rma_add_items")
    print("=" * 60)

    cursor = 0
    total_procesado = 0
    batch_num = 1

    while True:
        print(f"📦 Lote #{batch_num} (rmaai_id > {cursor})...")

        params = {
            "strScriptLabel": "scriptRMAAddItems",
            "rmaaiID": cursor,
        }

        try:
            data = asyncio.run(fetch_from_erp(params))

            if not data:
                print("   ✓ Sin más registros")
                break

            print(f"   ✓ Obtenidos {len(data)} registros")

            normalized_data = []
            for row in data:
                normalized = normalize_row(row)
                if normalized:
                    normalized_data.append(normalized)

            if not normalized_data:
                break

            for i in range(0, len(normalized_data), 500):
                batch = normalized_data[i : i + 500]
                upsert_batch(db, batch)

            total_procesado += len(normalized_data)
            print(f"   💾 Insertados en DB (Total acumulado: {total_procesado})")

            max_id_in_batch = max(row["rmaai_id"] for row in normalized_data)
            if max_id_in_batch == cursor:
                break
            cursor = max_id_in_batch
            batch_num += 1

        except httpx.HTTPStatusError as e:
            print(f"   ❌ Error HTTP: {e.response.status_code} - {e.response.text[:200]}")
            break
        except Exception as e:
            print(f"   ❌ Error: {str(e)}")
            import traceback

            traceback.print_exc()
            break

    print("\n✅ Sincronización completa finalizada")
    print(f"   Total procesado: {total_procesado} registros")


def sync_incremental(db: Session, from_id: int | None = None) -> None:
    """Sincronización incremental desde el último rmaai_id en la DB (o desde from_id)"""
    last_rmaai_id = from_id if from_id is not None else get_max_rmaai_id(db)

    print(f"\n🔄 Sincronización INCREMENTAL de tb_rma_add_items (desde rmaai_id > {last_rmaai_id})")
    print("=" * 60)

    params = {
        "strScriptLabel": "scriptRMAAddItems",
        "rmaaiID": last_rmaai_id,
    }

    print(f"📡 Consultando ERP (rmaai_id > {last_rmaai_id})...")
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
    """Sincronización por filtro específico (rmahID o rmadID)"""
    label = "RMA header" if filter_name == "rmahID" else "RMA detail"
    print(f"\n🔄 Sincronización por {label} ({filter_name}={filter_value})")
    print("=" * 60)

    params = {
        "strScriptLabel": "scriptRMAAddItems",
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

    for i in range(0, len(normalized_data), 500):
        batch = normalized_data[i : i + 500]
        upsert_batch(db, batch)

    print(f"\n✅ Sincronización por {label} finalizada")
    print(f"   Total actualizado: {len(normalized_data)} registros")


def main() -> None:
    parser = argparse.ArgumentParser(description="Sincronizar tb_rma_add_items")

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--full", action="store_true", help="Sincronización completa (toda la tabla del ERP)")
    mode.add_argument("--incremental", action="store_true", help="Incremental desde último rmaai_id en DB")
    mode.add_argument("--rmah-id", type=int, help="Sincronizar add items de un RMA header específico")
    mode.add_argument("--rmad-id", type=int, help="Sincronizar add items de un RMA detail específico")

    parser.add_argument(
        "--from-id", type=int, default=None, help="Forzar rmaai_id inicial para incremental (override auto-detect)"
    )

    args = parser.parse_args()

    db = SessionLocal()

    try:
        if args.full:
            sync_full(db)
        elif args.incremental:
            sync_incremental(db, from_id=args.from_id)
        elif args.rmah_id:
            sync_by_filter(db, "rmahID", args.rmah_id)
        elif args.rmad_id:
            sync_by_filter(db, "rmadID", args.rmad_id)

    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
