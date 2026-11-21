"""A throwaway Postgres world for the sell-in allocation tests (T5): the
sell-in tables, the three sale sources, the `sell_dirty` queue WITH its live
triggers, and bare stand-ins for what they reference.

Rows are shaped like production (read on prod, 2026-10-17):
- TN: `fecha_venta` at midnight UTC, `cantidad` a whole NUMERIC, a
  return is `signo = -1` with a POSITIVE `cantidad` (sd_id 3), and TN
  adjustment lines are `signo = 1` with a NEGATIVE `cantidad`;
- ML: one `ml_sale_lines` row per `ml_order_items_ops` row, `qty` > 0, `day`;
- fuera (VPF T4): ventas por fuera loaded from GBP's PDF reports, one document
  per line in `ventas_fuera_operaciones`; a return is an Nc whose line has a
  NEGATIVE `cantidad`, `precio` and `precio_costo` (GBP's sign), often the same
  day as its sale with a higher line id; invented data only. `gbp` writes a row
  of the GBP sync (`ventas_fuera_ml_metricas`), which is NOT a sale source any
  more: only to prove it is ignored.
"""

from __future__ import annotations

import itertools
from contextlib import contextmanager
from datetime import date, datetime, time, timezone
from decimal import Decimal
from time import monotonic, sleep
from typing import Iterator, List, Optional, Tuple

from sqlalchemy import Engine, text

from app.models.cur_exch_history import CurExchHistory
from app.models.tactical import Tactical
from app.models.auditoria import Auditoria
from app.models.combo_componente import ComboComponente
from app.models.costo_si import CostoSiDirty, CostoSiPaso
from app.models.item_cost_list_history import ItemCostListHistory
from app.models.tipo_cambio import TipoCambio
from app.models.ml_costo_si import MlCostoSiDirty
from app.models.tb_item import TBItem
from app.models.ml_orders_ops import MlOrderItemOps
from app.models.ml_sale_line import MlSaleLine
from app.models.producto import ProductoERP
from app.models.sell_dirty import SellDirty
from app.models.sell_in import (
    SellInBonoConsumo,
    SellInBonoMarca,
    SellInCompra,
    SellInCompraItem,
    SellInCompraPedido,
    SellInConsumo,
    SellInModoProducto,
)
from app.models.venta_fuera_ml_metrica import VentaFueraMLMetrica
from app.models.venta_tienda_nube_metrica import VentaTiendaNubeMetrica
from app.services.sell import queue
from app.services.ventas_fuera_pdf.ventas import COSTO_D_FACTOR
from tests.services.sell._schema import PDF_TABLES, PUBLICADOS, throwaway_schema

STUBS = [
    PUBLICADOS,
    "CREATE TABLE usuarios (id INTEGER PRIMARY KEY)",
    "CREATE TABLE proveedores (id INTEGER PRIMARY KEY, nombre TEXT)",
    "CREATE TABLE pedidos_compra (id BIGINT PRIMARY KEY, numero TEXT, numero_factura TEXT)",
    "INSERT INTO usuarios VALUES (7)",
]
TABLES = [
    ProductoERP.__table__,
    Tactical.__table__,  # `tactical_id` of campaigns, bonuses and purchases (tacticals T1)
    SellInBonoMarca.__table__,  # referenced by a generated purchase's bono_id
    SellInCompra.__table__,
    SellInCompraItem.__table__,
    SellInCompraPedido.__table__,
    SellInModoProducto.__table__,  # a manual consumption's source
    SellInConsumo.__table__,
    SellInBonoConsumo.__table__,  # read by the drain's old-product lookup (`queue.products_of`)
    Auditoria.__table__,
    VentaFueraMLMetrica.__table__,
    VentaTiendaNubeMetrica.__table__,
    *PDF_TABLES,  # the fuera sales since VPF T4
    MlOrderItemOps.__table__,
    MlSaleLine.__table__,
    SellDirty.__table__,
    CostoSiDirty.__table__,  # sell.drain also drains the costo SI queue (sell-in-costo-si T2)
    MlCostoSiDirty.__table__,  # ... and then the ML sales it re-costs (T3 PR 7)
    # What the resolved-cost reader reads (`costo_si.lote`): cost bonuses skip sales at costo SI (D2, T3 PR 7).
    CostoSiPaso.__table__,
    ItemCostListHistory.__table__,
    TipoCambio.__table__,
    CurExchHistory.__table__,  # the costo SI reader's ERP rate fallback (D2 reads `lote.en_fechas`)
    ComboComponente.__table__,  # combo sales count as their components' (combos in sell in / sell out)
    TBItem.__table__,  # a combo of the PC category is its own product (`combos.pcs`)
]
_MODELS = {"gbp": VentaFueraMLMetrica, "tn": VentaTiendaNubeMetrica}
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
        for table in (
            "ml_order_items_ops",
            "ventas_fuera_ml_metricas",
            "ventas_tienda_nube_metricas",
            "ventas_fuera_operaciones",
            "ventas_fuera_pdf_cargas",
            "auditoria",
        ):
            conn.execute(text(f"DELETE FROM {table}"))  # ml_sale_lines go with their items, pdf lines with their docs
        conn.execute(text("DELETE FROM sell_in_consumos"))  # a manual block's go with neither purchase nor line
        conn.execute(text("DELETE FROM sell_in_modos_producto"))
        conn.execute(text("DELETE FROM sell_in_compras"))  # cascades to items
        conn.execute(
            text("DELETE FROM combo_componentes WHERE combo_item_id <> 999999001")
        )  # keeps the seed (`_schema`)
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


