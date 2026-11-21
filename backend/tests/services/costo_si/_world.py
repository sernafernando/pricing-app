"""A throwaway Postgres world for costo SI (sell-in-costo-si T2): the GBP mirror (movements, orders, purchase
invoices, list cost history), Compras links, sell ins and bonuses, ML publications and Full stock, combos, and the
costo SI tables with their queue triggers. Invented data only, shaped like the rows read on prod for T1
(handoffs/sell-in-costo-si-t1.md): GBP timestamps are naive local time, a purchase's `it_cd` is its stock entry and
`ct_date` the supplier invoice date, `it_storeprevious` the depot balance before the movement."""

from __future__ import annotations

import itertools
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from typing import Iterator, Optional

from sqlalchemy import Engine, text

from app.models.combo_componente import ComboComponente
from app.models.commercial_transaction import CommercialTransaction
from app.models.costo_si import (
    CostoSiBackup,
    CostoSiDirty,
    CostoSiFacturaTc,
    CostoSiPaso,
    CostoSiStockDiario,
)
from app.models.item_cost_list_history import ItemCostListHistory
from app.models.item_transaction import ItemTransaction
from app.models.producto import ProductoERP
from app.models.sale_order_detail import SaleOrderDetail
from app.models.sale_order_detail_history import SaleOrderDetailHistory
from app.models.sale_order_header import SaleOrderHeader
from app.models.sale_order_header_history import SaleOrderHeaderHistory
from app.models.sell_in import SellInBonoItem, SellInBonoMarca, SellInCompra, SellInCompraItem, SellInCompraPedido
from app.models.tactical import Tactical
from app.models.tb_item import TBItem
from app.models.cur_exch_history import CurExchHistory
from app.models.tipo_cambio import TipoCambio
from app.services.costo_si import queue
from tests.services.sell._schema import throwaway_schema

STUBS = [
    "CREATE TABLE usuarios (id INTEGER PRIMARY KEY)",
    "INSERT INTO usuarios VALUES (7)",
    "CREATE TABLE proveedores (id INTEGER PRIMARY KEY, nombre TEXT)",
    "CREATE TABLE pedidos_compra (id BIGINT PRIMARY KEY, tipo_cambio NUMERIC(18, 6), tipo_cambio_manual NUMERIC(18, 6))",
    "CREATE TABLE pedido_compra_facturas (id BIGSERIAL PRIMARY KEY, pedido_id BIGINT NOT NULL REFERENCES pedidos_compra(id),"
    " ct_transaction_id BIGINT NOT NULL, fecha_factura DATE)",
    # The view of live purchase invoices, as a plain table: the engine only reads `clasificacion`.
    "CREATE TABLE v_facturas_compra_vigentes (ct_transaction BIGINT PRIMARY KEY, clasificacion TEXT, ct_docnumber TEXT)",
    "CREATE TABLE ml_items (item_id TEXT PRIMARY KEY, inventory_id TEXT, user_product_id TEXT)",
    "CREATE TABLE ml_item_product_links (item_id TEXT, variation_id BIGINT DEFAULT 0, producto_item_id INTEGER,"
    " PRIMARY KEY (item_id, variation_id))",
    "CREATE TABLE ml_user_product_stock (user_product_id TEXT PRIMARY KEY, full_quantity INTEGER)",
    "CREATE TABLE ml_item_variations (item_id TEXT, variation_id BIGINT, user_product_id TEXT, gone_at TIMESTAMPTZ,"
    " PRIMARY KEY (item_id, variation_id))",
    # ML sales as the app stores them (only the columns costo SI reads) and the Auditoría's daily stock photo.
    "CREATE TABLE ml_orders_ops (order_id BIGINT PRIMARY KEY, status TEXT, date_created TIMESTAMPTZ, shipping_id BIGINT)",
    "CREATE TABLE ml_order_items_ops (id SERIAL PRIMARY KEY, order_id BIGINT NOT NULL, item_id TEXT NOT NULL,"
    " variation_id BIGINT, quantity INTEGER)",
    "CREATE TABLE ml_shipments_ops (shipment_id BIGINT PRIMARY KEY, logistic_type TEXT)",
    # A sell-out line (a tactical's included): only the columns a cost reader could be tempted to read.
    "CREATE TABLE sell_out_campanas (id BIGSERIAL PRIMARY KEY, tactical_id BIGINT, tactical_linea SMALLINT, tipo TEXT,"
    " porcentaje NUMERIC(7, 4), monto_unit NUMERIC(18, 2), fecha_desde DATE, fecha_hasta DATE, estado TEXT)",
    "CREATE TABLE producto_stock_diario (fecha DATE, item_id INTEGER, stock_erp INTEGER DEFAULT 0,"
    " stock_full INTEGER DEFAULT 0, PRIMARY KEY (fecha, item_id))",
]

