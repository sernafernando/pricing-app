"""RMA search by ML sale when the ERP has no sale order for it (reported to the owner, 2026-11-04):

> cuando cargo un caso que no tiene numero de serie y lo tengo que cargar por el numero de compra de ML, no me trae
> la info del producto o los datos del cliente.

`GET /seriales/traza/ml/{ml_id}` falls back to the ML order header when no ERP sale order (`tb_sale_order_header`)
links to the sale; that fallback has no `soh_id` (0), so neither serials nor invoice items were found and the RMA
modal had no article to add. The sale's products now come from the ML order detail, whether the user types the pack
id or the order id. The rows follow the model columns (anonymized: no real buyer data, the repository is public).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.commercial_transaction import CommercialTransaction
from app.models.item_transaction import ItemTransaction
from app.models.mercadolibre_order_detail import MercadoLibreOrderDetail
from app.models.mercadolibre_order_header import MercadoLibreOrderHeader
from app.models.sale_order_header import SaleOrderHeader
from app.models.tb_item import TBItem
from app.routers import seriales_traza_ml
from tests.conftest import POSTGRES_TEST_URL, _postgres_reachable

pytestmark = pytest.mark.postgres

_TABLES = (
    "productos_erp",
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

PACK_ID = "2000000000000001"
ORDER_ID = "2000000000000002"
COMP_ID = 1
MLO_ID = 900001


@pytest.fixture()
def db():
    if not _postgres_reachable():
        pytest.skip(f"PostgreSQL not reachable at {POSTGRES_TEST_URL}")
    engine = create_engine(POSTGRES_TEST_URL)
    connection = engine.connect()
    transaction = connection.begin()
    # The DDL runs inside the transaction, so the rollback drops the tables it created.
    tables = [Base.metadata.tables[name] for name in _TABLES]
    Base.metadata.create_all(bind=connection, tables=tables, checkfirst=True)
    session = sessionmaker(bind=connection, autoflush=False)()
    yield session
    session.close()
    transaction.rollback()
    connection.close()
    engine.dispose()


@pytest.fixture()
def venta_sin_pedido_erp(db):
    """One ML sale of two products, known only to the ML order tables (no ERP sale order, no ERP customer)."""
    db.add(
        MercadoLibreOrderHeader(
            comp_id=COMP_ID,
            mlo_id=MLO_ID,
            cust_id=0,
            mlorder_id=ORDER_ID,
            ml_pack_id=PACK_ID,
            mlshippingid="40000000001",
            mlo_cd=datetime(2026, 10, 25, 10, 0),
            mlo_status="paid",
            mlbra_id=45,
            mluser_first_name="Comprador",
            mluser_last_name="De Prueba",
            identificationnumber=20000000001,
            mluser_phone="XXXXXXX",
        )
    )
    db.add_all(
        [
            TBItem(comp_id=COMP_ID, item_id=501, item_code="7790000000011", item_desc="Router de prueba"),
            TBItem(comp_id=COMP_ID, item_id=502, item_code="7790000000028", item_desc="Switch de prueba"),
            MercadoLibreOrderDetail(
                comp_id=COMP_ID,
                mlo_id=MLO_ID,
                mlod_id=1,
                item_id=501,
                mlo_quantity=Decimal("1"),
                mlo_title="Router ML",
            ),
            MercadoLibreOrderDetail(
                comp_id=COMP_ID,
                mlo_id=MLO_ID,
                mlod_id=2,
                item_id=502,
                mlo_quantity=Decimal("2"),
                mlo_title="Switch ML",
            ),
        ]
    )
    db.flush()


def _traza(db, ml_id: str):
    with (
        patch.object(seriales_traza_ml, "_fetch_claims_by_order_ids", return_value=[]),
        patch.object(seriales_traza_ml, "_fetch_webhook_previews", return_value=[]),
    ):
        return seriales_traza_ml.traza_ml(ml_id, db=db, current_user=None)


@pytest.mark.parametrize("ml_id", [PACK_ID, ORDER_ID])
def test_a_sale_without_erp_order_lists_its_products(db, venta_sin_pedido_erp, ml_id):
    traza = _traza(db, ml_id)

    assert [p.ml_id for p in traza.pedidos] == [ORDER_ID]
    articulos = sorted(
        (s.serial, s.articulo.item_id, s.articulo.codigo, s.articulo.descripcion) for s in traza.seriales
    )
    assert articulos == [
        ("", 501, "7790000000011", "Router de prueba"),
        ("", 502, "7790000000028", "Switch de prueba"),
    ]


def test_a_detail_item_missing_from_the_catalog_keeps_its_ml_title(db, venta_sin_pedido_erp):
    db.query(TBItem).filter(TBItem.item_id == 502).delete()
    db.flush()

    traza = _traza(db, PACK_ID)

    by_item = {s.articulo.item_id: s.articulo for s in traza.seriales}
    assert (by_item[502].codigo, by_item[502].descripcion) == ("502", "Switch ML")


def test_an_unrelated_invoice_without_sale_order_is_not_taken_as_this_sale(db, venta_sin_pedido_erp):
    """The header-only sale has no ERP order (soh_id 0): it must not match invoices whose order id is 0 too."""
    db.add_all(
        [
            TBItem(comp_id=COMP_ID, item_id=999, item_code="7790000000999", item_desc="Producto ajeno"),
            CommercialTransaction(comp_id=COMP_ID, ct_transaction=70001, ct_soh_id=0, ct_kindOf="FC"),
            ItemTransaction(comp_id=COMP_ID, it_transaction=80001, ct_transaction=70001, item_id=999),
        ]
    )
    db.flush()

    traza = _traza(db, PACK_ID)

    assert sorted(s.articulo.item_id for s in traza.seriales) == [501, 502]


def test_a_sale_with_erp_order_still_lists_its_invoice_items_only(db, venta_sin_pedido_erp):
    """Previous behavior: with an ERP sale order the products come from its invoice, never from the ML detail."""
    db.add_all(
        [
            SaleOrderHeader(comp_id=COMP_ID, bra_id=45, soh_id=31001, soh_mlid=ORDER_ID, mlo_id=MLO_ID, cust_id=0),
            CommercialTransaction(
                comp_id=COMP_ID,
                ct_transaction=70002,
                ct_soh_id=31001,
                ct_kindOf="FC",
                ct_pointOfSale=4,
                ct_docNumber="00000001",
            ),
            ItemTransaction(comp_id=COMP_ID, it_transaction=80002, ct_transaction=70002, item_id=501),
        ]
    )
    db.flush()

    traza = _traza(db, ORDER_ID)

    assert [p.soh_id for p in traza.pedidos] == [31001]
    assert [(s.articulo.item_id, [m.nro_documento for m in s.movimientos]) for s in traza.seriales] == [
        (501, ["FC 4-00000001"])
    ]
