"""A throwaway Postgres world for the brand bonus (T3c-3): the sell-in tables,
the bonus table and its queue WITH the live triggers, the invoiced-lines
snapshot, the FX table, the sale sources (with the `sell_dirty` triggers) and a
stand-in for `pedidos_compra` with the columns the bonus reads.

Shapes follow production: `pedidos_compra.fecha_factura` is the supplier
invoice date (T3c-1), `tipo_cambio` the operation's effective ARS-per-USD rate
(NULL on most ARS operations), and the snapshot holds whole invoiced units net
of credit notes per (pedido, item) (T3c-2).
"""

from __future__ import annotations

import itertools
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from typing import Dict, Iterator, List, Optional, Tuple

from sqlalchemy import Engine, text

from app.models.pedido_compra_linea_facturada import PedidoCompraLineaFacturada
from app.models.sell_in import SellInBonoDirty, SellInBonoItem, SellInBonoMarca
from app.models.tipo_cambio import TipoCambio
from app.services.sell import queue as sell_queue
from app.services.sell_in import bono_queue
from tests.services.sell._schema import throwaway_schema
from tests.services.sell_in import _world as w

STUBS = [
    "CREATE TABLE usuarios (id INTEGER PRIMARY KEY)",
    "CREATE TABLE proveedores (id INTEGER PRIMARY KEY, nombre TEXT)",
    "CREATE TABLE pedidos_compra (id BIGINT PRIMARY KEY, numero TEXT NOT NULL, proveedor_id INTEGER NOT NULL, "
    "moneda VARCHAR(3) NOT NULL, estado VARCHAR(24) NOT NULL DEFAULT 'aprobado', tipo_cambio NUMERIC(18, 6), "
    "fecha_factura DATE, observaciones TEXT, numero_factura TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now())",
    # What was received, for the bonus panel's pending / no-brand-line groups (`bonos_alcance`).
    "CREATE TABLE pedido_compra_ingresos (id BIGSERIAL PRIMARY KEY, pedido_id BIGINT NOT NULL, item_id INTEGER NOT NULL, "
    "cantidad_recibida NUMERIC(18, 6) NOT NULL)",
    "INSERT INTO usuarios VALUES (7), (8)",
    "INSERT INTO proveedores VALUES (31, 'TP-Link Argentina'), (32, 'Otro proveedor')",
]
_SELL_IN = [t for t in w.TABLES if t.name not in ("productos_erp", "sell_in_bonos_marca")]
TABLES = [
    w.ProductoERP.__table__,
    SellInBonoMarca.__table__,
    SellInBonoItem.__table__,
    *_SELL_IN,
    PedidoCompraLineaFacturada.__table__,
    TipoCambio.__table__,
    SellInBonoDirty.__table__,
]
_pedidos = itertools.count(5000)

TPLINK, MERCUSYS = "TP-LINK", "MERCUSYS"
# item -> (marca, costo, moneda_costo)
PRODUCTOS = {
    2964: (TPLINK, "41.50", "USD"),
    2270: (TPLINK, "12000.00", "ARS"),
    950: (MERCUSYS, "9.90", "USD"),
}


def _install(engine: Engine) -> None:
    with engine.begin() as conn:
        for statement in sell_queue.UPGRADE_SQL + bono_queue.UPGRADE_SQL:
            conn.execute(text(statement))
        for item_id, (marca, costo, moneda) in PRODUCTOS.items():
            conn.execute(
                text(
                    "INSERT INTO productos_erp (item_id, codigo, descripcion, marca, costo, moneda_costo) "
                    "VALUES (:i, :c, 'Producto', :m, :costo, :mon)"
                ),
                {"i": item_id, "c": f"C{item_id}", "m": marca, "costo": costo, "mon": moneda},
            )
        conn.execute(text("DELETE FROM sell_in_bono_dirty"))  # the products' own inserts queue nothing useful


@contextmanager
def world(prefix: str) -> Iterator[Engine]:
    with throwaway_schema(prefix, TABLES, STUBS, after=_install) as engine:
        yield engine


