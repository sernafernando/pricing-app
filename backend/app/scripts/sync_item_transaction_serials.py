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

Terminación del full sync (ver incidente de runaway):
    - Se frena tras MAX_CONSECUTIVE_EMPTY_BATCHES lotes que NO persisten ninguna
      fila. Cuenta filas realmente escritas, no "el payload venía con algo".
    - Se aborta con exit code 1 tras MAX_CONSECUTIVE_FAILURES errores seguidos.
    - MAX_BATCHES es una válvula de seguridad absoluta: superarla es un fallo
      ruidoso, nunca un corte silencioso.
    - --max-id acota el rango de its_id explorado.
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

from app.core.config import settings
from app.core.database import SessionLocal

# Import all models to avoid circular dependency issues
import app.models  # noqa
from app.models.tb_item_transaction_serials import TbItemTransactionSerial

SCRIPT_LABEL = "scriptItemTransactionSerials"

# Rows per ON CONFLICT DO UPDATE statement.
UPSERT_SUB_BATCH_SIZE = 500

# Consecutive batches that persist ZERO rows before the full sync concludes it
# has walked past the end of the its_id space. Counts rows actually written, not
# payload truthiness: a batch whose every row fails _normalize_row persists
# nothing and therefore counts as empty.
MAX_CONSECUTIVE_EMPTY_BATCHES = 3

# Consecutive failing batches before the full sync aborts with a non-zero exit.
# One transient ERP hiccup must not kill a long run; a dead ERP must stop it.
MAX_CONSECUTIVE_FAILURES = 3

# Absolute safety valve. At the default batch_size of 10000 this caps the walk
# at its_id 20_000_000 and at 2000 upstream requests. The production runaway
# reached batch #370563 / its_id 3_705_620_001 sustaining ~25 req/s for hours
# against the ERP webservice. Hitting this ceiling is a LOUD failure, never a
# silent stop: either the ERP is misbehaving or the table outgrew this script.
MAX_BATCHES = 2000

# Single-element payloads carrying one of these keys are gbp-parser's error
# sentinels (`[{"error": "No se encontró el tag result"}]`,
# `[{"raw": "<html>...503..."}]`). Real rows never carry them: they carry
# comp_id / bra_id / its_id.
_ERP_ERROR_SENTINEL_KEYS: frozenset[str] = frozenset({"error", "raw"})


class ErpPayloadError(RuntimeError):
    """The ERP answered HTTP 200 with an error sentinel instead of rows.

    Must NEVER be collapsed into an empty list: an upstream outage has to be
    distinguishable from "no more rows", otherwise the full sync reads the
    outage as data and never terminates.
    """


class SyncAbortedError(RuntimeError):
    """The full sync hit a guard rail and must exit non-zero."""


def _to_int(value: object) -> int | None:
    """Convert value to int, return None if invalid."""
    if value is None or value == "":
        return None
    try:
        return int(value)  # type: ignore[arg-type]
    except (ValueError, TypeError):
        return None


def _is_erp_error_sentinel(data: list) -> bool:
    """True when `data` is a gbp-parser error sentinel rather than rows."""
    if len(data) != 1 or not isinstance(data[0], dict):
        return False
    return bool(_ERP_ERROR_SENTINEL_KEYS & data[0].keys())


async def _fetch_from_erp(params: dict[str, str | int]) -> list:
    """Query ERP via gbp-parser.

    Returns:
        The list of raw ERP rows, or `[]` for the legitimate "no data" sentinel
        `[{"Column1": "..."}]`.

    Raises:
        httpx.HTTPStatusError: si gbp-parser responde con un status no-2xx.
        ErpPayloadError: si gbp-parser responde 200 con un sentinel de error
            (`error` / `raw`) o con algo que no es una lista. Estos casos NO se
            devuelven como `[]`: una caída del ERP no puede ser indistinguible
            de "no hay más filas".
    """
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.get(settings.GBP_PARSER_URL, params=params)
        response.raise_for_status()
        data = response.json()

    if not isinstance(data, list):
        raise ErpPayloadError(f"gbp-parser devolvió un payload que no es una lista: {data!r}")

    # An upstream failure dressed as HTTP 200. Hard failure, never "no data".
    if _is_erp_error_sentinel(data):
        raise ErpPayloadError(f"gbp-parser devolvió un sentinel de error del ERP: {data[0]!r}")

    # GBP sometimes returns [{"Column1": "..."}] when there's no data
    if len(data) == 1 and isinstance(data[0], dict) and "Column1" in data[0]:
        return []

    return data


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


