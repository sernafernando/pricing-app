"""SQLite side of the invoiced-units rounding rule.

The PostgreSQL tests in `test_lineas_facturadas_postgres.py` prove a fractional
net is floored there; these prove the same expression yields the same units on
the SQLite test engine (and that FLOOR exists in it), so both engines agree.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from sqlalchemy import text

from app.services.erp_matching_service import asignar_factura_erp
from tests.unit import test_erp_matching_service as base
from tests.unit.test_erp_matching_service import _crear_ct, _crear_pedido, _linea_erp, _unidades

# Reuse that module's SQLite fixtures (the view and the ERP catalog rows).
_crear_vista = base._crear_vista
empresa = base.empresa
proveedor = base.proveedor
sd_factura = base.sd_factura


def _factura_fraccionaria(db, proveedor, sd_factura) -> int:
    """Invoice 990101: item 501 x (1.5 + 1.2) = 2.7, item 502 x 4."""
    _crear_ct(
        db,
        ct_transaction=990101,
        comp_id=1,
        bra_id=1,
        supp_id=proveedor.supp_id,
        ct_docnumber="LIN-FR",
        sd_id=sd_factura.sd_id,
    )
    _linea_erp(db, it=101, ct=990101, item_id=501, qty="1.5")
    _linea_erp(db, it=102, ct=990101, item_id=501, qty="1.2")
    _linea_erp(db, it=103, ct=990101, item_id=502, qty="4")
    return 990101


def _pedido(db, empresa, proveedor, active_user):
    return _crear_pedido(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        numero="P-LIN-FR",
        numero_factura="LIN-FR",
        creado_por_id=active_user.id,
    )


def test_fractional_net_is_floored(db, empresa, proveedor, sd_factura, active_user):
    factura = _factura_fraccionaria(db, proveedor, sd_factura)
    pedido = _pedido(db, empresa, proveedor, active_user)

    asignar_factura_erp(db, pedido, factura)

    assert _unidades(db, pedido.id) == {501: 2, 502: 4}


def test_migration_backfill_floors_a_fractional_net(db, empresa, proveedor, sd_factura, active_user):
    migration = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "20261104_pedido_lineas_facturadas.py"
    spec = importlib.util.spec_from_file_location("pedido_lineas_facturadas_sqlite", migration)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    factura = _factura_fraccionaria(db, proveedor, sd_factura)
    pedido = _pedido(db, empresa, proveedor, active_user)
    pedido.ct_transaction_id = factura
    db.flush()

    db.execute(text(module.BACKFILL))

    assert _unidades(db, pedido.id) == {501: 2, 502: 4}
