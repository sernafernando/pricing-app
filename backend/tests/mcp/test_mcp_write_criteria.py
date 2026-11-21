"""C1 band for AI writes, read from #2333's per-MLA criteria (`ml_hay_mejores_criterios`)."""

from __future__ import annotations

import math
from decimal import Decimal

import pytest

from app.mcp.write import criteria
from app.models.ml_hay_mejores_criterios import MlHayMejoresCriterios
from app.models.producto import ProductoERP
from app.models.publicacion_ml import PublicacionML


def _criterios(db, mla: str, activo: bool, lo: str | None, hi: str | None) -> None:
    db.add(
        MlHayMejoresCriterios(
            item_id=mla,
            c1_activo=activo,
            c1_markup_min=None if lo is None else Decimal(lo),
            c1_markup_max=None if hi is None else Decimal(hi),
        )
    )


def _publicacion(db, item_id: int, mla: str, activo: bool = True) -> None:
    if db.get(ProductoERP, item_id) is None:
        db.add(ProductoERP(item_id=item_id, codigo=f"COD{item_id}", descripcion=f"Producto {item_id}"))
    db.add(PublicacionML(mla=mla, item_id=item_id, pricelist_id=4, activo=activo))


@pytest.mark.parametrize("accion", ["promo_aplicar", "promo_quitar", "precio_mayorista"])
def test_mla_target_uses_its_active_c1_band(db, accion):
    _criterios(db, "MLA100", True, "8", "25")
    db.commit()
    assert criteria.band_for(db, {"accion": accion, "objetivo": "MLA100"}) == (8.0, 25.0)


def test_mla_without_criteria_or_with_c1_off_has_no_band(db):
    _criterios(db, "MLA101", False, "8", "25")
    db.commit()
    assert criteria.band_for(db, {"accion": "promo_aplicar", "objetivo": "MLA101"}) is None
    assert criteria.band_for(db, {"accion": "promo_aplicar", "objetivo": "MLA999"}) is None


def test_open_side_of_the_band_is_unbounded(db):
    _criterios(db, "MLA102", True, "10", None)
    _criterios(db, "MLA103", True, None, "30")
    db.commit()
    assert criteria.band_for(db, {"accion": "promo_aplicar", "objetivo": "MLA102"}) == (10.0, math.inf)
    assert criteria.band_for(db, {"accion": "promo_aplicar", "objetivo": "MLA103"}) == (-math.inf, 30.0)


@pytest.mark.parametrize(
    ("accion", "objetivo"),
    [("precio_lista", "5001"), ("precio_markup_masivo", "5001"), ("precio_cuota", "5001:clasica:3")],
)
def test_product_price_takes_the_narrowest_band_of_its_active_publications(db, accion, objetivo):
    _publicacion(db, 5001, "MLA201")
    _publicacion(db, 5001, "MLA202")
    _publicacion(db, 5001, "MLA203", activo=False)
    _criterios(db, "MLA201", True, "5", "40")
    _criterios(db, "MLA202", True, "12", "30")
    _criterios(db, "MLA203", True, "90", "95")  # paused publication: ignored
    db.commit()
    assert criteria.band_for(db, {"accion": accion, "objetivo": objetivo}) == (12.0, 30.0)


def test_product_without_active_c1_on_its_publications_has_no_band(db):
    _publicacion(db, 5002, "MLA301")
    _criterios(db, "MLA301", False, "5", "40")
    db.commit()
    assert criteria.band_for(db, {"accion": "precio_lista", "objetivo": "5002"}) is None


def test_status_changes_have_no_band(db):
    _criterios(db, "MLA401", True, "8", "25")
    db.commit()
    assert criteria.band_for(db, {"accion": "estado_pausar", "objetivo": "MLA401"}) is None


def test_unreadable_criteria_fail_closed(db, monkeypatch):
    def boom(*_args, **_kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(criteria, "get_criterios", boom)
    assert criteria.band_for(db, {"accion": "promo_aplicar", "objetivo": "MLA100"}) == criteria.UNAVAILABLE


def test_unknown_target_shape_fails_closed(db):
    assert criteria.band_for(db, {"accion": "precio_lista", "objetivo": "no-es-un-id"}) == criteria.UNAVAILABLE