def sync_full(db: Session, batch_size: int = 10000, max_id: int | None = None) -> None:
    """Full sync by its_id ranges.

    Terminates on any of:
      - MAX_CONSECUTIVE_EMPTY_BATCHES batches that persist zero rows (normal end);
      - `max_id` reached, when supplied (normal end);
      - MAX_CONSECUTIVE_FAILURES consecutive failing batches (SyncAbortedError);
      - MAX_BATCHES batches walked (SyncAbortedError, safety valve).

    Raises:
        SyncAbortedError: when a guard rail trips. The caller must exit non-zero.
    """
    print("\nSync FULL de tb_item_transaction_serials (rangos de its_id)")
    print("=" * 60)
    print(
        f"Batch size: {batch_size} | Frena con {MAX_CONSECUTIVE_EMPTY_BATCHES} lotes "
        f"sin registros | Aborta con {MAX_CONSECUTIVE_FAILURES} errores seguidos"
    )
    print(f"Tope de lotes: {MAX_BATCHES} | max-id: {max_id if max_id is not None else 'sin tope'}\n")

    current_from = 1
    total_processed = 0
    batch_num = 1
    consecutive_empty = 0
    consecutive_failures = 0

    while True:
        if max_id is not None and current_from > max_id:
            print(f"\nAlcanzado --max-id {max_id}, terminando.")
            break

        # Absolute safety valve. Loud on purpose: reaching it means either the
        # ERP is misbehaving or this script's assumptions no longer hold.
        if batch_num > MAX_BATCHES:
            raise SyncAbortedError(
                f"Válvula de seguridad: se alcanzó el tope de {MAX_BATCHES} lotes "
                f"(its_id {current_from}, {total_processed} registros persistidos). "
                "Revisar el ERP o subir MAX_BATCHES deliberadamente."
            )

        current_to = current_from + batch_size - 1
        if max_id is not None:
            current_to = min(current_to, max_id)
        print(f"Lote #{batch_num} (its_id: {current_from} - {current_to})...", end=" ")

        params: dict[str, str | int] = {
            "strScriptLabel": SCRIPT_LABEL,
            "itsIDfrom": current_from,
            "itsIDto": current_to,
        }

        try:
            data = asyncio.run(_fetch_from_erp(params))
            normalized = [r for row in data if (r := _normalize_row(row)) is not None]

            # Insert in sub-batches
            rows_persisted = 0
            for i in range(0, len(normalized), UPSERT_SUB_BATCH_SIZE):
                rows_persisted += _upsert_batch(db, normalized[i : i + UPSERT_SUB_BATCH_SIZE])
        except Exception as exc:
            consecutive_failures += 1
            print(f"ERROR ({consecutive_failures}/{MAX_CONSECUTIVE_FAILURES}): {exc}")
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                raise SyncAbortedError(
                    f"{MAX_CONSECUTIVE_FAILURES} errores consecutivos consultando el ERP "
                    f"(último its_id {current_from}, {total_processed} registros persistidos): {exc}"
                ) from exc
        else:
            consecutive_failures = 0
            total_processed += rows_persisted

            # Termination is driven by rows ACTUALLY PERSISTED, never by payload
            # truthiness: a payload full of unnormalizable rows used to reset
            # this counter and print "0 registros" forever.
            if rows_persisted == 0:
                consecutive_empty += 1
                print(f"sin registros ({consecutive_empty}/{MAX_CONSECUTIVE_EMPTY_BATCHES})")
                if consecutive_empty >= MAX_CONSECUTIVE_EMPTY_BATCHES:
                    print(f"\n{MAX_CONSECUTIVE_EMPTY_BATCHES} lotes sin registros consecutivos, terminando.")
                    break
            else:
                consecutive_empty = 0
                print(f"{rows_persisted} registros (acum: {total_processed})")

        current_from = current_to + 1
        batch_num += 1

    print(f"\nSync full finalizado. Total: {total_processed} registros")


def sync_incremental(db: Session) -> None:
    """Incremental sync from last its_id in our DB.

    Raises:
        SyncAbortedError: si falla la consulta al ERP. Antes se imprimía el error
            y se retornaba con exit code 0, de modo que el cron daba por exitosa
            una corrida que no sincronizó nada.
    """
    print("\nSync INCREMENTAL de tb_item_transaction_serials")
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
    except Exception as exc:
        raise SyncAbortedError(f"Error consultando el ERP: {exc}") from exc

    if not data:
        print("No hay registros nuevos.")
        return

    print(f"Obtenidos {len(data)} registros del ERP")

    normalized = [r for row in data if (r := _normalize_row(row)) is not None]

    total = 0
    for i in range(0, len(normalized), UPSERT_SUB_BATCH_SIZE):
        total += _upsert_batch(db, normalized[i : i + UPSERT_SUB_BATCH_SIZE])
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
    # Sin default: cualquier tope fijo truncaría en silencio un full sync
    # legítimo el día que la tabla lo supere. El bound estructural contra
    # runaways lo da MAX_BATCHES, que falla ruidosamente en vez de truncar.
    parser.add_argument(
        "--max-id",
        type=int,
        default=None,
        help="its_id máximo a explorar en --full (default: sin tope, acotado por MAX_BATCHES)",
    )

    args = parser.parse_args()

    if not args.full and not args.incremental:
        print("Debe especificar --full o --incremental")
        sys.exit(1)

    if args.batch_size < 1:
        print("--batch-size debe ser >= 1")
        sys.exit(1)

    if args.max_id is not None and args.max_id < 1:
        print("--max-id debe ser >= 1")
        sys.exit(1)

    db = SessionLocal()

    try:
        if args.full:
            sync_full(db, batch_size=args.batch_size, max_id=args.max_id)
        else:
            sync_incremental(db)
    except SyncAbortedError as e:
        print(f"\nSync abortado: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\nError: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
