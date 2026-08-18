"""Tests for `POST /pxq/{item_id}/sync` (slice C2 of
`pxq-markup-antes-de-publicar`): the `publicar_sin_markup` request field.

Its own file, same precedent `test_pxq_router_adopt_endpoint.py` states for
adopt-live: `sincronizar_pxq` calls the real `sync_pxq_tiers` with a mocked
`ml_webhook_client`, exactly the shape `test_ml_pxq_write_service.py` already
uses for the service itself -- this file only proves the ROUTER threads the
new field through, never re-tests the gate/override behavior the service
suite already covers.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.core.security import get_password_hash
from app.models.comision_versionada import ComisionBase, ComisionVersion
from app.models.ml_pxq_tier import ESTADO_LISTO, MlPxqTier
from app.models.producto import ProductoERP
from app.models.publicacion_ml import PublicacionML
from app.models.usuario import AuthProvider, RolUsuario, Usuario
from app.routers import pxq as pxq_router
from app.routers.pxq import PxqSyncRequest
from app.services import ml_pxq_write_service as write_service


@pytest.fixture()
def pxq_user(db, rol_ventas) -> Usuario:
    user = Usuario(
        username="pxq_sync_router_user",
        email="pxq_sync_router_user@example.com",
        nombre="PxQ Sync Router User",
        password_hash=get_password_hash("TestPass123!"),
        rol=RolUsuario.VENTAS,
        rol_id=rol_ventas.id,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(user)
    db.flush()
    return user


@pytest.fixture()
def comision_fixtures(db) -> ComisionVersion:
    version = ComisionVersion(nombre="Test PxQ Sync Router", fecha_desde=date(2000, 1, 1), activo=True)
    db.add(version)
    db.flush()
    db.add(ComisionBase(version_id=version.id, grupo_id=1, comision_base=20.0))
    db.flush()
    return version


@pytest.fixture()
def producto(db) -> ProductoERP:
    p = ProductoERP(item_id=90501, codigo="SKU-PXQ-SYNC-EP", descripcion="Producto PxQ Sync EP", costo=1000.0)
    db.add(p)
    db.flush()
    return p


@pytest.fixture()
def publicacion(db, producto, comision_fixtures) -> PublicacionML:
    pub = PublicacionML(mla="MLA950001", item_id=producto.item_id, codigo="SKU-PXQ-SYNC-EP", pricelist_id=4)
    db.add(pub)
    db.flush()
    return pub


@pytest.fixture(autouse=True)
def _grant_pxq_escribir(monkeypatch):
    monkeypatch.setattr(pxq_router.PermisosService, "tiene_permiso", lambda self, usuario, codigo: True)


def _eligible() -> dict:
    return {"item_tags": ["standard_price_by_quantity"], "seller_tags": ["business"]}


def _mock_client(**overrides):
    patcher = patch.object(write_service, "ml_webhook_client")
    mock_client = patcher.start()
    mock_client.get_pxq_eligibility = AsyncMock(return_value=overrides.get("eligibility", _eligible()))
    mock_client.get_pxq_prices = AsyncMock(return_value=overrides.get("live_prices", []))
    mock_client.post_pxq_prices = AsyncMock(
        return_value=overrides.get("post_result", {"ok": True, "status_code": 200, "ambiguous": False, "body": None})
    )
    return patcher, mock_client


def _sync(db, usuario, item_id: str, body: PxqSyncRequest):
    return pxq_router.sincronizar_pxq(item_id=item_id, body=body, current_user=usuario, db=db)


class TestPublicarSinMarkupRequestField:
    def test_default_is_false(self) -> None:
        body = PxqSyncRequest()
        assert body.publicar_sin_markup is False

    def test_field_does_not_persist_between_requests(self, db, publicacion, pxq_user) -> None:
        """Per-request, never sticky: constructing a fresh request after one
        that opted in must NOT inherit `True` from anywhere -- there is no
        module-level or session-level state to carry it."""
        # No unresolved tiers needed here: this only proves the Pydantic model
        # itself carries no memory across instances.
        opted_in = PxqSyncRequest(publicar_sin_markup=True)
        assert opted_in.publicar_sin_markup is True

        fresh = PxqSyncRequest()
        assert fresh.publicar_sin_markup is False

    def test_router_threads_the_flag_into_sync_pxq_tiers(self, db, publicacion, pxq_user, monkeypatch) -> None:
        """The router must not swallow the field: it has to reach
        `sync_pxq_tiers` as the exact keyword the service expects."""
        captured: dict = {}
        real_sync = write_service.sync_pxq_tiers

        def spy_sync(db_arg, usuario, item_id, *, allow_clear=False, publicar_sin_markup=False):
            captured["publicar_sin_markup"] = publicar_sin_markup
            return real_sync(db_arg, usuario, item_id, allow_clear=allow_clear, publicar_sin_markup=publicar_sin_markup)

        monkeypatch.setattr(pxq_router, "sync_pxq_tiers", spy_sync)
        monkeypatch.setattr(write_service.settings, "PXQ_WRITE_ENABLED", True)
        patcher, mock_client = _mock_client(live_prices=[])
        try:
            # No tiers exist for this publication, so the sync itself refuses
            # with a divergence (empty desired set) -- irrelevant here: the
            # spy already captured the keyword the router passed BEFORE the
            # real service raised.
            with pytest.raises(HTTPException):
                _sync(db, pxq_user, publicacion.mla, PxqSyncRequest(publicar_sin_markup=True))
        finally:
            patcher.stop()

        assert captured["publicar_sin_markup"] is True

    def test_override_lets_an_unresolved_tier_be_posted_via_the_endpoint(self, db, pxq_user, monkeypatch) -> None:
        # No comision_fixtures for this publication: markup stays unresolved.
        producto = ProductoERP(
            item_id=90502, codigo="SKU-PXQ-SYNC-EP-OVERRIDE", descripcion="Sin comision", costo=1000.0
        )
        db.add(producto)
        db.flush()
        pub = PublicacionML(
            mla="MLA950002", item_id=producto.item_id, codigo="SKU-PXQ-SYNC-EP-OVERRIDE", pricelist_id=4
        )
        db.add(pub)
        db.flush()
        tier = MlPxqTier(
            publicacion_ml_id=pub.id,
            item_id=pub.mla,
            cantidad_minima=10,
            precio_unitario=Decimal("500.00"),
            costo_envio_total=Decimal("50.00"),
            ml_price_id=None,
            estado=ESTADO_LISTO,
            usuario_id=pxq_user.id,
        )
        db.add(tier)
        db.flush()

        monkeypatch.setattr(write_service.settings, "PXQ_WRITE_ENABLED", True)
        patcher, mock_client = _mock_client(
            live_prices=[],
            post_result={"ok": True, "status_code": 200, "ambiguous": False, "body": None},
        )
        mock_client.get_pxq_prices.side_effect = [
            [],
            [{"id": "ML10", "quantity": 10, "amount": 500.0}],
        ]
        try:
            result = _sync(db, pxq_user, pub.mla, PxqSyncRequest(publicar_sin_markup=True))
        finally:
            patcher.stop()

        assert result.synced is True
        mock_client.post_pxq_prices.assert_called_once()

    def test_without_override_the_unresolved_tier_is_excluded_by_the_endpoint(self, db, pxq_user, monkeypatch) -> None:
        producto = ProductoERP(
            item_id=90503, codigo="SKU-PXQ-SYNC-EP-NOOVERRIDE", descripcion="Sin comision", costo=1000.0
        )
        db.add(producto)
        db.flush()
        pub = PublicacionML(
            mla="MLA950003", item_id=producto.item_id, codigo="SKU-PXQ-SYNC-EP-NOOVERRIDE", pricelist_id=4
        )
        db.add(pub)
        db.flush()
        tier = MlPxqTier(
            publicacion_ml_id=pub.id,
            item_id=pub.mla,
            cantidad_minima=10,
            precio_unitario=Decimal("500.00"),
            costo_envio_total=Decimal("50.00"),
            ml_price_id=None,
            estado=ESTADO_LISTO,
            usuario_id=pxq_user.id,
        )
        db.add(tier)
        db.flush()

        monkeypatch.setattr(write_service.settings, "PXQ_WRITE_ENABLED", True)
        patcher, mock_client = _mock_client(live_prices=[])
        try:
            # Empty desired set against an empty live read is a divergence
            # refusal (`empty_desired_set`), same as the boundary-b test for
            # this exact gate -- the point here is only that the router did
            # not silently smuggle the unresolved tier through.
            with pytest.raises(HTTPException):
                _sync(db, pxq_user, pub.mla, PxqSyncRequest())
        finally:
            patcher.stop()

        mock_client.post_pxq_prices.assert_not_called()