TABLES = [
    ProductoERP.__table__,
    TBItem.__table__,
    ComboComponente.__table__,
    Tactical.__table__,
    SellInBonoMarca.__table__,
    SellInBonoItem.__table__,
    SellInCompra.__table__,
    SellInCompraItem.__table__,
    SellInCompraPedido.__table__,
    TipoCambio.__table__,
    CurExchHistory.__table__,
    CommercialTransaction.__table__,
    ItemTransaction.__table__,
    SaleOrderHeader.__table__,
    SaleOrderDetail.__table__,
    SaleOrderHeaderHistory.__table__,
    SaleOrderDetailHistory.__table__,
    ItemCostListHistory.__table__,
    CostoSiPaso.__table__,
    CostoSiBackup.__table__,
    CostoSiDirty.__table__,
    CostoSiStockDiario.__table__,
    CostoSiFacturaTc.__table__,
]

MARCA = "MARCA DEMO"
_ids = itertools.count(500_000)


def install(engine: Engine) -> None:
    with engine.begin() as conn:
        for statement in queue.UPGRADE_SQL:
            conn.execute(text(statement))


@contextmanager
def world(prefix: str) -> Iterator[Engine]:
    with throwaway_schema(prefix, TABLES, STUBS, after=install) as engine:
        yield engine


def clean(engine: Engine) -> None:
    with engine.begin() as conn:
        for table in (
            "sell_in_compras",
            "sell_in_bonos_marca",
            "tacticals",
            "pedido_compra_facturas",
            "pedidos_compra",
            "v_facturas_compra_vigentes",
            "tb_item_transactions",
            "tb_commercial_transactions",
            "tb_sale_order_header",
            "tb_sale_order_detail",
            "tb_sale_order_header_history",
            "tb_sale_order_detail_history",
            "tb_item_cost_list_history",
            "tipo_cambio",
            "ml_items",
            "ml_item_product_links",
            "ml_user_product_stock",
            "ml_item_variations",
            "ml_orders_ops",
            "ml_order_items_ops",
            "ml_shipments_ops",
            "sell_out_campanas",
            "producto_stock_diario",
            "tb_item",
            "costo_si_pasos",
            "costo_si_backups",
            "costo_si_stock_diario",
            "costo_si_factura_tc",
            "productos_erp",
        ):
            conn.execute(text(f"DELETE FROM {table}"))
        conn.execute(text("DELETE FROM combo_componentes WHERE combo_item_id <> 999999001"))
        conn.execute(text("DELETE FROM costo_si_dirty"))  # last: the deletes above queue products


def run(engine: Engine, sql: str, **params) -> None:
    with engine.begin() as conn:
        conn.execute(text(sql), params)


def rows(engine: Engine, sql: str, **params) -> list:
    with engine.connect() as conn:
        return [tuple(r) for r in conn.execute(text(sql), params)]


def producto(
    engine: Engine,
    item_id: int,
    marca: str = MARCA,
    categoria: str = "CAMARAS",
    cat_id: int = 3,
    moneda: str = "USD",
    costo: Optional[str] = None,
) -> None:
    """A product whose cost currency is `moneda` (costo SI lives in it, L18) and current list cost `costo`."""
    run(
        engine,
        "INSERT INTO productos_erp (item_id, codigo, descripcion, marca, categoria, moneda_costo, costo) "
        "VALUES (:i, :c, 'Producto', :m, :cat, :mon, :costo)",
        i=item_id,
        c=f"C{item_id}",
        m=marca,
        cat=categoria,
        mon=moneda,
        costo=float(costo) if costo is not None else None,
    )
    run(
        engine,
        "INSERT INTO tb_item (comp_id, item_id, item_code, cat_id) VALUES (1, :i, :c, :cat)",
        i=item_id,
        c=f"C{item_id}",
        cat=cat_id,
    )


