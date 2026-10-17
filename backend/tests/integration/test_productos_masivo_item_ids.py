"""`calcular-web-masivo` / `calcular-pvp-masivo` with an explicit `item_ids` write set.

Publicaciones ML resolves its own filters to products (`/ml-publications/view/product-ids`) and asks the bulk
calculation over EXACTLY those ids. With `item_ids` the run touches those products and no other; `filtros` alongside
is refused (422), so no request can mean two sets at once. Without `item_ids` nothing changes (Productos' path).
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.endpoints.productos_pricing import (
    actualizar_config_cuotas_masivo,
    calcular_pvp_masivo,
    calcular_web_masivo,
)
from app.api.endpoints.productos_shared import (
    MAX_EXPLICIT_PRODUCT_IDS,
    CalculoPVPMasivoRequest,
    CalculoWebMasivoRequest,
    ConfigCuotasMasivoRequest,
)
from app.models.auditoria import Auditoria
from app.models.producto import ProductoPricing
from app.services.ml_publications.view import products as products_service
from tests.integration.test_productos_masivo_cross_db_filters import _seed

WEB = {"porcentaje_con_precio": 6.0, "porcentaje_sin_precio": 6.0}
PVP = {"markup_pvp_clasica": 10.0, "adicional_cuotas": 0.0}

_ENDPOINTS = [
    pytest.param(calcular_web_masivo, CalculoWebMasivoRequest, WEB, id="web"),
    pytest.param(calcular_pvp_masivo, CalculoPVPMasivoRequest, PVP, id="pvp"),
]


def _touched(db) -> dict[int, object]:
    """When each product's pricing was last written: both runs stamp it on every product they process (the prices
    themselves need the pricing constants, absent in this harness)."""
    db.expire_all()
    return {p.item_id: p.fecha_modificacion for p in db.query(ProductoPricing).all()}


@pytest.mark.parametrize("endpoint, model, base", _ENDPOINTS)
class TestItemIds:
    def test_the_run_touches_exactly_the_named_products(self, db, endpoint, model, base) -> None:
        user = _seed(db)
        before = _touched(db)

        result = endpoint(request=model(**base, item_ids=[2]), db=db, current_user=user)

        after = _touched(db)
        assert result["procesados"] == 1
        assert after[1] == before[1]  # product 1 is in no filter's way: only the id list decides
        assert after[2] != before[2]

    def test_filtros_alongside_item_ids_is_refused(self, db, endpoint, model, base) -> None:
        with pytest.raises(ValidationError):
            model(**base, item_ids=[1], filtros={"search": "Producto"})

    def test_an_empty_id_list_is_refused_never_read_as_everything(self, db, endpoint, model, base) -> None:
        with pytest.raises(ValidationError):
            model(**base, item_ids=[])

    def test_without_item_ids_the_run_is_the_filtered_one_as_before(self, db, endpoint, model, base) -> None:
        user = _seed(db)

        everything = endpoint(request=model(**base), db=db, current_user=user)
        filtered = endpoint(request=model(**base, filtros={"search": "Producto 1"}), db=db, current_user=user)

        assert (everything["procesados"], filtered["procesados"]) == (2, 1)
        assert "item_ids" not in model(**base).model_dump(exclude_unset=True)

    def test_duplicate_ids_collapse_in_first_seen_order(self, db, endpoint, model, base) -> None:
        assert model(**base, item_ids=[2, 1, 2, 1, 2]).item_ids == [2, 1]

    def test_the_audit_counts_the_unique_ids(self, db, endpoint, model, base) -> None:
        user = _seed(db)

        endpoint(request=model(**base, item_ids=[2, 2, 2]), db=db, current_user=user)

        audit = db.query(Auditoria).order_by(Auditoria.id.desc()).first()
        assert audit.valores_nuevos["item_ids_explicitos"] == 1

    def test_duplicates_do_not_use_up_the_cap(self, db, endpoint, model, base) -> None:
        many = list(range(1, MAX_EXPLICIT_PRODUCT_IDS + 1))
        assert len(model(**base, item_ids=many + many).item_ids) == MAX_EXPLICIT_PRODUCT_IDS

    def test_exactly_the_cap_is_accepted(self, db, endpoint, model, base) -> None:
        many = list(range(1, MAX_EXPLICIT_PRODUCT_IDS + 1))
        assert model(**base, item_ids=many).item_ids == many

    def test_one_over_the_cap_is_refused(self, db, endpoint, model, base) -> None:
        with pytest.raises(ValidationError):
            model(**base, item_ids=list(range(1, MAX_EXPLICIT_PRODUCT_IDS + 2)))


def test_the_bulk_cap_is_the_resolvers_cap() -> None:
    """One constant, so the resolver can never hand the bulk endpoints a set they refuse."""
    assert MAX_EXPLICIT_PRODUCT_IDS == products_service.MAX_PRODUCT_IDS == 10000


GONE = 999  # linked from a publication, no longer in productos_erp


@pytest.mark.parametrize("endpoint, model, base", _ENDPOINTS)
def test_an_id_not_in_the_catalog_refuses_the_whole_run(db, endpoint, model, base) -> None:
    """Never a silent partial run: an explicit set with an unknown product writes nothing and names it."""
    user = _seed(db)
    before = _touched(db)

    with pytest.raises(HTTPException) as exc_info:
        endpoint(request=model(**base, item_ids=[2, GONE]), db=db, current_user=user)

    assert exc_info.value.status_code == 422
    assert str(GONE) in str(exc_info.value.detail)
    assert _touched(db) == before


def test_config_cuotas_with_an_id_not_in_the_catalog_writes_nothing(db, monkeypatch) -> None:
    """It used to create a pricing row for it (a foreign key error, a 500, on Postgres)."""
    monkeypatch.setattr("app.services.permisos_service.verificar_permiso", lambda *a, **k: True)
    user = _seed(db)
    before = _touched(db)

    with pytest.raises(HTTPException) as exc_info:
        actualizar_config_cuotas_masivo(
            body=ConfigCuotasMasivoRequest(item_ids=[2, GONE], recalcular_cuotas_auto=True), db=db, current_user=user
        )

    assert exc_info.value.status_code == 422
    assert str(GONE) in str(exc_info.value.detail)
    assert _touched(db) == before
