"""
Backfill one-off de órdenes ML canceladas históricas a mlwebhook.ml_cancelled_orders.

ml-webhook ya persiste las cancelaciones NUEVAS (forward-fill por webhook). Este
script carga el HISTÓRICO: órdenes canceladas antes del deploy, usando datos que
pricing YA tiene (sin tocar la API de ML).

Fuente (READ):  pricing_dev.tb_mercadolibre_orders_header WHERE mlo_status='cancelled'.
                mlo_lastjson = snapshot crudo de la orden (shape de /orders/{id}).
Destino (WRITE): mlwebhook.ml_cancelled_orders, vía get_mlwebhook_engine().

El mapeo replica EXACTAMENTE el de ml-webhook para que las filas del backfill sean
indistinguibles de las del forward-fill. UPSERT idempotente por order_id (seguro de
re-correr; no pisa mal lo que el webhook haya cargado en el medio).

Uso:
    python -m app.scripts.backfill_ml_cancelled_orders
    python -m app.scripts.backfill_ml_cancelled_orders --dry-run
    python -m app.scripts.backfill_ml_cancelled_orders --batch-size 500
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

backend_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_dir))

from dotenv import load_dotenv

load_dotenv(dotenv_path=backend_dir / ".env")

from sqlalchemy import text

from app.core.database import SessionLocal, get_mlwebhook_engine

BATCH_SIZE_DEFAULT = 500

_UPSERT_SQL = text("""
    INSERT INTO ml_cancelled_orders (
        order_id, pack_id, status, status_detail, cancelled_by,
        date_created, date_closed, total_amount, currency_id,
        buyer_id, buyer_nickname, seller_id, items, payload, updated_at
    ) VALUES (
        :order_id, :pack_id, :status, :status_detail, :cancelled_by,
        :date_created, :date_closed, :total_amount, :currency_id,
        :buyer_id, :buyer_nickname, :seller_id,
        CAST(:items AS JSONB), CAST(:payload AS JSONB), NOW()
    )
    ON CONFLICT (order_id) DO UPDATE SET
        pack_id = EXCLUDED.pack_id, status = EXCLUDED.status,
        status_detail = EXCLUDED.status_detail, cancelled_by = EXCLUDED.cancelled_by,
        date_created = EXCLUDED.date_created, date_closed = EXCLUDED.date_closed,
        total_amount = EXCLUDED.total_amount, currency_id = EXCLUDED.currency_id,
        buyer_id = EXCLUDED.buyer_id, buyer_nickname = EXCLUDED.buyer_nickname,
        seller_id = EXCLUDED.seller_id, items = EXCLUDED.items,
        payload = EXCLUDED.payload, updated_at = NOW()