def costo_lista(engine: Engine, item_id: int, cuando: datetime, precio: str, curr_id: int = 2) -> None:
    run(
        engine,
        "INSERT INTO tb_item_cost_list_history (iclh_id, coslis_id, item_id, iclh_price, curr_id, iclh_cd) "
        "VALUES (:id, 1, :i, :p, :curr, :cd)",
        id=next(_ids),
        i=item_id,
        p=Decimal(precio),
        curr=curr_id,
        cd=cuando,
    )


def movimiento(
    engine: Engine,
    item_id: int,
    cuando: datetime,
    qty: int,
    previo: int,
    sd_id: int = 1,
    stor_id: int = 1,
    soh_id: Optional[int] = None,
    cust_id: Optional[int] = None,
) -> int:
    """One GBP movement of depot `stor_id` (a sale `sd_id` 1 by default), with the depot balance before it."""
    ct = next(_ids)
    run(
        engine,
        "INSERT INTO tb_commercial_transactions (ct_transaction, bra_id, sd_id, ct_date, cust_id) "
        "VALUES (:ct, 1, :sd, :d, :cust)",
        ct=ct,
        sd=sd_id,
        d=cuando,
        cust=cust_id,
    )
    run(
        engine,
        "INSERT INTO tb_item_transactions (it_transaction, ct_transaction, bra_id, item_id, it_qty, stor_id, "
        "it_storeprevious, it_cd, it_soh_id) VALUES (:it, :ct, 1, :i, :q, :s, :p, :cd, :soh)",
        it=next(_ids),
        ct=ct,
        i=item_id,
        q=qty,
        s=stor_id,
        p=previo,
        cd=cuando,
        soh=soh_id,
    )
    return ct


def factura(
    engine: Engine,
    item_id: int,
    fecha: date,
    entrada: datetime,
    qty: int,
    precio: str,
    previo: int,
    curr_id: int = 2,
    supp_id: int = 14,
    pedido: Optional[int] = None,
    tc_pedido: Optional[str] = None,
) -> int:
    """A purchase invoice dated `fecha` (supplier date) whose goods entered depot 1 at `entrada`; optionally linked
    to a Compras operation `pedido` with its TC."""
    ct = next(_ids)
    run(
        engine,
        "INSERT INTO tb_commercial_transactions (ct_transaction, bra_id, sd_id, ct_date, supp_id) "
        "VALUES (:ct, 1, 101, :d, :s)",
        ct=ct,
        d=datetime.combine(fecha, datetime.min.time()),
        s=supp_id,
    )
    run(engine, "INSERT INTO v_facturas_compra_vigentes VALUES (:ct, 'FACTURA', :n)", ct=ct, n=f"0001-{ct}")
    run(
        engine,
        "INSERT INTO tb_item_transactions (it_transaction, ct_transaction, bra_id, item_id, it_qty, it_price, curr_id,"
        " stor_id, it_storeprevious, it_cd) VALUES (:it, :ct, 1, :i, :q, :p, :c, 1, :prev, :cd)",
        it=next(_ids),
        ct=ct,
        i=item_id,
        q=qty,
        p=Decimal(precio),
        c=curr_id,
        prev=previo,
        cd=entrada,
    )
    if pedido is not None:
        run(
            engine,
            "INSERT INTO pedidos_compra (id, tipo_cambio) VALUES (:p, :tc) ON CONFLICT (id) DO NOTHING",
            p=pedido,
            tc=Decimal(tc_pedido) if tc_pedido else None,
        )
        run(
            engine,
            "INSERT INTO pedido_compra_facturas (pedido_id, ct_transaction_id) VALUES (:p, :ct)",
            p=pedido,
            ct=ct,
        )
    return ct


def sell_in_compra(engine: Engine, item_id: int, pedido: int, porcentaje: str, fecha: date) -> int:
    """A Compras sell in of `porcentaje` % on `item_id`, for operation `pedido`."""
    with engine.begin() as conn:
        cid = conn.execute(
            text(
                "INSERT INTO sell_in_compras (fecha_compra, moneda, monto_total, tipo, porcentaje, tipo_cambio, usuario_id) "
                "VALUES (:f, 'USD', 1, 'porcentaje', :p, 1, 7) RETURNING id"
            ).bindparams(),
            {"f": fecha, "p": Decimal(porcentaje)},
        ).scalar()
        conn.execute(
            text("INSERT INTO sell_in_compra_pedidos (compra_id, pedido_compra_id) VALUES (:c, :p)"),
            {"c": cid, "p": pedido},
        )
        conn.execute(
            text(
                "INSERT INTO sell_in_compra_items (compra_id, item_id, cantidad, costo_base_unit, monto_asignado) "
                "VALUES (:c, :i, 1, 1, 1)"
            ),
            {"c": cid, "i": item_id},
        )
    return cid