def clean(engine: Engine) -> None:
    """Empties what the tests write; the queues go LAST, since deletes fire their triggers."""
    w.clean(engine)
    with engine.begin() as conn:
        for table in (
            "sell_in_compras",
            "sell_in_bonos_marca",
            "pedido_compra_lineas_facturadas",
            "pedido_compra_ingresos",
            "pedidos_compra",
        ):
            conn.execute(text(f"DELETE FROM {table}"))
        conn.execute(text("DELETE FROM tipo_cambio"))
        # Products a test brought into the catalog (only the world's own ones stay).
        conn.execute(text("DELETE FROM productos_erp WHERE NOT (item_id = ANY(:i))"), {"i": list(PRODUCTOS)})
        conn.execute(
            text(
                "UPDATE productos_erp SET marca = CASE item_id WHEN 950 THEN 'MERCUSYS' ELSE 'TP-LINK' END, "
                "categoria = NULL"
            )
        )
        conn.execute(text("DELETE FROM sell_in_bono_dirty"))
        conn.execute(text("DELETE FROM sell_dirty"))


def bono(
    engine: Engine,
    marca: str = TPLINK,
    monto: str = "2.00",
    moneda: str = "USD",
    desde: date = date(2026, 10, 1),
    hasta: date = date(2026, 10, 31),
    estado: str = "activa",
) -> int:
    with engine.begin() as conn:
        return conn.execute(
            text(
                "INSERT INTO sell_in_bonos_marca (marca, monto_unit, moneda, fecha_desde, fecha_hasta, estado, "
                "usuario_id) VALUES (:m, :monto, :mon, :d, :h, :e, 7) RETURNING id"
            ),
            {"m": marca, "monto": monto, "mon": moneda, "d": desde, "h": hasta, "e": estado},
        ).scalar()


def bono_alcance(
    engine: Engine,
    alcance: str,
    *,
    categoria: Optional[str] = None,
    pedido_id: Optional[int] = None,
    modelos: Tuple[int, ...] = (),
    tipo: str = "por_unidad",
    monto: Optional[str] = "2.00",
    porcentaje: Optional[str] = None,
    moneda: str = "USD",
    desde: date = date(2026, 10, 1),
    hasta: date = date(2026, 10, 31),
    estado: str = "activa",
) -> int:
    """A bonus reaching a category, some models or one invoice (T3e); `monto` is ignored for a percentage."""
    with engine.begin() as conn:
        bono_id = conn.execute(
            text(
                "INSERT INTO sell_in_bonos_marca (alcance, categoria, pedido_id, tipo, monto_unit, porcentaje, moneda, "
                "fecha_desde, fecha_hasta, estado, usuario_id) VALUES (:a, :c, :p, :t, :monto, :pct, :mon, :d, :h, "
                ":e, 7) RETURNING id"
            ),
            {
                "a": alcance,
                "c": categoria,
                "p": pedido_id,
                "t": tipo,
                "monto": None if tipo == "porcentaje" else monto,
                "pct": porcentaje,
                "mon": moneda,
                "d": desde,
                "h": hasta,
                "e": estado,
            },
        ).scalar()
        for item_id in modelos:
            conn.execute(
                text("INSERT INTO sell_in_bono_items (bono_id, item_id) VALUES (:b, :i)"), {"b": bono_id, "i": item_id}
            )
    return bono_id


def update_bono(engine: Engine, bono_id: int, **values) -> None:
    sets = ", ".join(f"{column} = :{column}" for column in values)
    with engine.begin() as conn:
        conn.execute(text(f"UPDATE sell_in_bonos_marca SET {sets} WHERE id = :_id"), {"_id": bono_id, **values})


def pedido(
    engine: Engine,
    lineas: Dict[int, int],
    fecha_factura: Optional[date] = date(2026, 10, 10),
    *,
    moneda: str = "USD",
    tipo_cambio: Optional[str] = "1450.000000",
    estado: str = "aprobado",
    proveedor_id: int = 31,
) -> int:
    """A Compras operation with its invoiced units per item (`{item_id: cantidad}`); returns its id."""
    pedido_id = next(_pedidos)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO pedidos_compra (id, numero, proveedor_id, moneda, estado, tipo_cambio, fecha_factura) "
                "VALUES (:id, :n, :p, :m, :e, :tc, :f)"
            ),
            {
                "id": pedido_id,
                "n": f"OC-{pedido_id}",
                "p": proveedor_id,
                "m": moneda,
                "e": estado,
                "tc": tipo_cambio,
                "f": fecha_factura,
            },
        )
    set_lineas(engine, pedido_id, lineas)
    return pedido_id


