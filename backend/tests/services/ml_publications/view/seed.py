"""Rows for the view tests: plain SQL inserts into the throwaway store schema (`env` fixture).

Not captures of ML: these tests exercise OUR query (joins, filters, sorts, paging) over rows whose
shape is fixed by the migrations, so each helper names only the columns the case under test needs.
"""

from __future__ import annotations

import itertools
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import text

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
_counter = itertools.count(1)


def _insert(conn, table: str, row: dict[str, Any]) -> None:
    columns = ", ".join(row)
    values = ", ".join(f":{name}" for name in row)
    conn.execute(text(f"INSERT INTO {table} ({columns}) VALUES ({values})"), row)


def add_item(conn, item_id: str, **columns: Any) -> None:
    _insert(conn, "ml_items", {"item_id": item_id, **columns})


def add_variation(conn, item_id: str, variation_id: int, **columns: Any) -> None:
    """A variation row; `raw` (the captured JSON, as a dict) may be overridden, e.g. for `attribute_combinations`."""
    row = {
        "item_id": item_id,
        "variation_id": variation_id,
        "raw": {"id": variation_id},
        "raw_hash": b"\x00",
        "fetched_at": NOW,
        **columns,
    }
    row["raw"] = json.dumps(row["raw"])
    values = ", ".join("CAST(:raw AS jsonb)" if name == "raw" else f":{name}" for name in row)
    conn.execute(text(f"INSERT INTO ml_item_variations ({', '.join(row)}) VALUES ({values})"), row)


def add_product(
    conn,
    item_id: int,
    codigo: str,
    descripcion: str,
    marca: Optional[str] = None,
    categoria: Optional[str] = None,
    subcategoria_id: Optional[int] = None,
) -> None:
    _insert(
        conn,
        "productos_erp",
        {
            "item_id": item_id,
            "codigo": codigo,
            "descripcion": descripcion,
            "marca": marca,
            "categoria": categoria,
            "subcategoria_id": subcategoria_id,
        },
    )


PRICING_DDL = (
    "CREATE TABLE productos_pricing (id serial PRIMARY KEY, item_id integer UNIQUE, precio_lista_ml double precision, "
    "precio_3_cuotas numeric(15,2), precio_6_cuotas numeric(15,2), precio_9_cuotas numeric(15,2), "
    "precio_12_cuotas numeric(15,2))"
)


def add_cost(
    conn,
    item_id: int,
    costo: Optional[float],
    *,
    moneda_costo: str = "ARS",
    iva: float = 21.0,
    envio: float = 0.0,
) -> None:
    """The cost fields of an already inserted product."""
    conn.execute(
        text("UPDATE productos_erp SET costo = :c, moneda_costo = :m, iva = :iva, envio = :e WHERE item_id = :i"),
        {"c": costo, "m": moneda_costo, "iva": iva, "e": envio, "i": item_id},
    )


def add_pricing(conn, item_id: int, **prices: Any) -> None:
    """The Productos list prices (`precio_lista_ml`, `precio_6_cuotas`, ...) of a product."""
    _insert(conn, "productos_pricing", {"item_id": item_id, **prices})


def add_link(
    conn,
    item_id: str,
    producto_item_id: Optional[int],
    *,
    source: str = "sku_auto",
    match_status: str = "linked",
    variation_id: int = 0,
) -> None:
    _insert(
        conn,
        "ml_item_product_links",
        {
            "item_id": item_id,
            "variation_id": variation_id,
            "source": source,
            "match_status": match_status,
            "producto_item_id": producto_item_id,
            "linked_at": NOW,
        },
    )


def add_sale_price(
    conn,
    item_id: str,
    amount: Optional[float],
    *,
    regular_amount: Optional[float] = None,
    promotion_type: Optional[str] = None,
    campaign_id: Optional[str] = None,
    http_status: int = 200,
    gone_at: Optional[datetime] = None,
) -> None:
    _insert(
        conn,
        "ml_item_sale_prices",
        {
            "item_id": item_id,
            "amount": amount,
            "regular_amount": regular_amount,
            "promotion_type": promotion_type,
            "campaign_id": campaign_id,
            "http_status": http_status,
            "gone_at": gone_at,
        },
    )


def add_stock(
    conn,
    user_product_id: str,
    *,
    full: Optional[int],
    own: Optional[int],
    ml_last_updated: Optional[datetime] = NOW,
) -> None:
    _insert(
        conn,
        "ml_user_product_stock",
        {
            "user_product_id": user_product_id,
            "full_quantity": full,
            "own_quantity": own,
            "total_quantity": (full or 0) + (own or 0),
            "ml_last_updated": ml_last_updated,
        },
    )


def add_stock_locations(
    conn, user_product_id: str, locations: Any, *, ml_last_updated: Optional[datetime] = NOW
) -> None:
    """A stock row with the captured body's `locations` kept in `raw` (a list, or anything else to pin the guard)."""
    row = {
        "user_product_id": user_product_id,
        "raw": json.dumps({"id": user_product_id, "locations": locations}),
        "ml_last_updated": ml_last_updated,
        "http_status": 200,
    }
    values = ", ".join("CAST(:raw AS jsonb)" if name == "raw" else f":{name}" for name in row)
    conn.execute(text(f"INSERT INTO ml_user_product_stock ({', '.join(row)}) VALUES ({values})"), row)


def add_replenishment(conn, user_product_id: str, **columns: Any) -> None:
    """A replenishment state row; `http_status` defaults to the 200 of an `ok` answer."""
    _insert(
        conn,
        "ml_user_product_replenishment",
        {"user_product_id": user_product_id, "http_status": 200, "fetched_at": NOW, **columns},
    )


def add_state(conn, table: str, key_column: str, key: Any, **columns: Any) -> None:
    """A row of any sub-resource state table, keyed by `key_column` (`item_id`, `user_product_id`, `family_id`)."""
    _insert(conn, table, {key_column: key, **columns})


def add_event(conn, item_id: str, event_type: str, observed_at: datetime) -> None:
    log_id = conn.execute(
        text(
            "INSERT INTO ml_change_log (resource_type, entity_id, item_id, observed_at, changed_paths, changes) "
            "VALUES ('item', :item_id, :item_id, :at, '{}', '[]'::jsonb) RETURNING id"
        ),
        {"item_id": item_id, "at": observed_at},
    ).scalar_one()
    _insert(
        conn,
        "ml_item_events",
        {
            "event_type": event_type,
            "item_id": item_id,
            "observed_at": observed_at,
            "change_log_id": log_id,
            "dedupe_key": f"{os.getpid()}-{next(_counter)}".encode(),
        },
    )


def hours_ago(hours: float) -> datetime:
    return NOW - timedelta(hours=hours)
