"""SQLite side of the invoiced-units rounding rule.

The PostgreSQL tests in `test_lineas_facturadas_postgres.py` prove a fractional
net is floored there; these prove the same expression yields the same units on
the SQLite test engine (and that FLOOR exists in it), so both engines agree.
"""

from __future__ import annotations

import importlib.util
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import text

from app.models.tb_sale_document import SaleDocument
from app.services import imputaciones_service, pedidos_service
from app.services.erp_matching_service import asignar_factura_erp, reconciliar_lineas_facturadas
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


# ──────────────────────────────────────────────────────────────────────────
# corregir_pedido: a credit note frozen on the corrected-from pedido
# ──────────────────────────────────────────────────────────────────────────
#
# A financial correction clones the pedido as `pendiente_aprobacion` with the
# original's lines (credit note already subtracted), while the credit note's
# imputación stays on the original until the clone is approved. Every later
# reconcile (the ERP sync refreshes all pedidos) must keep subtracting it.


@pytest.fixture
def sd_nc(db) -> SaleDocument:
    sd = SaleDocument(
        sd_id=203,
        sd_desc="Nota de crédito compra",
        sd_ispurchase=True,
        sd_iscreditnote=True,
        sd_plusorminus=-1,
        hacc_group=10001,
    )
    db.add(sd)
    db.flush()
    return sd


def _ct(db, proveedor, sd, *, ct: int, lineas: dict[int, str]) -> int:
    _crear_ct(
        db, ct_transaction=ct, comp_id=1, bra_id=1, supp_id=proveedor.supp_id, ct_docnumber=f"DOC-{ct}", sd_id=sd.sd_id
    )
    for n, (item_id, qty) in enumerate(lineas.items()):
        _linea_erp(db, it=ct * 10 + n, ct=ct, item_id=item_id, qty=qty)
    return ct


def _imputar_nc(db, proveedor, active_user, *, nc: int, pedido_id: int):
    return imputaciones_service.crear_imputacion(
        db,
        origen_tipo="nota_credito_erp",
        origen_id=nc,
        destino_tipo="pedido_compra",
        destino_id=pedido_id,
        monto_imputado=Decimal("10"),
        moneda_imputada="ARS",
        monto_origen=Decimal("10"),
        moneda_origen="ARS",
        proveedor_id=proveedor.id,
        creado_por_id=active_user.id,
    )


def _corregir_monto(db, pedido_id: int, monto: str, active_user):
    return pedidos_service.corregir_pedido(
        db,
        pedido_original_id=pedido_id,
        cambios={"monto": Decimal(monto)},
        motivo_correccion="cambio financiero",
        user_id=active_user.id,
    )


@pytest.fixture
def pedido_con_nc(db, empresa, proveedor, sd_factura, sd_nc, active_user):
    """Approved pedido linked to an invoice of 10 x item 501, with a credit note of 1 imputed: 9 units."""
    factura = _ct(db, proveedor, sd_factura, ct=990201, lineas={501: "10"})
    nc = _ct(db, proveedor, sd_nc, ct=990202, lineas={501: "1"})
    pedido = pedidos_service.crear_pedido(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto=Decimal("1000"),
        creado_por_id=active_user.id,
    )
    pedidos_service.transicionar(db, pedido_id=pedido.id, accion="enviar_aprobacion", user_id=active_user.id)
    pedidos_service.transicionar(db, pedido_id=pedido.id, accion="aprobar", user_id=active_user.id)
    asignar_factura_erp(db, pedido, factura)
    _imputar_nc(db, proveedor, active_user, nc=nc, pedido_id=pedido.id)
    assert _unidades(db, pedido.id) == {501: 9}
    return pedido


def test_pending_clone_keeps_subtracting_the_credit_note_frozen_on_the_original(db, pedido_con_nc, active_user):
    clon = _corregir_monto(db, pedido_con_nc.id, "1200", active_user)
    assert clon.estado == "pendiente_aprobacion"

    reconciliar_lineas_facturadas(db)  # the ERP sync refreshes every pedido

    assert _unidades(db, clon.id) == {501: 9}
    assert _unidades(db, pedido_con_nc.id) == {}  # the original stays unlinked, as before