def update_pedido(engine: Engine, pedido_id: int, **values) -> None:
    sets = ", ".join(f"{column} = :{column}" for column in values)
    with engine.begin() as conn:
        conn.execute(text(f"UPDATE pedidos_compra SET {sets} WHERE id = :_id"), {"_id": pedido_id, **values})


def set_lineas(engine: Engine, pedido_id: int, lineas: Dict[int, int]) -> None:
    """Makes the snapshot of `pedido_id` hold exactly `lineas`, the way the T3c-2 reconcile does (upsert + delete)."""
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM pedido_compra_lineas_facturadas WHERE pedido_id = :p AND NOT (item_id = ANY(:items))"),
            {"p": pedido_id, "items": list(lineas)},
        )
        for item_id, cantidad in sorted(lineas.items()):
            conn.execute(
                text(
                    "INSERT INTO pedido_compra_lineas_facturadas (pedido_id, item_id, cantidad) VALUES (:p, :i, :q) "
                    "ON CONFLICT (pedido_id, item_id) DO UPDATE SET cantidad = EXCLUDED.cantidad"
                ),
                {"p": pedido_id, "i": item_id, "q": cantidad},
            )


def set_importe(engine: Engine, pedido_id: int, item_id: int, importe: Optional[str], moneda: Optional[str]) -> None:
    """The invoiced net of one snapshot line (T3g-1), the base of a % bonus; NULL both when currencies mix."""
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE pedido_compra_lineas_facturadas SET importe_neto = :imp, moneda = :mon "
                "WHERE pedido_id = :p AND item_id = :i"
            ),
            {"imp": importe, "mon": moneda, "p": pedido_id, "i": item_id},
        )


def set_categoria(engine: Engine, item_id: int, categoria: Optional[str]) -> None:
    with engine.begin() as conn:
        conn.execute(text("UPDATE productos_erp SET categoria = :c WHERE item_id = :i"), {"c": categoria, "i": item_id})


def tipo_cambio(engine: Engine, fecha: date, venta: float) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO tipo_cambio (fecha, moneda, compra, venta) VALUES (:f, 'USD', :v, :v)"),
            {"f": fecha, "v": venta},
        )


def generadas(engine: Engine) -> List[Tuple]:
    """`(bono_id, bono_pedido_id, estado, moneda, monto_total, tipo_cambio, fecha_compra, proveedor_id)`."""
    with engine.connect() as conn:
        return [
            tuple(r)
            for r in conn.execute(
                text(
                    "SELECT bono_id, bono_pedido_id, estado, moneda, monto_total, tipo_cambio, fecha_compra, "
                    "proveedor_id FROM sell_in_compras WHERE origen = 'bono_marca' ORDER BY bono_id, bono_pedido_id"
                )
            )
        ]


def items_de(engine: Engine, bono_id: int, pedido_id: int) -> List[Tuple[int, int, Decimal]]:
    """`(item_id, cantidad, monto_asignado)` of the purchase generated for (bonus, operation)."""
    with engine.connect() as conn:
        return [
            tuple(r)
            for r in conn.execute(
                text(
                    "SELECT i.item_id, i.cantidad, i.monto_asignado FROM sell_in_compra_items i "
                    "JOIN sell_in_compras c ON c.id = i.compra_id WHERE c.bono_id = :b AND c.bono_pedido_id = :p "
                    "ORDER BY i.item_id"
                ),
                {"b": bono_id, "p": pedido_id},
            )
        ]


def compra_id(engine: Engine, bono_id: int, pedido_id: int) -> int:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT id FROM sell_in_compras WHERE bono_id = :b AND bono_pedido_id = :p"),
            {"b": bono_id, "p": pedido_id},
        ).scalar_one()


def queued(engine: Engine) -> List[Tuple[str, int]]:
    with engine.connect() as conn:
        return [tuple(r) for r in conn.execute(text("SELECT tipo, ref FROM sell_in_bono_dirty ORDER BY 1, 2"))]


def queue_rows(engine: Engine) -> List[Tuple[str, int, int, Optional[str]]]:
    with engine.connect() as conn:
        return [
            tuple(r)
            for r in conn.execute(text("SELECT tipo, ref, attempts, last_error FROM sell_in_bono_dirty ORDER BY 1, 2"))
        ]


def clear_queue(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM sell_in_bono_dirty"))


def auditoria(engine: Engine) -> List[str]:
    with engine.connect() as conn:
        return [r[0] for r in conn.execute(text("SELECT tipo_accion FROM auditoria ORDER BY id"))]
