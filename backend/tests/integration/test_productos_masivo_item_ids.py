"""`calcular-web-masivo` / `calcular-pvp-masivo` with an explicit `item_ids` write set.

Publicaciones ML resolves its own filters to products (`/ml-publications/view/product-ids`) and asks the bulk
calculation over EXACTLY those ids. With `item_ids` the run touches those products and no other; `filtros` alongside
is refused (422), so no request can mean two sets at once. Without `item_ids` nothing changes (Productos' path).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.api.endpoints.productos_pricing import calcular_pvp_masivo, calcular_web_masivo
from app.api.endpoints.productos_shared import CalculoPVPMasivoRequest, CalculoWebMasivoRequest
from app.models.producto import ProductoPricing
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
