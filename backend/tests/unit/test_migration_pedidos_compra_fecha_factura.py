"""Backfill of `pedidos_compra.fecha_factura` (20261103_pedidos_fecha_factura).

Runs the migration's UPDATE against the SQLite test schema with a hand-made
`v_facturas_compra_vigentes` (migrations do not run in tests): linked rows get
the invoice date part, unlinked rows and links missing from the view stay NULL.
"""

from __future__ import annotations

import importlib.util
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import text

from app.models.commercial_transaction import CommercialTransaction
from app.models.empresa import Empresa
from app.models.pedido_compra import PedidoCompra
from app.models.proveedor import OrigenProveedor, Proveedor
from app.models.tb_sale_document import SaleDocument

_MIGRATION = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "20261103_pedidos_compra_fecha_factura.py"

_VIEW_SQL = """
CREATE VIEW v_facturas_compra_vigentes AS
SELECT ct.ct_transaction, ct.supp_id, ct.ct_date
FROM tb_commercial_transactions ct
JOIN tb_sale_document sd ON sd.sd_id = ct.sd_id
WHERE sd.sd_ispurchase = 1
"""


def _load_migration():
    spec = importlib.util.spec_from_file_location("pedidos_compra_fecha_factura", _MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def seed(db, active_user):
    db.execute(text("DROP VIEW IF EXISTS v_facturas_compra_vigentes"))
    db.execute(text(_VIEW_SQL))
    db.add(Empresa(id=1, nombre="EmpresaFecha", activo=True, orden=0))
    db.add(Proveedor(id=77, nombre="PROV_FECHA", supp_id=77, activo=True, origen=OrigenProveedor.ERP.value))
    db.add(SaleDocument(sd_id=101, sd_desc="Factura compra", sd_ispurchase=True, sd_plusorminus=1))
    db.flush()
    db.add(
        CommercialTransaction(
            ct_transaction=880001,
            comp_id=1,
            bra_id=1,
            supp_id=77,
            ct_docNumber="0001",
            sd_id=101,
            ct_total=Decimal("10"),
            ct_date=datetime(2026, 5, 20, 1, 30, 0),
            ct_isCancelled=False,
        )
    )

    def pedido(numero: str, ct_id: int | None) -> PedidoCompra:
        p = PedidoCompra(
            numero=numero,
            empresa_id=1,
            proveedor_id=77,
            moneda="ARS",
            monto=Decimal("10"),
            estado="aprobado",
            ct_transaction_id=ct_id,
            creado_por_id=active_user.id,
        )
        db.add(p)
        return p

    pedidos = {
        "vinculado": pedido("P-FF-1", 880001),
        "sin_fila_en_vista": pedido("P-FF-2", 880999),
        "sin_vincular": pedido("P-FF-3", None),
    }
    db.flush()
    return pedidos


def test_backfill_copia_la_fecha_solo_de_pedidos_vinculados(db, seed) -> None:
    db.execute(text(_load_migration().BACKFILL))
    db.expire_all()

    assert seed["vinculado"].fecha_factura == date(2026, 5, 20)
    assert seed["sin_fila_en_vista"].fecha_factura is None
    assert seed["sin_vincular"].fecha_factura is None