def tactical(engine: Engine, desde: date, hasta: date, marca: str = MARCA) -> int:
    """A sell-in tactical of the brand (the loyalty is loaded through one on prod: bono 94, tactical 38)."""
    with engine.begin() as conn:
        return conn.execute(
            text(
                "INSERT INTO tacticals (tipo, nombre, marca, fecha_desde, fecha_hasta, moneda, usuario_id) "
                "VALUES ('sell_in', 'Loyalty', :m, :d, :h, 'ARS', 7) RETURNING id"
            ),
            {"m": marca, "d": desde, "h": hasta},
        ).scalar()


def bono_marca(
    engine: Engine,
    porcentaje: str,
    desde: date,
    hasta: date,
    marca: str = MARCA,
    tactical_id: Optional[int] = None,
    incluye_iva: bool = False,
) -> int:
    """A brand bonus of the sale-cost kind by %, like the loyalty (S6); optionally one line of a tactical."""
    with engine.begin() as conn:
        return conn.execute(
            text(
                "INSERT INTO sell_in_bonos_marca (alcance, marca, tipo, porcentaje, moneda, fecha_desde, fecha_hasta, "
                "base, usuario_id, tactical_id, tactical_linea, incluye_iva) "
                "VALUES ('marca', :m, 'porcentaje', :p, 'ARS', :d, :h, 'costo_venta', 7, :t, :l, :iva) RETURNING id"
            ),
            {
                "m": marca,
                "p": Decimal(porcentaje),
                "d": desde,
                "h": hasta,
                "t": tactical_id,
                "l": 1 if tactical_id is not None else None,
                "iva": incluye_iva,
            },
        ).scalar()


def bono_modelos(
    engine: Engine,
    item_ids: list,
    tipo: str,
    valor: str,
    desde: date,
    hasta: date,
    *,
    tope_unidades: Optional[int] = None,
    tope_monto: Optional[str] = None,
    moneda: str = "ARS",
    tactical_id: Optional[int] = None,
    incluye_iva: bool = False,
) -> int:
    """A sale-cost sell-in line over models, % or per unit, as a tactical loads it (tactical 41 / 54 on prod)."""
    with engine.begin() as conn:
        bono = conn.execute(
            text(
                "INSERT INTO sell_in_bonos_marca (alcance, tipo, porcentaje, monto_unit, moneda, fecha_desde, fecha_hasta,"
                " base, usuario_id, tactical_id, tactical_linea, tope_unidades, tope_monto, incluye_iva) "
                "VALUES ('modelos', :t, :p, :mu, :m, :d, :h, 'costo_venta', 7, :tac, :l, :tu, :tm, :iva) RETURNING id"
            ),
            {
                "t": tipo,
                "p": Decimal(valor) if tipo == "porcentaje" else None,
                "mu": Decimal(valor) if tipo == "por_unidad" else None,
                "m": moneda,
                "d": desde,
                "h": hasta,
                "tac": tactical_id,
                "l": 1 if tactical_id is not None else None,
                "tu": tope_unidades,
                "tm": Decimal(tope_monto) if tope_monto else None,
                "iva": incluye_iva,
            },
        ).scalar()
    for item_id in item_ids:
        run(engine, "INSERT INTO sell_in_bono_items (bono_id, item_id) VALUES (:b, :i)", b=bono, i=item_id)
    return bono


def sell_out_tactical(engine: Engine, tactical_id: int, porcentaje: str, desde: date, hasta: date) -> None:
    run(
        engine,
        "INSERT INTO sell_out_campanas (tactical_id, tactical_linea, tipo, porcentaje, fecha_desde, fecha_hasta, estado)"
        " VALUES (:t, 1, 'porcentaje', :p, :d, :h, 'activa')",
        t=tactical_id,
        p=Decimal(porcentaje),
        d=desde,
        h=hasta,
    )


