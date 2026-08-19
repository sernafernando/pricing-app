"""The mass price-calculation endpoints must narrow their write set with the
SAME filters the listing uses.

`calcular-web-masivo` / `calcular-pvp-masivo` already honour a subset
(`search`, `con_stock`, `marcas`, `subcategorias`, ...), so the operator
reasonably reads "aplicar filtros" as "the products I am looking at". The
cross-DB filters (promos, wholesale tiers) were absent, so those two runs
disagreed about their own scope.

FAIL-CLOSED here, unlike the detail panel: these endpoints WRITE. If
mlwebhook cannot answer, the run must not proceed on a wider set — a
too-broad write is a repair job, a 503 is a retry.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.api.endpoints.productos_pricing import calcular_pvp_masivo, calcular_web_masivo
from app.core.security import get_password_hash
from app.models.producto import ProductoERP, ProductoPricing
from app.models.publicacion_ml import PublicacionML
from app.models.usuario import AuthProvider, RolUsuario, Usuario

_PXQ_READER = "app.api.endpoints.productos_shared.fetch_mlas_with_pxq_tiers"
_PROMO_READER = "app.api.endpoints.productos_shared.fetch_mlas_with_active_promo_type"


def _seed_user(db) -> Usuario:
    """The mass endpoints write an `auditoria` row bound to the acting user,
    so a real row must exist (FK)."""
    user = Usuario(
        username="masivo_user",
        email="masivo@example.com",
        nombre="Masivo User",
        password_hash=get_password_hash("Pass123!"),
        rol=RolUsuario.VENTAS,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(user)
    db.flush()
    return user


def _seed(db) -> Usuario:
    for item_id, mla in ((1, "MLA1"), (2, "MLA2")):
        db.add(
            ProductoERP(
                item_id=item_id,
                codigo=f"COD{item_id}",
                descripcion=f"Producto {item_id}",
                marca="MARCA",
                activo=True,
                stock=5,
                costo=100.0,
                iva=21.0,
            )
        )
        db.add(ProductoPricing(item_id=item_id, precio_lista_ml=1000.0, precio_pvp=1000.0))
        db.add(PublicacionML(mla=mla, item_id=item_id, activo=True))
    user = _seed_user(db)
    db.commit()
    return user


def _request(filtros):
    return SimpleNamespace(
        filtros=filtros,
        markup_pvp_clasica=10.0,
        adicional_cuotas=0.0,
        porcentaje_con_precio=6.0,
        porcentaje_sin_precio=6.0,
    )


_ENDPOINTS = [
    pytest.param(calcular_web_masivo, id="calcular-web-masivo"),
    pytest.param(calcular_pvp_masivo, id="calcular-pvp-masivo"),
]


class TestPxqNarrowsTheWriteSet:
    @pytest.mark.parametrize("endpoint", _ENDPOINTS)
    def test_con_pxq_limits_the_run_to_products_with_tiers(self, db, endpoint) -> None:
        user = _seed(db)

        with patch(_PXQ_READER, return_value={"MLA1"}):
            result = endpoint(request=_request({"con_pxq": True}), db=db, current_user=user)

        assert result["procesados"] == 1

    @pytest.mark.parametrize("endpoint", _ENDPOINTS)
    def test_empty_set_writes_nothing_instead_of_everything(self, db, endpoint) -> None:
        user = _seed(db)

        with patch(_PXQ_READER, return_value=set()):
            result = endpoint(request=_request({"con_pxq": True}), db=db, current_user=user)

        assert result["procesados"] == 0

    @pytest.mark.parametrize("endpoint", _ENDPOINTS)
    def test_cross_db_failure_fails_closed_with_503(self, db, endpoint) -> None:
        """A wider write is irreversible; a 503 is a retry."""
        user = _seed(db)

        with patch(_PXQ_READER, side_effect=RuntimeError("down")):
            with pytest.raises(HTTPException) as exc_info:
                endpoint(request=_request({"con_pxq": True}), db=db, current_user=user)

        assert exc_info.value.status_code == 503

    @pytest.mark.parametrize("endpoint", _ENDPOINTS)
    def test_absent_filter_does_not_call_the_reader(self, db, endpoint) -> None:
        user = _seed(db)

        with patch(_PXQ_READER) as mock_reader:
            endpoint(request=_request({"search": "Producto"}), db=db, current_user=user)

        mock_reader.assert_not_called()


class TestPromoNarrowsTheWriteSet:
    @pytest.mark.parametrize("endpoint", _ENDPOINTS)
    def test_promo_tipos_limits_the_run(self, db, endpoint) -> None:
        user = _seed(db)

        with patch(_PROMO_READER, return_value={"MLA2"}):
            result = endpoint(
                request=_request({"promo_tipos": "SMART", "promo_estado": "disponible"}),
                db=db,
                current_user=user,
            )

        assert result["procesados"] == 1

    @pytest.mark.parametrize("endpoint", _ENDPOINTS)
    def test_both_filters_intersect(self, db, endpoint) -> None:
        user = _seed(db)

        with (
            patch(_PXQ_READER, return_value={"MLA1", "MLA2"}),
            patch(_PROMO_READER, return_value={"MLA2"}),
        ):
            result = endpoint(
                request=_request({"con_pxq": True, "promo_tipos": "SMART", "promo_estado": "disponible"}),
                db=db,
                current_user=user,
            )

        assert result["procesados"] == 1
