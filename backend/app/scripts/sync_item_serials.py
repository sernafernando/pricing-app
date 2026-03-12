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

env_path = backend_dir / ".env"
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


def sync_full(db: Session, batch_size: int = 10000):
    """Sincronización completa por rangos de is_id. Frena con 3 batches vacíos."""
    print("\n Sincronización COMPLETA de tb_item_serials (por rangos de is_id)")
    print("=" * 60)
    print(f"Batch size: {batch_size} | Frena con 3 batches vacíos consecutivos\n")

    current_from = 1
    total_procesado = 0
    batch_num = 1
    consecutive_empty = 0
    max_consecutive_empty = 3

    while True:
        current_to = current_from + batch_size - 1
        print(f"Lote #{batch_num} (is_id: {current_from} - {current_to})...", end=" ")

        params = {"strScriptLabel": "scriptItemSerials", "isIDfrom": current_from, "isIDto": current_to}

        try:
            data = asyncio.run(fetch_from_erp(params))

            # GBP empty response
            if data and len(data) == 1 and "Column1" in data[0]:
                data = []

            if not data:
                consecutive_empty += 1
                print(f"sin datos ({consecutive_empty}/{max_consecutive_empty})")
                if consecutive_empty >= max_consecutive_empty:
                    print(f"\n{max_consecutive_empty} batches vacíos consecutivos, terminando.")
                    break
            else:
                consecutive_empty = 0
                normalized = [r for row in data if (r := _normalize_row(row)) is not None]

                for i in range(0, len(normalized), 500):
                    _upsert_batch(db, normalized[i : i + 500])

                total_procesado += len(normalized)
                print(f"{len(normalized)} registros (acum: {total_procesado})")

        except Exception as e:
            print(f"ERROR: {e}")

        current_from = current_to + 1
        batch_num += 1

    print(f"\n Sincronización completa finalizada. Total: {total_procesado} registros")


def _normalize_row(row: dict) -> dict | None:
    """Normaliza una fila del ERP para upsert."""
    if not row.get("comp_id") or not row.get("is_id") or not row.get("bra_id"):
        return None

    if "is_IsOwnGeneration" in row:
        row["is_isowngeneration"] = row.pop("is_IsOwnGeneration")

    for bool_field in ["is_available", "is_isowngeneration", "is_checked", "is_printed"]:
        if bool_field in row and row[bool_field] is not None:
            row[bool_field] = bool(row[bool_field])

    if "is_cd" in row and row["is_cd"]:
        try:
            row["is_cd"] = datetime.fromisoformat(row["is_cd"].replace("Z", "+00:00"))
        except (ValueError, TypeError):
            row["is_cd"] = None

    valid_fields = {
        "comp_id",
        "is_id",
        "bra_id",
        "ct_transaction",
        "it_transaction",
        "item_id",
        "stor_id",
        "is_serial",
        "is_cd",
        "is_available",
        "is_guid",
        "is_isowngeneration",
        "is_checked",
        "is_printed",
    }
    return {k: v for k, v in row.items() if k in valid_fields}


def _upsert_batch(db: Session, rows: list[dict]) -> int:
    """Upsert un batch de filas normalizadas. Retorna cantidad procesada."""
    if not rows:
        return 0

    stmt = insert(TbItemSerial)
    stmt = stmt.on_conflict_do_update(
        index_elements=["comp_id", "is_id", "bra_id"],
        set_={
            "ct_transaction": stmt.excluded.ct_transaction,
            "it_transaction": stmt.excluded.it_transaction,
            "item_id": stmt.excluded.item_id,
            "stor_id": stmt.excluded.stor_id,
            "is_serial": stmt.excluded.is_serial,
            "is_cd": stmt.excluded.is_cd,
            "is_available": stmt.excluded.is_available,
            "is_guid": stmt.excluded.is_guid,
            "is_isowngeneration": stmt.excluded.is_isowngeneration,
            "is_checked": stmt.excluded.is_checked,
            "is_printed": stmt.excluded.is_printed,
        },
    )

    db.execute(stmt, rows)
    db.commit()
    return len(rows)


def sync_incremental(db: Session, days_back: int = 7):
    """Sincronización incremental: por fecha + por is_id (gap fill)."""
    from sqlalchemy import func

    print("\n Sincronización INCREMENTAL de tb_item_serials")
    print("=" * 60)

    total_updated = 0

    # ── Paso 1: por fecha (últimos N días) ────────────────────────
    from_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    to_date = datetime.now().strftime("%Y-%m-%d")

    params = {"strScriptLabel": "scriptItemSerials", "fromDate": from_date, "toDate": to_date}

    print(f"[1/2] Por fecha (desde {from_date} hasta {to_date})...")
    data = asyncio.run(fetch_from_erp(params))

    if data:
        normalized = [r for row in data if (r := _normalize_row(row)) is not None]
        for i in range(0, len(normalized), 500):
            total_updated += _upsert_batch(db, normalized[i : i + 500])
        print(f"  Actualizados {total_updated} registros por fecha")
    else:
        print("  Sin datos nuevos por fecha")

    # ── Paso 2: por is_id (gap fill) ─────────────────────────────
    # Trae todo lo que tenga is_id mayor al último sincronizado,
    # sin importar la fecha. Cubre seriales con is_cd vieja o NULL.
    last_is_id = db.query(func.max(TbItemSerial.is_id)).scalar()

    if last_is_id is None:
        print("[2/2] No hay datos previos, saltando gap fill (usá --full)")
    else:
        print(f"[2/2] Por is_id (desde {last_is_id})...")
        params_gap = {"strScriptLabel": "scriptItemSerials", "isID": last_is_id}

        try:
            data_gap = asyncio.run(fetch_from_erp(params_gap))
        except Exception as e:
            print(f"  Error consultando gap fill: {e}")
            data_gap = None

        if data_gap:
            # Filtrar respuesta vacía de GBP
            if len(data_gap) == 1 and "Column1" in data_gap[0]:
                data_gap = []

            if data_gap:
                normalized_gap = [r for row in data_gap if (r := _normalize_row(row)) is not None]
                gap_count = 0
                for i in range(0, len(normalized_gap), 500):
                    gap_count += _upsert_batch(db, normalized_gap[i : i + 500])
                total_updated += gap_count
                new_max = db.query(func.max(TbItemSerial.is_id)).scalar()
                print(f"  Actualizados {gap_count} registros por is_id (nuevo max: {new_max})")
            else:
                print("  Sin datos nuevos por is_id")
        else:
            print("  Sin datos nuevos por is_id")

    print(f"\n Sincronización incremental finalizada. Total: {total_updated} registros")


def main():
    parser = argparse.ArgumentParser(description="Sincronizar tb_item_serials")
    parser.add_argument("--full", action="store_true", help="Sincronización completa")
    parser.add_argument("--incremental", action="store_true", help="Sincronización incremental (últimos 7 días)")
    parser.add_argument("--days", type=int, default=7, help="Días hacia atrás para incremental (default: 7)")
    parser.add_argument(
        "--batch-size", type=int, default=10000, help="Tamaño de lote para sincronización full (default: 10000)"
    )

    args = parser.parse_args()

    if not args.full and not args.incremental:
        print("❌ Debe especificar --full o --incremental")
        sys.exit(1)

    db = SessionLocal()

    try:
        if args.full:
            sync_full(db, batch_size=args.batch_size)
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