def tipo_cambio(engine: Engine, fecha: date, venta: float) -> None:
    run(engine, "INSERT INTO tipo_cambio (fecha, moneda, compra, venta) VALUES (:f, 'USD', :v, :v)", f=fecha, v=venta)


def cambio_erp(engine: Engine, cuando: datetime, valor: float, desde: int = 2, hacia: int = 1) -> None:
    """A `tb_cur_exch_history` row (the ERP's rate history): `desde` -> `hacia` currency ids, 2 = USD, 1 = ARS."""
    run(
        engine,
        "INSERT INTO tb_cur_exch_history (ceh_id, comp_id, curr_id_1, curr_id_2, ceh_cd, ceh_exchange)"
        " VALUES (:i, 1, :d, :h, :c, :v)",
        i=next(_ids),
        d=desde,
        h=hacia,
        c=cuando,
        v=valor,
    )


def publicacion_full(engine: Engine, mla: str, producto_item_id: int, inventory_id: str, full_hoy: int) -> None:
    up = f"UP-{inventory_id}"
    run(engine, "INSERT INTO ml_items VALUES (:m, :inv, :up)", m=mla, inv=inventory_id, up=up)
    run(
        engine,
        "INSERT INTO ml_item_product_links (item_id, variation_id, producto_item_id) VALUES (:m, 0, :p)",
        m=mla,
        p=producto_item_id,
    )
    run(engine, "INSERT INTO ml_user_product_stock VALUES (:up, :q)", up=up, q=full_hoy)


def publicacion_full_variacion(
    engine: Engine, mla: str, variation_id: int, producto_item_id: int, full_hoy: int
) -> None:
    """A publication with variations whose variation `variation_id` is linked to `producto_item_id`: ML keeps the
    inventory per variation (its own user product), the item itself has none."""
    up = f"UP-{mla}-{variation_id}"
    run(engine, "INSERT INTO ml_items VALUES (:m, NULL, NULL) ON CONFLICT DO NOTHING", m=mla)
    run(
        engine,
        "INSERT INTO ml_item_variations (item_id, variation_id, user_product_id) VALUES (:m, :v, :up)",
        m=mla,
        v=variation_id,
        up=up,
    )
    run(
        engine,
        "INSERT INTO ml_item_product_links (item_id, variation_id, producto_item_id) VALUES (:m, :v, :p)",
        m=mla,
        v=variation_id,
        p=producto_item_id,
    )
    run(engine, "INSERT INTO ml_user_product_stock VALUES (:up, :q)", up=up, q=full_hoy)


def venta_ml(
    engine: Engine,
    mla: str,
    cuando: datetime,
    qty: int,
    logistic_type: str = "fulfillment",
    status: str = "paid",
    variation_id: Optional[int] = None,
) -> None:
    """One ML sale of `mla` as the app stores it: order, item and shipment."""
    order_id = next(_ids)
    run(engine, "INSERT INTO ml_shipments_ops VALUES (:s, :l)", s=order_id, l=logistic_type)
    run(engine, "INSERT INTO ml_orders_ops VALUES (:o, :st, :c, :o)", o=order_id, st=status, c=cuando)
    run(
        engine,
        "INSERT INTO ml_order_items_ops (order_id, item_id, variation_id, quantity) VALUES (:o, :m, :v, :q)",
        o=order_id,
        m=mla,
        v=variation_id,
        q=qty,
    )


def foto_ml(engine: Engine, item_id: int, fecha: date, stock_full: int) -> None:
    """The Auditoría's daily photo of a product (`stock.snapshot`, 06:00 local): ML's Full stock that morning."""
    run(
        engine,
        "INSERT INTO producto_stock_diario (fecha, item_id, stock_full) VALUES (:f, :i, :s)",
        f=fecha,
        i=item_id,
        s=stock_full,
    )


def pasos(engine: Engine, item_id: int) -> list:
    return rows(
        engine,
        "SELECT tipo, fecha, cantidad, stock_antes, costo_neto_neto_usd, promedio_usd FROM costo_si_pasos "
        "WHERE item_id = :i ORDER BY orden",
        i=item_id,
    )


def encolados(engine: Engine) -> list:
    return rows(engine, "SELECT item_id, desde FROM costo_si_dirty ORDER BY item_id")
