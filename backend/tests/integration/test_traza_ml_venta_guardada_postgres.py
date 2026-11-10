"""RMA search by ML sale falls back to the ML sales we already store (reported to the owner, 2026-11-10):

> buen dia Fer, te comparto un caso que no me trae los datos en el pricing, numero de ML 2000015661644825, son unos
> cartuchos sin serie

Owner: "si tenemos vinculadas las operaciones a productos, usemos el mismo vinculo, si ya guardamos las ventas..."

Owner (L2): "pero en ventas ml tenemos los datos y no necesitamos al ERP para matchearlos."
Owner (L3): the ERP stays, the RMA processes run there; only the sale and product data stop depending on it.

`GET /seriales/traza/ml/{ml_id}` only read the GBP mirror (`tb_mercadolibre_orders_header/detail`, ERP orders,
invoices): a sale missing there answered 404, or no products. The trace now takes the sale and its products from our
own stored ML sale (`ml_orders_ops` by order, pack or shipment id, its `ml_order_items_ops` lines), each line linked
to its product exactly like the costing does (`ml_order_item_costos.producto_item_id`, else
`costeo_service._productos_por_item`). The ERP side (order, invoice, serials, RMAs) still enriches it as before. Ids, names and codes are placeholders (the repository is public); the column
shapes follow the ML ingestion (`ml_orders_ops` keyed by the ML order id, MLA strings as item ids).
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.commercial_transaction import CommercialTransaction
from app.models.item_transaction import ItemTransaction
from app.models.mercadolibre_order_detail import MercadoLibreOrderDetail
from app.models.mercadolibre_order_header import MercadoLibreOrderHeader
from app.models.ml_order_item_costo import MlOrderItemCosto
from app.models.ml_orders_ops import MlOrderItemOps, MlOrdersOps
from app.models.producto import ProductoERP
from app.models.publicacion_ml import PublicacionML
from app.models.sale_order_header import SaleOrderHeader
from app.models.tb_item import TBItem
from app.routers import seriales_traza_ml
from app.models.tb_item_serials import TbItemSerial
from app.models.tb_sale_order_serial import TbSaleOrderSerial
from app.routers.seriales_shared import ArticuloInfo, MovimientoSerial, TrazaMLSerialItem
from tests.conftest import (
    POSTGRES_TEST_URL,
    _patch_pg_types_for_sqlite,
    _postgres_reachable,
    _restore_pristine_pg_types,
)

pytestmark = pytest.mark.postgres

_TABLES = (
    "productos_erp",
    "publicaciones_ml",
    "ml_orders_ops",
    "ml_order_items_ops",
    "ml_order_item_costos",
    "tb_category",
    "tb_commercial_transactions",
    "tb_customer",
    "tb_document_file",
    "tb_item",
    "tb_item_serials",
    "tb_item_transactions",
    "tb_item_transaction_serials",
    "tb_mercadolibre_orders_header",
    "tb_mercadolibre_orders_detail",
    "tb_mercadolibre_orders_shipping",
    "tb_rma_detail",
    "tb_rma_detail_attrib_history",
    "tb_rma_header",
    "tb_sale_order_header",
    "tb_sale_order_header_history",
    "tb_sale_order_serials",
    "tb_sale_order_status",
    "tb_storage",
    "tb_supplier",
)

PACK_ID = 2000000000000101
ORDER_A = 2000000000000102  # black cartridge, cost frozen
ORDER_B = 2000000000000103  # color cartridge, not frozen yet: linked through its MLA
SHIPPING_ID = 40000000101
COMP_ID = 1
MLO_ID = 900101
FECHA = datetime(2026, 11, 7, 14, 30, tzinfo=timezone.utc)


@pytest.fixture()
def db():
    if not _postgres_reachable():
        pytest.skip(f"PostgreSQL not reachable at {POSTGRES_TEST_URL}")
    engine = create_engine(POSTGRES_TEST_URL)
    connection = engine.connect()
    transaction = connection.begin()
    # The DDL runs inside the transaction, so the rollback drops the tables it created.
    tables = [Base.metadata.tables[name] for name in _TABLES]
    # Real BIGINT ML order ids: undo the SQLite downgrade of BigInteger primary keys other fixtures leave behind.
    _restore_pristine_pg_types(tables)
    Base.metadata.create_all(bind=connection, tables=tables, checkfirst=True)
    _patch_pg_types_for_sqlite()
    session = sessionmaker(bind=connection, autoflush=False)()
    yield session
    session.close()
    transaction.rollback()
    connection.close()
    engine.dispose()


def _orden(order_id: int, pack_id: int | None = PACK_ID) -> MlOrdersOps:
    return MlOrdersOps(
        order_id=order_id,
        pack_id=pack_id,
        status="paid",
        date_created=FECHA,
        ml_last_updated=FECHA,
        buyer_id=111,
        buyer_nickname="COMPRADORPRUEBA",
        seller_id=999,
        total_amount=Decimal("30000"),
        currency_id="ARS",
        shipping_id=SHIPPING_ID,
    )


@pytest.fixture()
def venta_guardada(db):
    """A pack of two ML orders (one cartridge each, no serials), stored by our ML ingestion only."""
    db.add_all(
        [
            ProductoERP(item_id=601, codigo="CART-NEGRO", descripcion="Cartucho negro de prueba"),
            ProductoERP(item_id=602, codigo="CART-COLOR", descripcion="Cartucho color de prueba"),
        ]
    )
    db.flush()
    db.add_all(
        [
            PublicacionML(mla="MLA100000002", item_id=602, codigo="CART-COLOR"),
            _orden(ORDER_A),
            _orden(ORDER_B),
            MlOrderItemOps(
                order_id=ORDER_A, item_id="MLA100000001", seller_sku="SKU-VIEJO", title="Cartucho N ML", quantity=2
            ),
            MlOrderItemOps(order_id=ORDER_B, item_id="MLA100000002", title="Cartucho C ML", quantity=1),
            # The costing froze ORDER_A's line to product 601 (its SKU since changed and matches nothing).
            MlOrderItemCosto(
                order_id=ORDER_A,
                item_id="MLA100000001",
                costo_origen=Decimal("10"),
                moneda="USD",
                costo_unitario_ars=Decimal("10000"),
                iva_pct=Decimal("21"),
                precio_unitario=Decimal("15000"),
                fuente="publicacion",
                producto_item_id=601,
            ),
        ]
    )
    db.flush()


def _traza(db, ml_id: str):
    with (
        patch.object(seriales_traza_ml, "_fetch_claims_by_order_ids", return_value=[]),
        patch.object(seriales_traza_ml, "_fetch_webhook_previews", return_value=[]),
        patch.object(seriales_traza_ml, "_fetch_pedidos_rows_from_gbp_fallback", return_value=[]),
    ):
        return seriales_traza_ml.traza_ml(ml_id, db=db, current_user=None)


def _productos(traza) -> list[tuple]:
    return sorted(
        (s.serial, s.articulo.item_id, s.articulo.codigo, s.articulo.descripcion, s.cantidad) for s in traza.seriales
    )


PACK_PRODUCTOS = [
    ("", 601, "CART-NEGRO", "Cartucho negro de prueba", 2),
    ("", 602, "CART-COLOR", "Cartucho color de prueba", 1),
]


# --- S1/S2: no GBP sale at all (the trace answered 404) ---------------------------------------------------------


@pytest.mark.parametrize("ml_id", [str(PACK_ID), str(SHIPPING_ID)])
def test_a_pack_or_shipment_known_only_to_our_stored_sales_lists_every_product(db, venta_guardada, ml_id):
    traza = _traza(db, ml_id)

    assert _productos(traza) == PACK_PRODUCTOS
    assert sorted(p.ml_id for p in traza.pedidos) == [str(ORDER_A), str(ORDER_B)]
    pedido = traza.pedidos[0]
    assert (pedido.soh_id, pedido.cliente, pedido.shipping_id, pedido.estado) == (
        0,
        "COMPRADORPRUEBA",
        SHIPPING_ID,
        "paid",
    )
    assert pedido.fecha.startswith("2026-11-07")
    assert traza.busqueda_por == "ventas_ml"


def test_an_order_id_known_only_to_our_stored_sales_lists_its_own_product(db, venta_guardada):
    traza = _traza(db, str(ORDER_B))

    assert _productos(traza) == [("", 602, "CART-COLOR", "Cartucho color de prueba", 1)]
    assert [p.ml_id for p in traza.pedidos] == [str(ORDER_B)]


def test_a_line_linked_through_its_seller_sku_uses_that_product(db, venta_guardada):
    db.add(ProductoERP(item_id=603, codigo="CART-XL", descripcion="Cartucho XL de prueba"))
    db.add(_orden(ORDER_A + 10, pack_id=None))
    db.add(MlOrderItemOps(order_id=ORDER_A + 10, item_id="MLA100000009", seller_sku="CART-XL", quantity=3))
    db.flush()

    traza = _traza(db, str(ORDER_A + 10))

    assert _productos(traza) == [("", 603, "CART-XL", "Cartucho XL de prueba", 3)]


def test_a_line_with_no_product_link_keeps_its_ml_code_and_title(db, venta_guardada):
    """Assumption: an unlinked line still appears (item id 0) so a case can be opened for it."""
    db.add(_orden(ORDER_A + 20, pack_id=None))
    db.add(MlOrderItemOps(order_id=ORDER_A + 20, item_id="MLA100000077", title="Cartucho sin vincular", quantity=1))
    db.flush()

    traza = _traza(db, str(ORDER_A + 20))

    assert _productos(traza) == [("", 0, "MLA100000077", "Cartucho sin vincular", 1)]


def test_an_id_no_side_knows_is_still_not_found(db, venta_guardada):
    with pytest.raises(HTTPException) as error:
        _traza(db, "2000000000009999")
    assert error.value.status_code == 404


# --- S1/S2: the GBP side has the sale but yields no products -----------------------------------------------------


def _gbp_header(**kwargs) -> MercadoLibreOrderHeader:
    return MercadoLibreOrderHeader(
        comp_id=COMP_ID,
        mlo_id=MLO_ID,
        mlorder_id=str(ORDER_A),
        ml_pack_id=str(PACK_ID),
        mlshippingid=str(SHIPPING_ID),
        mlo_cd=datetime(2026, 11, 7, 11, 0),
        mlo_status="paid",
        mluser_first_name="Comprador",
        mluser_last_name="GBP",
        **kwargs,
    )


def test_a_gbp_header_without_detail_rows_takes_the_products_of_our_stored_sale(db, venta_guardada):
    db.add(_gbp_header())
    db.flush()

    traza = _traza(db, str(PACK_ID))

    assert _productos(traza) == PACK_PRODUCTOS
    # The GBP order keeps its buyer; the pack's other order comes from our stored sale.
    assert [(p.ml_id, p.cliente) for p in traza.pedidos] == [
        (str(ORDER_A), "Comprador GBP"),
        (str(ORDER_B), "COMPRADORPRUEBA"),
    ]


def test_a_gbp_detail_without_item_id_takes_the_products_of_our_stored_sale(db, venta_guardada):
    db.add(_gbp_header())
    db.add(MercadoLibreOrderDetail(comp_id=COMP_ID, mlo_id=MLO_ID, mlod_id=1, item_id=None, mlo_title="Cartucho"))
    db.flush()

    traza = _traza(db, str(PACK_ID))

    assert _productos(traza) == PACK_PRODUCTOS


def test_an_erp_order_not_invoiced_yet_takes_the_products_of_our_stored_sale(db, venta_guardada):
    """The ERP order exists (no serials, no invoice yet): its rows carry no mlo_id, so the GBP detail was never read."""
    db.add(_gbp_header())
    db.add(SaleOrderHeader(comp_id=COMP_ID, bra_id=45, soh_id=32001, soh_mlid=str(ORDER_A), mlo_id=MLO_ID, cust_id=0))
    db.flush()

    traza = _traza(db, str(ORDER_A))

    assert _productos(traza) == [("", 601, "CART-NEGRO", "Cartucho negro de prueba", 2)]
    assert [p.soh_id for p in traza.pedidos] == [32001]


def test_a_gbp_order_without_date_or_shipment_takes_them_from_our_stored_sale(db, venta_guardada):
    db.add(SaleOrderHeader(comp_id=COMP_ID, bra_id=45, soh_id=32002, soh_mlid=str(ORDER_B), cust_id=0))
    db.flush()

    traza = _traza(db, str(ORDER_B))

    pedido = traza.pedidos[0]
    assert (pedido.soh_id, pedido.shipping_id) == (32002, SHIPPING_ID)
    assert pedido.fecha.startswith("2026-11-07")


# --- S3: the ERP side enriches, never duplicates -------------------------------------------------------------------


def test_a_product_both_sides_have_is_listed_once_and_the_rest_come_from_our_stored_sale(db, venta_guardada):
    db.add(_gbp_header())
    db.add(TBItem(comp_id=COMP_ID, item_id=601, item_code="7790000000601", item_desc="Cartucho negro ERP"))
    db.add(MercadoLibreOrderDetail(comp_id=COMP_ID, mlo_id=MLO_ID, mlod_id=1, item_id=601, mlo_title="Cartucho"))
    db.flush()

    traza = _traza(db, str(PACK_ID))

    assert sorted((s.articulo.item_id, s.articulo.codigo, s.cantidad) for s in traza.seriales) == [
        (601, "7790000000601", 2),
        (602, "CART-COLOR", 1),
    ]
    assert traza.busqueda_por != "ventas_ml"


def test_an_invoiced_product_keeps_its_invoice_and_is_not_duplicated(db, venta_guardada):
    db.add_all(
        [
            SaleOrderHeader(comp_id=COMP_ID, bra_id=45, soh_id=32003, soh_mlid=str(ORDER_A), cust_id=0),
            TBItem(comp_id=COMP_ID, item_id=601, item_code="7790000000601", item_desc="Cartucho negro ERP"),
            CommercialTransaction(
                comp_id=COMP_ID,
                ct_transaction=71001,
                ct_soh_id=32003,
                ct_soh_bra_id=45,
                ct_kindOf="FC",
                ct_pointOfSale=4,
                ct_docNumber="00000009",
            ),
            ItemTransaction(comp_id=COMP_ID, it_transaction=81001, ct_transaction=71001, item_id=601),
        ]
    )
    db.flush()

    traza = _traza(db, str(ORDER_A))

    assert [p.soh_id for p in traza.pedidos] == [32003]
    assert [(s.articulo.item_id, [m.nro_documento for m in s.movimientos]) for s in traza.seriales] == [
        (601, ["FC 4-00000009"])
    ]


def test_an_erp_order_found_only_through_our_stored_order_id_still_enriches_the_sale(db, venta_guardada):
    """Typed the pack id, the GBP header is missing: the ERP order is reached through the stored order ids."""
    db.add(SaleOrderHeader(comp_id=COMP_ID, bra_id=45, soh_id=32004, soh_mlid=str(ORDER_B), cust_id=0))
    db.flush()

    traza = _traza(db, str(PACK_ID))

    assert sorted((p.soh_id, p.ml_id) for p in traza.pedidos) == [(0, str(ORDER_A)), (32004, str(ORDER_B))]
    assert _productos(traza) == PACK_PRODUCTOS


def _serial_erp(db) -> None:
    db.add_all(
        [
            SaleOrderHeader(
                comp_id=COMP_ID,
                bra_id=45,
                soh_id=32005,
                soh_mlid=str(ORDER_A),
                cust_id=0,
                soh_cd=datetime(2026, 11, 7, 12, 0),
                mlshippingid=SHIPPING_ID,
            ),
            TbItemSerial(comp_id=COMP_ID, is_id=91001, bra_id=45, item_id=601, is_serial="SN-PRUEBA-1"),
            TbSaleOrderSerial(comp_id=COMP_ID, bra_id=45, sose_id=1, is_id=91001, soh_id=32005),
        ]
    )
    db.flush()


def _traza_con_serial(db, ml_id: str):
    with (
        patch.object(seriales_traza_ml, "_build_movimientos", return_value=([_MOVIMIENTO_ERP], _ARTICULO_ERP)),
        patch.object(seriales_traza_ml, "_build_rma", return_value=([], _ARTICULO_ERP)),
    ):
        return _traza(db, ml_id)


_ARTICULO_ERP = ArticuloInfo(item_id=601, codigo="7790000000601", descripcion="Cartucho negro ERP")
_MOVIMIENTO_ERP = MovimientoSerial(is_id=91001, tipo="CLIENTE", nro_documento="FC 4-00000010")
# What the trace answers today for a sale with one serial in the ERP.
SERIAL_HOY = [
    TrazaMLSerialItem(serial="SN-PRUEBA-1", articulo=_ARTICULO_ERP, movimientos=[_MOVIMIENTO_ERP]).model_dump()
]


def test_without_a_stored_sale_a_serial_sale_reads_as_today(db):
    _serial_erp(db)

    traza = _traza_con_serial(db, str(ORDER_A))

    assert [s.model_dump() for s in traza.seriales] == SERIAL_HOY


def test_a_serial_sale_keeps_its_serial_exactly_as_today_when_we_also_store_it(db, venta_guardada):
    _serial_erp(db)

    traza = _traza_con_serial(db, str(ORDER_A))

    assert [s.model_dump() for s in traza.seriales] == SERIAL_HOY
    assert [(p.soh_id, p.fecha, p.shipping_id) for p in traza.pedidos] == [(32005, "2026-11-07 12:00:00", SHIPPING_ID)]