def modo(engine: Engine, item_id: int, modo: str, desde: date, **manual) -> int:
    """A cost-mode row of `item_id` from `desde` on (a manual one takes `cantidad`, `costo_unit`, `costo_base_unit`)."""
    with engine.begin() as conn:
        return conn.execute(
            text(
                "INSERT INTO sell_in_modos_producto (item_id, modo, desde, cantidad, costo_unit, costo_base_unit, "
                "usuario_id) VALUES (:i, :m, :d, :q, :c, :b, 7) RETURNING id"
            ),
            {
                "i": item_id,
                "m": modo,
                "d": desde,
                "q": manual.get("cantidad"),
                "c": manual.get("costo_unit"),
                "b": manual.get("costo_base_unit"),
            },
        ).scalar()


PDF_PRECIO = Decimal("54298.64")  # a line total without VAT, invented
PDF_COSTO = Decimal("38574.55")  # 'Precio Costo' per unit, invented; Costo D = x 1.065
PDF_EMPRESA = "EMPRESA DEMO SRL"


def venta(
    engine: Engine,
    canal: str,
    item_id: Optional[int],
    cantidad: int,
    dia: date,
    *,
    signo: int = 1,
    cliente: Optional[int] = 202741,
    cliente_nombre: str = "Cliente Demo",
    precio_costo: Optional[Decimal] = None,
    precio: Optional[Decimal] = None,
) -> int:
    """A sale line in `canal` (ml, fuera, tn; gbp: a GBP sync row, not a sale); returns its `venta_ref`.
    A fuera return (`signo=-1`) is an Nc document whose line has a NEGATIVE quantity and amounts;
    `cliente` is its client code (None: the document has no summary, so no code), `precio_costo` the line's
    'Precio Costo' total (default `PDF_COSTO` per unit) and `precio` its price total without VAT
    (default `PDF_PRECIO`); both given unsigned, signed like GBP here."""
    ref = next(_refs)
    with engine.begin() as conn:
        if canal == "fuera":
            q = Decimal(cantidad) * signo
            costo = abs(precio_costo) if precio_costo is not None else PDF_COSTO * abs(q)
            total = abs(precio) if precio is not None else PDF_PRECIO
            carga = conn.execute(
                text(
                    "INSERT INTO ventas_fuera_pdf_cargas (empresa, desde, hasta, documentos, reemplazados, avisos) "
                    "VALUES (:e, :d, :d, 1, 0, '[]') RETURNING id"
                ),
                {"e": PDF_EMPRESA, "d": dia},
            ).scalar()
            operacion = conn.execute(
                text(
                    "INSERT INTO ventas_fuera_operaciones (carga_id, empresa, vendedor, cliente, cliente_codigo, tipo, "
                    "letra, punto_venta, numero, fecha, importe, saldo, total_lineas, recargo_financiero) "
                    "VALUES (:c, :e, 'Vendedor Demo', :cn, :cc, :t, 'A', 9, :n, :d, :p, 0, :p, 0) RETURNING id"
                ),
                {
                    "c": carga,
                    "e": PDF_EMPRESA,
                    "cn": cliente_nombre,
                    "cc": None if cliente is None else str(cliente),
                    "t": "Fc" if signo == 1 else "Nc",
                    "n": ref,
                    "d": dia,
                    "p": total * signo,
                },
            ).scalar()
            conn.execute(
                text(
                    "INSERT INTO ventas_fuera_operacion_lineas (id, operacion_id, renglon, codigo, articulo, cantidad, "
                    "moneda, precio, precio_costo, precio_costo_pp, item_id) "
                    "VALUES (:id, :o, 1, :cod, 'Articulo demo', :q, 'ARS', :p, :pc, :pc, :i)"
                ),
                {
                    "id": ref,
                    "o": operacion,
                    "cod": None if item_id is None else f"C{item_id}",
                    "q": q,
                    "p": total * signo,
                    "pc": costo * signo,
                    "i": item_id,
                },
            )
        elif canal == "ml":
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


