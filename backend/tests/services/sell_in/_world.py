"""A throwaway Postgres world for the sell-in allocation tests (T5): the
sell-in tables, the three sale sources, the `sell_dirty` queue WITH its live
triggers, and bare stand-ins for what they reference.

Rows are shaped like production (read on prod, 2026-10-17):
- fuera / TN: `fecha_venta` at midnight UTC, `cantidad` a whole NUMERIC, a
  return is `signo = -1` with a POSITIVE `cantidad` (sd_id 3), and TN
  adjustment lines are `signo = 1` with a NEGATIVE `cantidad`;
- ML: one `ml_sale_lines` row per `ml_order_items_ops` row, `qty` > 0, `day`;
- a fuera return (409 product returns measured) is `signo = -1`, sd_id 3,
  POSITIVE `cantidad`, `cust_id` always filled, often the same day as its sale
  with a higher `it_transaction` (584631 sold, 584724 returned, 2026-09-30).
"""

from __future__ import annotations

import itertools
from contextlib import contextmanager
from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import Iterator, List, Optional, Tuple

from sqlalchemy import Engine, text

from app.models.auditoria import Auditoria
from app.models.ml_orders_ops import MlOrderItemOps
from app.models.ml_sale_line import MlSaleLine
from app.models.producto import ProductoERP
from app.models.sell_dirty import SellDirty
from app.models.sell_in import SellInBonoMarca, SellInCompra, SellInCompraItem, SellInCompraPedido, SellInConsumo
from app.models.venta_fuera_ml_metrica import VentaFueraMLMetrica
from app.models.venta_tienda_nube_metrica import VentaTiendaNubeMetrica
from app.services.sell import queue
from tests.services.sell._schema import throwaway_schema

STUBS = [
    "CREATE TABLE usuarios (id INTEGER PRIMARY KEY)",
    "CREATE TABLE proveedores (id INTEGER PRIMARY KEY, nombre TEXT)",
    "CREATE TABLE pedidos_compra (id BIGINT PRIMARY KEY, numero TEXT)",
    "INSERT INTO usuarios VALUES (7)",
]
TABLES = [
    ProductoERP.__table__,
    SellInBonoMarca.__table__,  # referenced by a generated purchase's bono_id
    SellInCompra.__table__,
    SellInCompraItem.__table__,
    SellInCompraPedido.__table__,
    SellInConsumo.__table__,
    Auditoria.__table__,
    VentaFueraMLMetrica.__table__,
    VentaTiendaNubeMetrica.__table__,
    MlOrderItemOps.__table__,
    MlSaleLine.__table__,
    SellDirty.__table__,
]
_MODELS = {"fuera": VentaFueraMLMetrica, "tn": VentaTiendaNubeMetrica}
_refs = itertools.count(600_000)


def install(engine: Engine) -> None:
    with engine.begin() as conn:
        for statement in queue.UPGRADE_SQL:
            conn.execute(text(statement))
        for item_id in (2964, 2270, 950):
            conn.execute(
                text("INSERT INTO productos_erp (item_id, codigo, descripcion) VALUES (:i, :c, 'Producto')"),
                {"i": item_id, "c": f"C{item_id}"},
            )


@contextmanager
def world(prefix: str) -> Iterator[Engine]:
    with throwaway_schema(prefix, TABLES, STUBS, after=install) as engine:
        yield engine


def clean(engine: Engine) -> None:
    """Empties every table; the queue goes LAST, since deleting sales fires its triggers."""
    with engine.begin() as conn:
        for table in ("ml_order_items_ops", "ventas_fuera_ml_metricas", "ventas_tienda_nube_metricas", "auditoria"):
            conn.execute(text(f"DELETE FROM {table}"))  # ml_sale_lines go with their items
        conn.execute(text("DELETE FROM sell_in_compras"))  # cascades to items and consumptions
        conn.execute(text("DELETE FROM sell_dirty"))


def compra(
    engine: Engine,
    lineas: List[Tuple[int, int, str]],
    fecha: date = date(2026, 10, 1),
    *,
    moneda: str = "ARS",
    tipo_cambio: Optional[str] = None,
    cuenta_desde: str = "compra",
    fecha_ingreso: Optional[date] = None,
    estado: str = "activa",
) -> List[int]:
    """A sell-in purchase with `(item_id, cantidad, monto_asignado)` lines; returns the line ids."""
    total = sum(Decimal(monto) for _, _, monto in lineas)
    with engine.begin() as conn:
        compra_id = conn.execute(
            text(
                "INSERT INTO sell_in_compras (fecha_compra, fecha_ingreso, cuenta_desde, moneda, monto_total, "
                "tipo_cambio, estado, usuario_id) VALUES (:f, :fi, :cd, :m, :t, :tc, :e, 7) RETURNING id"
            ),
            {
                "f": fecha,
                "fi": fecha_ingreso,
                "cd": cuenta_desde,
                "m": moneda,
                "t": total,
                "tc": tipo_cambio,
                "e": estado,
            },
        ).scalar()
        return [
            conn.execute(
                text(
                    "INSERT INTO sell_in_compra_items (compra_id, item_id, cantidad, costo_base_unit, monto_asignado) "
                    "VALUES (:c, :i, :q, 41081.895750, :m) RETURNING id"
                ),
                {"c": compra_id, "i": item, "q": cantidad, "m": monto},
            ).scalar()
            for item, cantidad, monto in lineas
        ]


