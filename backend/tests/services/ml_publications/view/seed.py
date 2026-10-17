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

from app.services.ml_publications.mappers import installments_campaign

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
_counter = itertools.count(1)


def _insert(conn, table: str, row: dict[str, Any]) -> None:
    columns = ", ".join(row)
    values = ", ".join(f":{name}" for name in row)
    conn.execute(text(f"INSERT INTO {table} ({columns}) VALUES ({values})"), row)


def add_item(conn, item_id: str, **columns: Any) -> None:
    """An `ml_items` row. A `raw` body given as JSON text fills `installments_campaign` the way the item mapper
    does at ingest (the markup reads the column, never `raw`), unless the test sets that column itself."""
    if isinstance(columns.get("raw"), str) and "installments_campaign" not in columns:
        columns["installments_campaign"] = installments_campaign(json.loads(columns["raw"]).get("sale_terms"))
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
    stock: Optional[int] = None,
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
            "stock": stock,
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


def real_hours_ago(hours: float) -> datetime:
    """Relative to the real clock, for the queries that compare against the database's `now()` (the
    `evento_desde` window). Against the fixed `NOW` those windows expire a day or a week after `NOW`."""
    return datetime.now(timezone.utc) - timedelta(hours=hours)


def create_board_tables(engine) -> None:
    """The tables the Métricas Board reads, next to the store's, in the engine's throwaway schema (the KPI strip
    reads both in one transaction, as production does). Tables that already exist (the products, the stores) are
    left alone."""
    from app.models.mercadolibre_item_publicado import MercadoLibreItemPublicado
    from app.models.ml_group_metrics import MlGroupMetrics
    from app.models.ml_order_item_costo import MlOrderItemCosto
    from app.models.ml_order_metrics import MlOrderMetrics, MlOrderMetricsDirty
    from app.models.ml_orders_ops import MlOpsSyncCursor, MlOrderItemOps, MlOrdersOps
    from app.models.ml_payments import MlPaymentOps
    from app.models.ml_tienda_oficial import MlTiendaOficial
    from app.models.ml_venta_deduccion import MlVentaDeduccion
    from tests.conftest import _restore_pristine_pg_types

    tables = [
        MlOrdersOps.__table__,
        MlOrderItemOps.__table__,
        MlOrderItemCosto.__table__,
        MlOrderMetrics.__table__,
        MlOrderMetricsDirty.__table__,
        MlGroupMetrics.__table__,
        MercadoLibreItemPublicado.__table__,
        MlOpsSyncCursor.__table__,
        MlPaymentOps.__table__,
        MlVentaDeduccion.__table__,
        MlTiendaOficial.__table__,
    ]
    _restore_pristine_pg_types(tables)
    for table in tables:
        table.create(bind=engine, checkfirst=True)


# The audit trails the Eventos/Historial origin reads, with production's column types (`\d` on pricing_db,
# 2026-10-17): `auditoria.fecha` is naive UTC and `tipo_accion` the enum NAME; `ml_write_log` as its migration.
AUDIT_DDL = (
    "CREATE TABLE usuarios (id serial PRIMARY KEY, nombre varchar(255) NOT NULL, username varchar(100) NOT NULL)",
    "CREATE TABLE ml_write_log (id serial PRIMARY KEY, mla varchar(32) NOT NULL, resource varchar(40) NOT NULL, "
    "action varchar(40) NOT NULL, target_id varchar(100), promotion_type varchar(40), payload jsonb, "
    "usuario_id integer REFERENCES usuarios(id), created_at timestamptz NOT NULL DEFAULT now())",
    "CREATE TABLE auditoria (id serial PRIMARY KEY, item_id integer, usuario_id integer NOT NULL REFERENCES "
    "usuarios(id), tipo_accion varchar(50) NOT NULL, valores_anteriores jsonb, valores_nuevos jsonb, "
    "es_masivo boolean DEFAULT false, productos_afectados integer, comentario varchar(500), "
    "fecha timestamp without time zone NOT NULL DEFAULT now())",
    "CREATE TABLE free_shipping_fix_log (id serial PRIMARY KEY, mla_id varchar(30) NOT NULL, success boolean NOT NULL, "
    "skipped boolean NOT NULL DEFAULT false, skip_reason varchar(100), item_price varchar(30), "
    "mandatory_free_shipping boolean NOT NULL DEFAULT false, ml_response_status integer, ml_response_body text, "
    "created_at timestamptz NOT NULL DEFAULT now())",
)


def create_audit_tables(conn) -> None:
    for ddl in AUDIT_DDL:
        conn.execute(text(ddl))


def add_user(conn, nombre: str, username: str) -> int:
    return conn.execute(
        text("INSERT INTO usuarios (nombre, username) VALUES (:n, :u) RETURNING id"), {"n": nombre, "u": username}
    ).scalar_one()


def add_write_log(
    conn,
    mla: str,
    action: str,
    target_id: Optional[str],
    at: datetime,
    usuario_id: Optional[int],
    promotion_type: Optional[str] = None,
) -> None:
    """One `ml_write_log` row as `ml_promotions_write_service._record_write_log` writes it (resource `promotion`)."""
    conn.execute(
        text(
            "INSERT INTO ml_write_log (mla, resource, action, target_id, promotion_type, payload, usuario_id, "
            "created_at) VALUES (:mla, 'promotion', :action, :target, :ptype, CAST(:payload AS jsonb), :user, :at)"
        ),
        {
            "mla": mla,
            "action": action,
            "target": target_id,
            "ptype": promotion_type,
            "payload": json.dumps({"promotion_type": promotion_type, "outcome": "submitted"}),
            "user": usuario_id,
            "at": at,
        },
    )


def add_auditoria(conn, tipo_accion: str, valores_nuevos: dict, at: datetime, usuario_id: int) -> None:
    """One `auditoria` row; `fecha` naive UTC like `registrar_auditoria` and `links._record_audit` leave it."""
    conn.execute(
        text(
            "INSERT INTO auditoria (usuario_id, tipo_accion, valores_nuevos, fecha) "
            "VALUES (:user, :tipo, CAST(:nuevos AS jsonb), :fecha)"
        ),
        {
            "user": usuario_id,
            "tipo": tipo_accion,
            "nuevos": json.dumps(valores_nuevos),
            "fecha": at.astimezone(timezone.utc).replace(tzinfo=None),
        },
    )


def add_free_shipping_fix(conn, mla: str, at: datetime, success: bool = True) -> None:
    """One `free_shipping_fix_log` row as `free_shipping_auto_fix._log_attempt` writes a confirmed fix."""
    _insert(
        conn,
        "free_shipping_fix_log",
        {"mla_id": mla, "success": success, "item_price": "61660.0", "ml_response_status": 200, "created_at": at},
    )
