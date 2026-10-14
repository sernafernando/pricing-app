"""PATCH /productos/{item_id}/rebate must recompute the stored markup_rebate.

Project rule: any write that changes a price input recomputes markup_rebate
in the same transaction, because list filters and stats read that stored
column (markup_rebate_positivo, markup_negativo_rebate). The rebate toggle
used to commit only participa_rebate/porcentaje_rebate, leaving the column
stale until some other price write happened.

Commission-table lookups and the shipping resolver are patched to fixed
values (same approach as test_pricing_manual_origen.py) so the test does not
need the full comision versioning fixture chain.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest

from app.models.permiso import Permiso, RolPermisoBase
from app.models.producto import ProductoERP, ProductoPricing, TipoMoneda
from app.models.tipo_cambio import TipoCambio

ITEM_ID = 3101


@pytest.fixture(autouse=True)
def _grant_toggle_rebate(db, rol_ventas):
    permiso = Permiso(
        codigo="productos.toggle_rebate", nombre="toggle_rebate", descripcion="", categoria="productos", orden=999
    )
    db.add(permiso)
    db.flush()
    db.add(RolPermisoBase(rol_id=rol_ventas.id, permiso_id=permiso.id))
    db.commit()


@pytest.fixture(autouse=True)
def _fixed_pricing_inputs():
    patches = [
        patch("app.services.pricing_calculator.obtener_grupo_subcategoria", return_value=1),
        patch("app.services.pricing_calculator.obtener_comision_base", return_value=15.0),
        patch("app.services.envio_real_service.resolver_costo_envio", return_value=0.0),
    ]
    for p in patches:
        p.start()
    yield
    for p in patches:
        p.stop()


def _seed(
    db, *, participa_rebate: bool, markup_rebate=None, costo: float = 1000.0, moneda: TipoMoneda = TipoMoneda.ARS
) -> None:
    db.add(
        ProductoERP(
            item_id=ITEM_ID,
            codigo=f"COD{ITEM_ID}",
            descripcion="Producto rebate",
            subcategoria_id=1,
            costo=costo,
            moneda_costo=moneda,
            iva=21.0,
        )
    )
    db.add(
        ProductoPricing(
            item_id=ITEM_ID,
            precio_lista_ml=2000.0,
            participa_rebate=participa_rebate,
            porcentaje_rebate=3.8,
            markup_rebate=markup_rebate,
        )
    )
    db.commit()


def _patch_rebate(client, headers, participa: bool, porcentaje: float):
    return client.patch(
        f"/api/productos/{ITEM_ID}/rebate",
        json={"participa_rebate": participa, "porcentaje_rebate": porcentaje},
        headers=headers,
    )


def _stored_markup_rebate(db):
    db.expire_all()
    return db.query(ProductoPricing).filter(ProductoPricing.item_id == ITEM_ID).one().markup_rebate


def test_activating_rebate_stores_a_markup_rebate(client, auth_headers, db) -> None:
    _seed(db, participa_rebate=False)

    response = _patch_rebate(client, auth_headers, True, 3.8)

    assert response.status_code == 200, response.text
    assert _stored_markup_rebate(db) is not None


def test_changing_rebate_percentage_recomputes_markup_rebate(client, auth_headers, db) -> None:
    _seed(db, participa_rebate=False)
    setup = _patch_rebate(client, auth_headers, True, 3.8)
    assert setup.status_code == 200, setup.text
    markup_bajo = _stored_markup_rebate(db)

    response = _patch_rebate(client, auth_headers, True, 10.0)

    assert response.status_code == 200, response.text
    markup_alto = _stored_markup_rebate(db)
    assert markup_bajo is not None and markup_alto is not None
    # A larger rebate raises the rebate price, so its markup must go up.
    assert float(markup_alto) > float(markup_bajo)


def test_deactivating_rebate_clears_a_stale_markup_rebate(client, auth_headers, db) -> None:
    _seed(db, participa_rebate=True, markup_rebate=42.0)

    response = _patch_rebate(client, auth_headers, False, 3.8)

    assert response.status_code == 200, response.text
    assert _stored_markup_rebate(db) is None


def test_bulk_limpiar_rebate_clears_stored_markup_rebate(client, auth_headers, db, rol_ventas) -> None:
    """limpiar-rebate turns participa_rebate off everywhere, so markup_rebate no longer applies."""
    permiso = Permiso(
        codigo="admin.limpieza_masiva", nombre="limpieza_masiva", descripcion="", categoria="admin", orden=999
    )
    db.add(permiso)
    db.flush()
    db.add(RolPermisoBase(rol_id=rol_ventas.id, permiso_id=permiso.id))
    _seed(db, participa_rebate=True, markup_rebate=42.0)

    response = client.post("/api/productos/limpiar-rebate", headers=auth_headers)

    assert response.status_code == 200, response.text
    assert _stored_markup_rebate(db) is None


def test_usd_costed_product_converts_cost_with_the_current_usd_rate(client, auth_headers, db) -> None:
    """USD cost 1 at a 1000 ARS rate must price exactly like an ARS cost of 1000."""
    _seed(db, participa_rebate=False)
    ars = _patch_rebate(client, auth_headers, True, 3.8)
    assert ars.status_code == 200, ars.text
    markup_ars = _stored_markup_rebate(db)

    db.query(ProductoPricing).delete()
    db.query(ProductoERP).delete()
    db.add(TipoCambio(moneda="USD", fecha=date.today(), compra=990.0, venta=1000.0))
    db.commit()
    _seed(db, participa_rebate=False, costo=1.0, moneda=TipoMoneda.USD)

    response = _patch_rebate(client, auth_headers, True, 3.8)

    assert response.status_code == 200, response.text
    markup_usd = _stored_markup_rebate(db)
    assert markup_ars is not None and markup_usd is not None
    assert float(markup_usd) == pytest.approx(float(markup_ars))


# Failure path: the toggle reuses the same chain as the price-writing endpoints in
# pricing.py (obtener_tipo_cambio_actual -> resolver_costo_envio ->
# calcular_markup_rebate). There, a missing rate converts the cost unchanged, a
# missing commission yields markup_rebate=None, and any exception inside the
# calculation is logged and yields None; the write itself still commits. These
# tests pin that the rebate toggle behaves the same way instead of returning 500.


def test_missing_commission_saves_rebate_with_null_markup(client, auth_headers, db) -> None:
    _seed(db, participa_rebate=False, markup_rebate=42.0)

    with patch("app.services.pricing_calculator.obtener_comision_base", return_value=None):
        response = _patch_rebate(client, auth_headers, True, 3.8)

    assert response.status_code == 200, response.text
    db.expire_all()
    pricing = db.query(ProductoPricing).filter(ProductoPricing.item_id == ITEM_ID).one()
    assert pricing.participa_rebate is True
    assert pricing.markup_rebate is None


def test_error_inside_markup_chain_saves_rebate_with_null_markup(client, auth_headers, db) -> None:
    _seed(db, participa_rebate=False, markup_rebate=42.0)

    with patch("app.services.pricing_calculator.obtener_comision_base", side_effect=RuntimeError("boom")):
        response = _patch_rebate(client, auth_headers, True, 3.8)

    assert response.status_code == 200, response.text
    db.expire_all()
    pricing = db.query(ProductoPricing).filter(ProductoPricing.item_id == ITEM_ID).one()
    assert pricing.participa_rebate is True
    assert pricing.markup_rebate is None


def test_usd_product_without_any_exchange_rate_still_saves(client, auth_headers, db) -> None:
    """No TipoCambio row: like pricing.py, convertir_a_pesos keeps the cost unconverted."""
    _seed(db, participa_rebate=False, costo=1000.0, moneda=TipoMoneda.USD)

    response = _patch_rebate(client, auth_headers, True, 3.8)

    assert response.status_code == 200, response.text
    assert _stored_markup_rebate(db) is not None