""")


def _to_bigint(value: Any) -> Optional[int]:
    """Castea a int (BIGINT). pack_id del ERP puede venir como string; None si no es numérico."""
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _as_dict(raw: Any) -> Optional[Dict[str, Any]]:
    """mlo_lastjson puede venir como dict (psycopg2 decodifica json) o como str."""
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else None
        except (ValueError, TypeError):
            return None
    return None


def _mapear_fila(row: Any) -> Optional[Dict[str, Any]]:
    """
    Mapea una fila del header a los valores de ml_cancelled_orders.

    order_id SIEMPRE sale de la columna plana ml_id (el número de orden de ML, la
    clave de cruce con ml_ventas_metricas.ml_order_id). NUNCA del mlo_id interno de
    GBP ni de order_data["id"]: en la data observada, mlo_lastjson suele ser un
    escalar vacío ("") y order_data["id"] no existe — usar el fallback a mlo_id
    corrompería el cruce. Los campos ricos se extraen del snapshot SOLO cuando
    mlo_lastjson/firstjson es un objeto real; si no, columnas planas.

    Devuelve None si la fila no tiene ml_id (no se puede cruzar -> descartada).
    """
    m = row._mapping

    order_id = _to_bigint(m["ml_id"])  # número de orden ML, autoritativo
    if order_id is None:
        return None

    # Snapshot crudo de ML, si existe como objeto (no "" ni null)
    order_data = _as_dict(m["mlo_lastjson"]) or _as_dict(m.get("mlo_firstjson"))

    status_detail: Optional[str] = None
    cancelled_by: Optional[str] = None
    currency_id: Optional[str] = None
    buyer_id: Optional[int] = None
    buyer_nickname: Optional[str] = None
    seller_id: Optional[int] = None
    items: List[Dict[str, Any]] = []
    pack_id = _to_bigint(m.get("ml_pack_id"))

    if order_data:
        detail = order_data.get("cancel_detail") or order_data.get("status_detail") or {}
        if isinstance(detail, dict):
            status_detail = detail.get("description") or detail.get("code")
            cancelled_by = detail.get("requested_by") or detail.get("group")
        else:
            status_detail = str(detail) if detail else None

        buyer = order_data.get("buyer") or {}
        seller = order_data.get("seller") or {}
        buyer_id = _to_bigint(buyer.get("id"))
        buyer_nickname = buyer.get("nickname")
        seller_id = _to_bigint(seller.get("id"))
        currency_id = order_data.get("currency_id")
        pack_id = _to_bigint(order_data.get("pack_id")) or pack_id

        items = [
            {
                "item_id": (oi.get("item") or {}).get("id"),
                "seller_sku": (oi.get("item") or {}).get("seller_sku")
                or (oi.get("item") or {}).get("seller_custom_field"),
                "title": (oi.get("item") or {}).get("title"),
                "quantity": oi.get("quantity"),
                "unit_price": oi.get("unit_price"),
            }
            for oi in (order_data.get("order_items") or [])
        ]

    # Fechas y total: preferir el snapshot, fallback a columnas planas
    od = order_data or {}
    date_created = od.get("date_created") or m.get("ml_date_created")
    date_closed = od.get("date_closed") or m.get("ml_date_closed")
    total_amount = od.get("total_amount")
    if total_amount is None:
        total_amount = m.get("mlo_total_paid_amount")

    payload = order_data if order_data else {"id": order_id, "status": "cancelled"}

    return {
        "order_id": order_id,
        "pack_id": pack_id,
        "status": "cancelled",
        "status_detail": status_detail,
        "cancelled_by": cancelled_by,
        "date_created": date_created,
        "date_closed": date_closed,
        "total_amount": total_amount,
        "currency_id": currency_id,
        "buyer_id": buyer_id,
        "buyer_nickname": buyer_nickname,
        "seller_id": seller_id,
        "items": json.dumps(items),
        "payload": json.dumps(payload, default=str),
    }


def _contar(conn, sql: str) -> int:
    return conn.execute(text(sql)).scalar() or 0


def _upsert_batch(dest_conn, valores: List[Dict[str, Any]]) -> Tuple[int, int]:
    """UPSERT de un batch. Devuelve (insertadas, actualizadas)."""
    if not valores:
        return 0, 0

    ids = [v["order_id"] for v in valores]
    existentes = {
        r[0]
        for r in dest_conn.execute(
            text("SELECT order_id FROM ml_cancelled_orders WHERE order_id = ANY(:ids)"),
            {"ids": ids},
        ).fetchall()
    }
    actualizadas = sum(1 for i in ids if i in existentes)
    insertadas = len(ids) - actualizadas

    dest_conn.execute(_UPSERT_SQL, valores)
    return insertadas, actualizadas


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill histórico de cancelaciones ML a ml_cancelled_orders")
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE_DEFAULT, help="Tamaño de batch (default 500)")
    parser.add_argument("--dry-run", action="store_true", help="No escribe; solo mapea y cuenta")
    args = parser.parse_args()

    print("=" * 60)
    print("BACKFILL ml_cancelled_orders (histórico)")
    print("=" * 60)
    print(f"Batch: {args.batch_size} | Dry-run: {args.dry_run}")

    src = SessionLocal()
    dest_engine = get_mlwebhook_engine()

    total_leidas = 0
    total_insertadas = 0
    total_actualizadas = 0
    total_descartadas = 0  # payload/order_id inservible

    try:
        result = src.execute(
            text("""
                SELECT mlo_id, ml_id, mlo_lastjson, mlo_firstjson,
                       ml_date_created, ml_date_closed, mlo_total_paid_amount, ml_pack_id
                FROM tb_mercadolibre_orders_header
                WHERE mlo_status = 'cancelled' OR mlo_iscancelled = TRUE
            """).execution_options(stream_results=True)
        )

        while True:
            rows = result.fetchmany(args.batch_size)
            if not rows:
                break

            total_leidas += len(rows)
            valores: List[Dict[str, Any]] = []
            for row in rows:
                mapped = _mapear_fila(row)
                if mapped is None:
                    total_descartadas += 1
                else:
                    valores.append(mapped)

            if args.dry_run:
                total_insertadas += len(valores)  # en dry-run no distinguimos ins/upd
            else:
                with dest_engine.begin() as dest_conn:
                    ins, upd = _upsert_batch(dest_conn, valores)
                    total_insertadas += ins
                    total_actualizadas += upd

            print(
                f"  procesadas {total_leidas} (ins={total_insertadas} upd={total_actualizadas} desc={total_descartadas})"
            )

        # Verificación de cierre
        origen_canceladas = _contar(
            src.connection(),
            "SELECT count(*) FROM tb_mercadolibre_orders_header WHERE mlo_status = 'cancelled' OR mlo_iscancelled = TRUE",
        )
        destino_total = 0
        if not args.dry_run:
            with dest_engine.connect() as dest_conn:
                destino_total = _contar(dest_conn, "SELECT count(*) FROM ml_cancelled_orders")

        print("\n" + "=" * 60)
        print("🧪 DRY-RUN (sin escritura)" if args.dry_run else "✅ COMPLETADO")
        print("=" * 60)
        print(f"  leídas (cancelled en header):     {total_leidas}")
        print(f"  insertadas:                       {total_insertadas}")
        print(f"  actualizadas:                     {total_actualizadas}")
        print(f"  descartadas (payload/id nulo):    {total_descartadas}")
        print("  --- verificación ---")
        print(f"  origen  tb_..._header cancelled:  {origen_canceladas}")
        if not args.dry_run:
            print(f"  destino ml_cancelled_orders:      {destino_total}")
        print()

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
    finally:
        src.close()


if __name__ == "__main__":
    main()