def test_returned_clone_keeps_subtracting_the_credit_note_frozen_on_the_original(db, pedido_con_nc, active_user):
    # Rejected back to the buyer: the imputación is still frozen on the original.
    clon = _corregir_monto(db, pedido_con_nc.id, "1200", active_user)
    pedidos_service.transicionar(
        db, pedido_id=clon.id, accion="rechazar_devolver", user_id=active_user.id, motivo="revisar monto"
    )

    reconciliar_lineas_facturadas(db)

    assert _unidades(db, clon.id) == {501: 9}


def test_approved_clone_subtracts_the_transferred_credit_note_once(db, pedido_con_nc, active_user):
    clon = _corregir_monto(db, pedido_con_nc.id, "1200", active_user)
    pedidos_service.transicionar(db, pedido_id=clon.id, accion="aprobar", user_id=active_user.id)

    reconciliar_lineas_facturadas(db)

    assert _unidades(db, clon.id) == {501: 9}
    assert _unidades(db, pedido_con_nc.id) == {}


def test_two_hop_correction_chain_keeps_subtracting_the_credit_note(db, pedido_con_nc, active_user):
    segundo = _corregir_monto(db, pedido_con_nc.id, "1200", active_user)
    pedidos_service.transicionar(db, pedido_id=segundo.id, accion="aprobar", user_id=active_user.id)
    tercero = _corregir_monto(db, segundo.id, "1300", active_user)

    reconciliar_lineas_facturadas(db)

    assert _unidades(db, tercero.id) == {501: 9}


def test_credit_note_imputed_to_a_grandparent_counts_for_the_head_of_the_chain(
    db, pedido_con_nc, proveedor, sd_nc, active_user
):
    # crear_imputacion has no guard on the destination pedido's estado, so a
    # credit note can still land on a cancelled ancestor two hops back.
    segundo = _corregir_monto(db, pedido_con_nc.id, "1200", active_user)
    pedidos_service.transicionar(db, pedido_id=segundo.id, accion="aprobar", user_id=active_user.id)
    tercero = _corregir_monto(db, segundo.id, "1300", active_user)
    nc2 = _ct(db, proveedor, sd_nc, ct=990203, lineas={501: "2"})
    _imputar_nc(db, proveedor, active_user, nc=nc2, pedido_id=pedido_con_nc.id)

    reconciliar_lineas_facturadas(db)

    assert _unidades(db, tercero.id) == {501: 7}


def test_migration_backfill_subtracts_the_credit_note_frozen_on_the_original(db, pedido_con_nc, active_user):
    migration = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "20261104_pedido_lineas_facturadas.py"
    spec = importlib.util.spec_from_file_location("pedido_lineas_facturadas_sqlite_clon", migration)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    clon = _corregir_monto(db, pedido_con_nc.id, "1200", active_user)
    db.execute(text("DELETE FROM pedido_compra_lineas_facturadas"))

    db.execute(text(module.BACKFILL))

    assert _unidades(db, clon.id) == {501: 9}


# An imputación on a corrected-from pedido must reach every descendant clone's
# snapshot at once, without waiting for the next ERP sync.


def test_credit_note_imputed_to_a_grandparent_reaches_the_clone_at_once(
    db, pedido_con_nc, proveedor, sd_nc, active_user
):
    segundo = _corregir_monto(db, pedido_con_nc.id, "1200", active_user)
    pedidos_service.transicionar(db, pedido_id=segundo.id, accion="aprobar", user_id=active_user.id)
    tercero = _corregir_monto(db, segundo.id, "1300", active_user)
    nc2 = _ct(db, proveedor, sd_nc, ct=990204, lineas={501: "2"})

    _imputar_nc(db, proveedor, active_user, nc=nc2, pedido_id=pedido_con_nc.id)

    assert _unidades(db, tercero.id) == {501: 7}


def test_reversed_credit_note_frozen_on_the_original_stops_counting_for_the_clone(db, pedido_con_nc, active_user):
    from app.models.imputacion import Imputacion  # noqa: PLC0415

    clon = _corregir_monto(db, pedido_con_nc.id, "1200", active_user)
    congelada = db.query(Imputacion).filter_by(destino_tipo="pedido_compra", destino_id=pedido_con_nc.id).one()

    imputaciones_service.desimputar(db, imputacion_id=congelada.id, user_id=active_user.id, motivo="error de carga")

    assert _unidades(db, clon.id) == {501: 10}