# A fuera (PDF) line's columns under the names of the synced tables; `costo_total` is Costo D, so its
# 'Precio Costo' is costo_total / 1.065 (to the cent: Costo D may then be off by less than a cent).
_LINEA_PDF = {"costo_total": "precio_costo", "monto_total": "precio", "cantidad": "cantidad", "item_id": "item_id"}


def update_venta(engine: Engine, canal: str, ref: int, **values) -> None:
    if canal == "fuera":
        with engine.begin() as conn:
            if "fecha_venta" in values:
                conn.execute(
                    text(
                        "UPDATE ventas_fuera_operaciones SET fecha = :f "
                        "WHERE id = (SELECT operacion_id FROM ventas_fuera_operacion_lineas WHERE id = :r)"
                    ),
                    {"f": values.pop("fecha_venta"), "r": ref},
                )
            if "costo_total" in values:
                values["costo_total"] = round(Decimal(values["costo_total"]) / COSTO_D_FACTOR, 2)
            sets = ", ".join(f"{_LINEA_PDF[column]} = :{column}" for column in values)
            if sets:
                conn.execute(
                    text(f"UPDATE ventas_fuera_operacion_lineas SET {sets} WHERE id = :_ref"), {"_ref": ref, **values}
                )
        return
    table = _MODELS[canal].__tablename__
    sets = ", ".join(f"{column} = :{column}" for column in values)
    with engine.begin() as conn:
        conn.execute(text(f"UPDATE {table} SET {sets} WHERE it_transaction = :_ref"), {"_ref": ref, **values})


def delete_venta(engine: Engine, canal: str, ref: int) -> None:
    with engine.begin() as conn:
        if canal == "fuera":  # a re-upload deletes the documents of its scope; their lines cascade
            conn.execute(
                text(
                    "DELETE FROM ventas_fuera_operaciones WHERE id = "
                    "(SELECT operacion_id FROM ventas_fuera_operacion_lineas WHERE id = :r)"
                ),
                {"r": ref},
            )
        elif canal == "ml":
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


def esperar_bloqueado_por(engine: Engine, pid: int) -> None:
    """Until another session waits on a lock the backend `pid` holds, so a concurrency test never orders its two
    waits by timing. Each poll ends its transaction: pg_stat_activity is a snapshot cached for the whole transaction,
    so a waiter whose backend starts after the first poll would never be seen."""
    limite = monotonic() + 20
    consulta = text("SELECT count(*) FROM pg_stat_activity WHERE :pid = ANY(pg_blocking_pids(pid))")
    with engine.connect() as conn:
        while True:
            esperando = conn.execute(consulta, {"pid": pid}).scalar()
            conn.rollback()
            if esperando:
                return
            assert monotonic() < limite, f"nothing ever waited on backend {pid}"
            sleep(0.05)


def combo(engine: Engine, combo_item_id: int, componentes: dict) -> None:
    """`combo_item_id` made of `{componente_item_id: cantidad}` in the bill of materials."""
    with engine.begin() as conn:
        for componente, cantidad in componentes.items():
            conn.execute(
                text("INSERT INTO combo_componentes (combo_item_id, componente_item_id, cantidad) VALUES (:c, :k, :q)"),
                {"c": combo_item_id, "k": componente, "q": cantidad},
            )


def modos_irreproducibles(monkeypatch) -> None:
    """Every product with cost modes fails to replay them, as with rows read mid-change: the failure path the costing
    must survive (a manual block used to be one, until it landed)."""
    from app.services.sell_in import fifo

    original = fifo.Dinero.__init__

    def init(self, lotes, periodos=()) -> None:
        periodos = list(periodos)
        if periodos:
            raise ValueError("cost modes cannot be replayed")
        original(self, lotes, periodos)

    monkeypatch.setattr(fifo.Dinero, "__init__", init)
