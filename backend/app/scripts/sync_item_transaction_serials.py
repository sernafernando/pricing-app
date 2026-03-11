"""
Script para sincronizar tb_item_transaction_serials desde el ERP.
Tabla puente entre seriales (is_id) y transacciones de venta (it_transaction/ct_transaction).

Ejecutar desde el directorio backend:
    cd /var/www/html/pricing-app/backend

    # Full sync (por rangos de its_id)
    python -m app.scripts.sync_item_transaction_serials --full

    # Full sync con rango personalizado
    python -m app.scripts.sync_item_transaction_serials --full --max-id 500000

    # Incremental (desde el último its_id sincronizado)
    python -m app.scripts.sync_item_transaction_serials --incremental
"""

import sys
import os

if __name__ == "__main__":
    backend_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if backend_path not in sys.path:
        sys.path.insert(0, backend_path)

from pathlib import Path

from dotenv import load_dotenv

env_path = Path(__file__).parent.parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

import argparse
import asyncio
import httpx
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy import func

from app.core.database import SessionLocal

# Import all models to avoid circular dependency issues
import app.models  # noqa
from app.models.tb_item_transaction_serials import TbItemTransactionSerial

GBP_PARSER_URL = "http://localhost:8002/api/gbp-parser"
SCRIPT_LABEL = "scriptItemTransactionSerials"


def _to_int(value: object) -> int | None:
    """Convert value to int, return None if invalid."""
    if value is None or value == "":
        return None
    try:
        return int(value)  # type: ignore[arg-type]
    except (ValueError, TypeError):
        return None


async def _fetch_from_erp(params: dict) -> list:
    """Query ERP via gbp-parser."""
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.get(GBP_PARSER_URL, params=params)
        response.raise_for_status()
        data = response.json()

    # GBP sometimes returns [{"Column1": "..."}] when there's no data
    if isinstance(data, list) and len(data) == 1 and "Column1" in data[0]:
        return []

    return data if isinstance(data, list) else []


def _normalize_row(row: dict) -> dict | None:
    """Normalize a row from ERP to match our model columns."""
    comp_id = _to_int(row.get("comp_id"))
    bra_id = _to_int(row.get("bra_id"))
    its_id = _to_int(row.get("its_id"))

    if not comp_id or not bra_id or not its_id:
        return None

    return {
        "comp_id": comp_id,
        "bra_id": bra_id,
        "its_id": its_id,
        "it_transaction": _to_int(row.get("it_transaction")),
        "is_id": _to_int(row.get("is_id")),
        "ct_transaction": _to_int(row.get("ct_transaction")),
        "impdata_id": _to_int(row.get("impData_id") or row.get("impdata_id")),
        "import_id": _to_int(row.get("import_id")),
    }


def _upsert_batch(db: Session, rows: list[dict]) -> int:
    """Upsert a batch of normalized rows. Returns count of rows processed."""
    if not rows:
        return 0

    stmt = insert(TbItemTransactionSerial)
    stmt = stmt.on_conflict_do_update(
        index_elements=["comp_id", "bra_id", "its_id"],
        set_={
            "it_transaction": stmt.excluded.it_transaction,
            "is_id": stmt.excluded.is_id,
            "ct_transaction": stmt.excluded.ct_transaction,
            "impdata_id": stmt.excluded.impdata_id,
            "import_id": stmt.excluded.import_id,
        },
    )

    db.execute(stmt, rows)
    db.commit()
    return len(rows)


def sync_full(db: Session, batch_size: int = 10000) -> None:
    """Full sync by its_id ranges. Stops when consecutive empty batches are found."""
    print(f"\nSync FULL de tb_item_transaction_serials (rangos de its_id)")
    print("=" * 60)
    print(f"Batch size: {batch_size} | Frena con 3 batches vacíos consecutivos\n")

    current_from = 1
    total_processed = 0
    batch_num = 1
    consecutive_empty = 0
    max_consecutive_empty = 3  # Stop after 3 empty batches in a row

    while True:
        current_to = current_from + batch_size - 1
        print(f"Lote #{batch_num} (its_id: {current_from} - {current_to})...", end=" ")

        params = {
            "strScriptLabel": SCRIPT_LABEL,
            "itsIDfrom": current_from,
            "itsIDto": current_to,
        }

        try:
            data = asyncio.run(_fetch_from_erp(params))

            if not data:
                consecutive_empty += 1
                print(f"sin datos ({consecutive_empty}/{max_consecutive_empty})")
                if consecutive_empty >= max_consecutive_empty:
                    print(f"\n{max_consecutive_empty} batches vacíos consecutivos, terminando.")
                    break
            else:
                consecutive_empty = 0
                normalized = [r for row in data if (r := _normalize_row(row)) is not None]

                # Insert in sub-batches of 500
                sub_total = 0
                for i in range(0, len(normalized), 500):
                    sub_total += _upsert_batch(db, normalized[i : i + 500])

                total_processed += sub_total
                print(f"{sub_total} registros (acum: {total_processed})")

        except Exception as e:
            print(f"ERROR: {e}")

        current_from = current_to + 1
        batch_num += 1

    print(f"\nSync full finalizado. Total: {total_processed} registros")


def sync_incremental(db: Session) -> None:
    """Incremental sync from last its_id in our DB."""
    print(f"\nSync INCREMENTAL de tb_item_transaction_serials")
    print("=" * 60)

    last_its_id = db.query(func.max(TbItemTransactionSerial.its_id)).scalar()

    if last_its_id is None:
        print("No hay datos previos. Ejecuta --full primero.")
        return

    print(f"Ultimo its_id en DB: {last_its_id}")

    # Fetch everything after last_its_id (the script uses its_id > @itsID)
    params = {
        "strScriptLabel": SCRIPT_LABEL,
        "itsID": last_its_id,
    }

    try:
        data = asyncio.run(_fetch_from_erp(params))
    except Exception as e:
        print(f"ERROR consultando ERP: {e}")
        return

    if not data:
        print("No hay registros nuevos.")
        return

    print(f"Obtenidos {len(data)} registros del ERP")

    normalized = [r for row in data if (r := _normalize_row(row)) is not None]

    total = 0
    for i in range(0, len(normalized), 500):
        total += _upsert_batch(db, normalized[i : i + 500])
        if total % 1000 == 0:
            print(f"  {total} registros procesados...")

    new_max = db.query(func.max(TbItemTransactionSerial.its_id)).scalar()
    print(f"\nSync incremental finalizado. Insertados: {total}")
    print(f"Nuevo max its_id: {new_max}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Sincronizar tb_item_transaction_serials")
    parser.add_argument("--full", action="store_true", help="Sync completo por rangos de its_id")
    parser.add_argument("--incremental", action="store_true", help="Sync incremental desde ultimo its_id")
    parser.add_argument("--batch-size", type=int, default=10000, help="Batch size para full (default: 10000)")

    args = parser.parse_args()

    if not args.full and not args.incremental:
        print("Debe especificar --full o --incremental")
        sys.exit(1)

    db = SessionLocal()

    try:
        if args.full:
            sync_full(db, batch_size=args.batch_size)
        else:
            sync_incremental(db)
    except Exception as e:
        print(f"\nError: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
