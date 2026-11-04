"""RMA search by ML sale whose ERP order was archived after its invoice (follow-up of the 2026-11-04 report).

Captured in production for the reported pack (read-only, owner's OK): the ERP order left `tb_sale_order_header`
and survives only in `tb_sale_order_header_history` (status "Ok Para Emisión"), and its invoice exists. The ML
header fallback found the sale first, with `soh_id` 0, so the history (which knows the real order) was never
read: the case got the bare ML detail instead of the invoice and the ERP customer. Ids and buyer data are replaced.
"""

# ruff: noqa: F811 -- the imported fixtures are re-named by the tests that use them
from __future__ import annotations

from datetime import datetime

import pytest

from app.models.commercial_transaction import CommercialTransaction
from app.models.item_transaction import ItemTransaction
from app.models.sale_order_header_history import SaleOrderHeaderHistory
from app.models.sale_order_status import SaleOrderStatus
from app.models.tb_customer import TBCustomer
from app.models.tb_item import TBItem
from tests.integration.test_traza_ml_sin_pedido_erp_postgres import (  # noqa: F401 -- fixtures
    COMP_ID,
    ORDER_ID,
    PACK_ID,
    _traza,
    db,
    venta_sin_pedido_erp,
)

pytestmark = pytest.mark.postgres

SOH_ID = 31000  # the archived ERP order of the sale (`venta_sin_pedido_erp`'s history row)
CUST_ID = 7001


@pytest.fixture()
def pedido_archivado_facturado(db, venta_sin_pedido_erp):
    db.query(SaleOrderHeaderHistory).filter(SaleOrderHeaderHistory.soh_id == SOH_ID).update({"cust_id": CUST_ID})
    db.add_all(
        [
            SaleOrderStatus(ssos_id=50, ssos_name="Ok Para Emisión"),
            TBCustomer(
                comp_id=COMP_ID,
                cust_id=CUST_ID,
                cust_name="Cliente ERP De Prueba",
                cust_taxnumber="30000000001",
                cust_cellphone="1100000000",
            ),
            CommercialTransaction(
                comp_id=COMP_ID,
                ct_transaction=70010,
                ct_soh_id=SOH_ID,
                ct_soh_bra_id=45,
                ct_kindOf="A",
                ct_pointOfSale=4,
                ct_docNumber="00000002",
                ct_date=datetime(2026, 10, 28),
            ),
            ItemTransaction(comp_id=COMP_ID, it_transaction=80010, ct_transaction=70010, item_id=501),
        ]
    )
    db.flush()


@pytest.mark.parametrize("ml_id", [PACK_ID, ORDER_ID])
def test_an_archived_erp_order_is_resolved_from_its_history(db, pedido_archivado_facturado, ml_id):
    traza = _traza(db, ml_id)

    [pedido] = traza.pedidos
    assert (pedido.soh_id, pedido.cust_id, pedido.ml_id) == (SOH_ID, CUST_ID, ORDER_ID)
    assert (pedido.cliente, pedido.cliente_dni, pedido.cliente_telefono) == (
        "Cliente ERP De Prueba",
        "30000000001",
        "1100000000",
    )
    assert pedido.estado == "Ok Para Emisión"
    assert pedido.shipping_id == 40000000001


def test_an_archived_erp_order_lists_its_invoice_items(db, pedido_archivado_facturado):
    traza = _traza(db, PACK_ID)

    assert [(s.articulo.item_id, [m.nro_documento for m in s.movimientos]) for s in traza.seriales] == [
        (501, ["A 4-00000002"])
    ]


def test_an_archived_order_without_erp_customer_keeps_the_ml_buyer(db, venta_sin_pedido_erp):
    """The history row has no ERP customer (as captured): the buyer data of the ML header stays."""
    traza = _traza(db, PACK_ID)

    [pedido] = traza.pedidos
    assert pedido.soh_id == SOH_ID
    assert (pedido.cliente, pedido.cliente_dni) == ("Comprador De Prueba", "20000000001")


def test_an_invoice_of_another_branch_with_the_same_order_number_is_not_listed(db, pedido_archivado_facturado):
    """As captured: the order number of the sale (branch 45) also appears on a 2025 invoice of branch 1."""
    db.add_all(
        [
            TBItem(comp_id=COMP_ID, item_id=999, item_code="7790000000999", item_desc="Producto de otra sucursal"),
            CommercialTransaction(
                comp_id=COMP_ID,
                ct_transaction=70011,
                ct_soh_id=SOH_ID,
                ct_soh_bra_id=1,
                ct_kindOf="B",
                ct_pointOfSale=1,
                ct_docNumber="00000003",
                ct_date=datetime(2025, 1, 17),
            ),
            ItemTransaction(comp_id=COMP_ID, it_transaction=80011, ct_transaction=70011, item_id=999),
        ]
    )
    db.flush()

    traza = _traza(db, PACK_ID)

    assert [s.articulo.item_id for s in traza.seriales] == [501]
