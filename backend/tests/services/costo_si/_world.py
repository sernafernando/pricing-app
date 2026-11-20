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
    CostoSiNcSinAsignar,
    CostoSiFullCobertura,
    CostoSiFullOperacion,
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
    # Compras' money links (only the columns the costo SI link reads) and local NCs matched to their ERP document.
    "CREATE TABLE imputaciones (id BIGSERIAL PRIMARY KEY, origen_tipo VARCHAR(64) NOT NULL, origen_id BIGINT NOT NULL,"
    " destino_tipo VARCHAR(32) NOT NULL, destino_id BIGINT, es_reversal BOOLEAN NOT NULL DEFAULT false,"
    " reimputada_desde_id BIGINT)",
    "CREATE TABLE notas_credito_local (id BIGSERIAL PRIMARY KEY, ct_transaction_id BIGINT)",
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
    CostoSiFullOperacion.__table__,
    CostoSiFullCobertura.__table__,
    CostoSiFacturaTc.__table__,
    CostoSiNcSinAsignar.__table__,
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
            "tb_item",
            "costo_si_pasos",
            "costo_si_backups",
            "costo_si_stock_diario",
            "costo_si_full_operaciones",
            "costo_si_full_cobertura",
            "costo_si_factura_tc",
            "costo_si_nc_sin_asignar",
            "imputaciones",
            "notas_credito_local",
            "productos_erp",
        ):
            conn.execute(text(f"DELETE FROM {table}"))
        conn.execute(text("DELETE FROM combo_componentes WHERE combo_item_id <> 999999001"))
        conn.execute(text("DELETE FROM costo_si_dirty"))  # last: the deletes above queue products


def run(engine: Engine, sql: str, **params) -> None:
    with engine.begin() as conn:
        conn.execute(text(sql), params)


def returning(engine: Engine, sql: str, **params):
    """A write whose RETURNING value is wanted, committed."""
    with engine.begin() as conn:
        return conn.execute(text(sql), params).scalar()


def rows(engine: Engine, sql: str, **params) -> list:
    with engine.connect() as conn:
        return [tuple(r) for r in conn.execute(text(sql), params)]


def producto(engine: Engine, item_id: int, marca: str = MARCA, categoria: str = "CAMARAS", cat_id: int = 3) -> None:
    run(
        engine,
        "INSERT INTO productos_erp (item_id, codigo, descripcion, marca, categoria) VALUES (:i, :c, 'Producto', :m, :cat)",
        i=item_id,
        c=f"C{item_id}",
        m=marca,
        cat=categoria,
    )
    run(
        engine,
        "INSERT INTO tb_item (comp_id, item_id, item_code, cat_id) VALUES (1, :i, :c, :cat)",
        i=item_id,
        c=f"C{item_id}",
        cat=cat_id,
    )


def costo_lista(engine: Engine, item_id: int, cuando: datetime, precio: str) -> None:
    run(
        engine,
        "INSERT INTO tb_item_cost_list_history (iclh_id, coslis_id, item_id, iclh_price, curr_id, iclh_cd) "
        "VALUES (:id, 1, :i, :p, 2, :cd)",
        id=next(_ids),
        i=item_id,
        p=Decimal(precio),
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


def bono_marca(engine: Engine, porcentaje: str, desde: date, hasta: date, marca: str = MARCA) -> int:
    """A brand bonus of the sale-cost kind by %, like the loyalty (S6)."""
    with engine.begin() as conn:
        return conn.execute(
            text(
                "INSERT INTO sell_in_bonos_marca (alcance, marca, tipo, porcentaje, moneda, fecha_desde, fecha_hasta, "
                "base, usuario_id) VALUES ('marca', :m, 'porcentaje', :p, 'ARS', :d, :h, 'costo_venta', 7) RETURNING id"
            ),
            {"m": marca, "p": Decimal(porcentaje), "d": desde, "h": hasta},
        ).scalar()


def tipo_cambio(engine: Engine, fecha: date, venta: float) -> None:
    run(engine, "INSERT INTO tipo_cambio (fecha, moneda, compra, venta) VALUES (:f, 'USD', :v, :v)", f=fecha, v=venta)


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


def operacion_full(engine: Engine, inventory_id: str, cuando: datetime, tipo: str, delta: int, disponible: int) -> None:
    run(
        engine,
        "INSERT INTO costo_si_full_operaciones (operation_id, inventory_id, date_created, tipo, delta, disponible) "
        "VALUES (:id, :inv, :c, :t, :d, :r)",
        id=next(_ids),
        inv=inventory_id,
        c=cuando,
        t=tipo,
        d=delta,
        r=disponible,
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


def nc(engine: Engine, item_id: int, fecha: date, qty: int, precio: str, curr_id: int = 2, supp_id: int = 14) -> int:
    """A supplier credit note dated `fecha` with a line for the product (`it_qty` positive, as GBP stores it; it moves
    no depot-1 stock)."""
    ct = next(_ids)
    run(
        engine,
        "INSERT INTO tb_commercial_transactions (ct_transaction, bra_id, sd_id, ct_date, supp_id) "
        "VALUES (:ct, 1, 103, :d, :s)",
        ct=ct,
        d=datetime.combine(fecha, datetime.min.time()),
        s=supp_id,
    )
    run(engine, "INSERT INTO v_facturas_compra_vigentes VALUES (:ct, 'NC', :n)", ct=ct, n=f"0001-NC{ct}")
    run(
        engine,
        "INSERT INTO tb_item_transactions (it_transaction, ct_transaction, bra_id, item_id, it_qty, it_price, curr_id,"
        " stor_id, it_cd) VALUES (:it, :ct, 1, :i, :q, :p, :c, 19, :cd)",
        it=next(_ids),
        ct=ct,
        i=item_id,
        q=qty,
        p=Decimal(precio),
        c=curr_id,
        cd=datetime.combine(fecha, datetime.min.time()),
    )
    return ct


def imputar(engine: Engine, nc_ct: int, destino_tipo: str, destino_id: Optional[int], local: bool = False) -> int:
    """Imputes an ERP NC (or a local NC matched to it, `local`) to an invoice, a Compras operation or the balance."""
    origen_tipo, origen_id = "nota_credito_erp", nc_ct
    if local:
        origen_tipo = "nota_credito_local"
        origen_id = returning(
            engine, "INSERT INTO notas_credito_local (ct_transaction_id) VALUES (:c) RETURNING id", c=nc_ct
        )
    return returning(
        engine,
        "INSERT INTO imputaciones (origen_tipo, origen_id, destino_tipo, destino_id) VALUES (:ot, :oi, :dt, :di) "
        "RETURNING id",
        ot=origen_tipo,
        oi=origen_id,
        dt=destino_tipo,
        di=destino_id,
    )