def venta(
    engine: Engine, canal: str, item_id: int, cantidad: int, dia: date, *, signo: int = 1, cliente: int = 202741
) -> int:
    """A sale line in `canal` (ml, fuera, tn); returns its `venta_ref`. A fuera return is
    `signo=-1` with a POSITIVE `cantidad` and sd_id 3, its customer always filled."""
    ref = next(_refs)
    with engine.begin() as conn:
        if canal == "ml":
            conn.execute(
                text("INSERT INTO ml_order_items_ops (id, order_id, item_id, quantity) VALUES (:id, :o, :mla, :q)"),
                {"id": ref, "o": 2_000_000_000 + ref, "mla": f"MLA{ref}", "q": cantidad},
            )
            conn.execute(
                text(
                    "INSERT INTO ml_sale_lines (item_row_id, order_id, group_key, product, mla, group_date, day, qty, "
                    "gross, tg, tg_known, mtg, mcosto) VALUES (:id, :o, :g, :p, :mla, :gd, :d, :q, 100, 50, true, 50, 30)"
                ),
                {
                    "id": ref,
                    "o": 2_000_000_000 + ref,
                    "g": f"o:{ref}",
                    "p": item_id,
                    "mla": f"MLA{ref}",
                    "gd": datetime.combine(dia, time(15), tzinfo=timezone.utc),
                    "d": dia,
                    "q": cantidad,
                },
            )
        else:
            conn.execute(
                text(
                    f"INSERT INTO {_MODELS[canal].__tablename__} (it_transaction, ct_transaction, item_id, codigo, "
                    "fecha_venta, sd_id, signo, cantidad, monto_total, costo_unitario, cliente, cust_id) "
                    "VALUES (:r, :ct, :i, 'X', :f, :sd, :s, :q, 54298.64, 41081.895750, 'Cliente', :cust)"
                ),
                {
                    "r": ref,
                    "ct": ref + 1,
                    "i": item_id,
                    "f": datetime.combine(dia, time(0), tzinfo=timezone.utc),
                    "sd": 1 if signo == 1 else 3,
                    "s": signo,
                    "q": Decimal(cantidad),
                    "cust": cliente,
                },
            )
    return ref


def update_venta(engine: Engine, canal: str, ref: int, **values) -> None:
    table = _MODELS[canal].__tablename__
    sets = ", ".join(f"{column} = :{column}" for column in values)
    with engine.begin() as conn:
        conn.execute(text(f"UPDATE {table} SET {sets} WHERE it_transaction = :_ref"), {"_ref": ref, **values})


def delete_venta(engine: Engine, canal: str, ref: int) -> None:
    with engine.begin() as conn:
        if canal == "ml":
            conn.execute(text("DELETE FROM ml_order_items_ops WHERE id = :r"), {"r": ref})
        else:
            conn.execute(text(f"DELETE FROM {_MODELS[canal].__tablename__} WHERE it_transaction = :r"), {"r": ref})


def consumos(engine: Engine) -> List[Tuple[int, str, int, int, int, Decimal]]:
    """`(compra_item_id, canal, venta_ref, item_id, unidades, descuento_ars)`, in a stable order."""
    with engine.connect() as conn:
        return [
            tuple(row)
            for row in conn.execute(
                text(
                    "SELECT compra_item_id, canal, venta_ref, item_id, unidades, descuento_ars FROM sell_in_consumos "
                    "ORDER BY compra_item_id, canal, venta_ref"
                )
            )
        ]


def consumo_ids(engine: Engine) -> List[int]:
    with engine.connect() as conn:
        return [r[0] for r in conn.execute(text("SELECT id FROM sell_in_consumos ORDER BY id"))]


def queued(engine: Engine) -> List[Tuple[str, int]]:
    with engine.connect() as conn:
        return [tuple(r) for r in conn.execute(text("SELECT canal, venta_ref FROM sell_dirty ORDER BY 1, 2"))]
