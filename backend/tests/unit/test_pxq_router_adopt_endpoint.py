"""Tests for `POST /pxq/{item_id}/adopt-live` (change `pxq-adopt-live`, slice 4).

Its OWN file rather than an extension of an existing one. `tests/unit/` is the
right directory -- every router test for this feature lives here -- but neither
existing file fits: `test_pxq_router_tier_crud.py` covers three endpoints that
share one shape (local DB only, no ML traffic) and adopt-live makes a live
proxy read, while `test_pxq_router_live_endpoint.py` is built around the
async/short-session pool-safety proof that adopt-live deliberately does NOT
use. The precedent here is one file per endpoint shape, and adopt-live is a
third shape: sync `def`, ordinary session, one outbound READ, refusals raised
by the service and passed through verbatim.

Router functions are called directly with the real `db` fixture and
`PermisosService.tiene_permiso` is monkeypatched, exactly as
`test_pxq_router_tier_crud.py` does. All `ml_webhook_client` calls are mocked.
No live-prod calls ever.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.core.security import get_password_hash
from app.models.ml_pxq_tier import MlPxqTier
from app.models.producto import ProductoERP
from app.models.publicacion_ml import PublicacionML
from app.models.usuario import AuthProvider, RolUsuario, Usuario
from app.routers import pxq as pxq_router
from app.services import ml_pxq_adopt_service as adopt_service
from app.services.pxq_diff import MAX_TIERS


@pytest.fixture()
def pxq_user(db, rol_ventas) -> Usuario:
    user = Usuario(
        username="pxq_adopt_router_user",
        email="pxq_adopt_router_user@example.com",
        nombre="PxQ Adopt Router User",
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
def producto(db) -> ProductoERP:
    p = ProductoERP(item_id=90401, codigo="SKU-PXQ-ADOPT-EP", descripcion="Producto PxQ Adopt EP", costo=1000.0)
    db.add(p)
    db.flush()
    return p


@pytest.fixture()
def publicacion(db, producto) -> PublicacionML:
    pub = PublicacionML(mla="MLA940001", item_id=producto.item_id, codigo="SKU-PXQ-ADOPT-EP")
    db.add(pub)
    db.flush()
    return pub


@pytest.fixture(autouse=True)
def _grant_pxq_escribir(monkeypatch):
    """Same shortcut `test_pxq_router_tier_crud.py` uses. Patching the class
    attribute covers BOTH checks -- the router's `_require_pxq_write` and the
    service's own -- because they resolve the same `PermisosService`."""
    monkeypatch.setattr(pxq_router.PermisosService, "tiene_permiso", lambda self, usuario, codigo: True)


def _live(entry_id: Any, quantity: Any, amount: Any) -> Dict[str, Any]:
    return {"id": entry_id, "quantity": quantity, "amount": amount}


def _mock_client(live_prices: Optional[List[Dict[str, Any]]]):
    """Patches the live read on the SERVICE module -- the only ML call this
    path is ever allowed to make. Returned so tests can assert on call counts."""
    patcher = patch.object(adopt_service, "ml_webhook_client", MagicMock())
    mock_client = patcher.start()
    mock_client.get_pxq_prices = AsyncMock(return_value=live_prices)
    return patcher, mock_client


def _adopt(db, usuario, item_id: str):
    return pxq_router.adoptar_tramos_live_pxq(item_id=item_id, current_user=usuario, db=db)


def test_missing_pxq_escribir_is_403_and_makes_zero_ml_calls(db, publicacion, pxq_user, monkeypatch) -> None:
    """The permission must refuse BEFORE any proxy traffic. A 403 that still
    hit MercadoLibre would leak that the publication exists and burn quota on
    a caller that was never allowed to ask."""
    monkeypatch.setattr(pxq_router.PermisosService, "tiene_permiso", lambda self, usuario, codigo: False)
    patcher, mock_client = _mock_client([_live("ML1", 3, 900.0)])
    try:
        with pytest.raises(HTTPException) as exc:
            _adopt(db, pxq_user, publicacion.mla)
    finally:
        patcher.stop()

    assert exc.value.status_code == 403
    assert mock_client.get_pxq_prices.await_count == 0


def test_unknown_item_id_is_404_and_makes_zero_ml_calls(db, pxq_user) -> None:
    """The service takes `publicacion_ml_id` on trust and never verifies the
    publication exists (flagged in slice 3b-1). The router is the ONLY place
    that catches it, so this test pins that responsibility here."""
    patcher, mock_client = _mock_client([_live("ML1", 3, 900.0)])
    try:
        with pytest.raises(HTTPException) as exc:
            _adopt(db, pxq_user, "MLA_NOPE")
    finally:
        patcher.stop()

    assert exc.value.status_code == 404
    assert mock_client.get_pxq_prices.await_count == 0


def test_success_returns_count_and_the_imported_rows(db, publicacion, pxq_user) -> None:
    patcher, _ = _mock_client([_live("ML1", 3, 900.5), _live(2222, 6, "850.25")])
    try:
        result = _adopt(db, pxq_user, publicacion.mla)
    finally:
        patcher.stop()

    assert result.item_id == publicacion.mla
    assert result.count == 2
    assert len(result.imported) == 2
    assert [t.cantidad_minima for t in result.imported] == [3, 6]
    assert [t.ml_price_id for t in result.imported] == ["ML1", "2222"]
    assert [t.precio_unitario for t in result.imported] == [900.5, 850.25]
    assert all(t.costo_envio_total is None for t in result.imported)
    assert db.query(MlPxqTier).filter(MlPxqTier.publicacion_ml_id == publicacion.id).count() == 2


def test_empty_live_set_is_a_success_with_count_zero(db, publicacion, pxq_user) -> None:
    """`[]` means MercadoLibre genuinely holds no tiers. That is a 200, never
    an error -- the service already draws that line and the router must not
    re-interpret it."""
    patcher, _ = _mock_client([])
    try:
        result = _adopt(db, pxq_user, publicacion.mla)
    finally:
        patcher.stop()

    assert result.count == 0
    assert result.imported == []
    # Nothing was skipped either, and that is what tells this apart from the
    # "ML holds prices we cannot mirror" case below.
    assert result.skipped_count == 0
    assert result.skipped == []


def test_a_skipped_entry_is_reported_with_its_ml_price_id_and_quantity(db, publicacion, pxq_user) -> None:
    """This response is the only thing that accounts for a gap the operator can
    SEE: `GET /{item_id}/live` goes on reporting the skipped entry in
    `live_tiers`, so the panel renders it in the live column against a mirror
    column that will never match. A count alone would leave "2 imported"
    reading as "the mirror matches ML" -- exactly the false belief this
    reporting exists to prevent."""
    patcher, _ = _mock_client([_live(3396, 1, 80999), _live("ML2", 3, 900.5), _live("ML3", 6, 850.25)])
    try:
        result = _adopt(db, pxq_user, publicacion.mla)
    finally:
        patcher.stop()

    assert result.count == 2
    assert [t.cantidad_minima for t in result.imported] == [3, 6]
    assert result.skipped_count == 1
    assert [s.cantidad_minima for s in result.skipped] == [1]
    assert [s.ml_price_id for s in result.skipped] == ["3396"]
    assert db.query(MlPxqTier).filter(MlPxqTier.publicacion_ml_id == publicacion.id).count() == 2


def test_a_fully_skipped_live_set_is_count_zero_WITH_a_skip_reported(db, publicacion, pxq_user) -> None:
    """`count == 0` on its own is ambiguous and the frontend renders two
    different messages off it: "MercadoLibre ya no tiene tramos" is FALSE
    here -- ML has a price, it is just not one this mirror can hold. The skip
    list is what disambiguates them."""
    patcher, _ = _mock_client([_live("ML1", 1, 999.0)])
    try:
        result = _adopt(db, pxq_user, publicacion.mla)
    finally:
        patcher.stop()

    assert result.count == 0
    assert result.imported == []
    assert result.skipped_count == 1
    assert [s.cantidad_minima for s in result.skipped] == [1]


def test_conflict_detail_passes_through_untouched(db, publicacion, pxq_user) -> None:
    """The 409 detail is the frontend's only source for WHICH tiers block the
    import. Re-wrapping or flattening it to a status string leaves the operator
    with a refusal and nothing to act on."""
    existing = MlPxqTier(
        publicacion_ml_id=publicacion.id,
        item_id=publicacion.mla,
        cantidad_minima=4,
        precio_unitario=700.0,
        usuario_id=pxq_user.id,
    )
    db.add(existing)
    db.flush()

    patcher, _ = _mock_client([_live("ML1", 3, 900.0)])
    try:
        with pytest.raises(HTTPException) as exc:
            _adopt(db, pxq_user, publicacion.mla)
    finally:
        patcher.stop()

    assert exc.value.status_code == 409
    detail = exc.value.detail
    assert isinstance(detail, dict)
    assert detail["status"] == "adopt_conflict"
    assert detail["conflicts"] == [{"tier_id": existing.id, "cantidad_minima": 4}]


def test_read_unavailable_detail_passes_through_untouched(db, publicacion, pxq_user) -> None:
    patcher, _ = _mock_client(None)
    try:
        with pytest.raises(HTTPException) as exc:
            _adopt(db, pxq_user, publicacion.mla)
    finally:
        patcher.stop()

    assert exc.value.status_code == 503
    detail = exc.value.detail
    assert isinstance(detail, dict)
    assert detail["status"] == "adopt_read_unavailable"
    assert "nothing was imported" in detail["reason"]


def test_more_live_tiers_than_max_is_503_not_409_and_not_422(db, publicacion, pxq_user) -> None:
    """`MAX_TIERS` is MercadoLibre's OWN platform limit, so receiving more is
    an impossible state: the read is untrustworthy, not a conflict the operator
    could resolve and not a complaint about input they never sent. The spec
    (422) and design D15 (409) are both wrong here."""
    patcher, _ = _mock_client([_live(f"ML{n}", n + 2, 900.0) for n in range(MAX_TIERS + 1)])
    try:
        with pytest.raises(HTTPException) as exc:
            _adopt(db, pxq_user, publicacion.mla)
    finally:
        patcher.stop()

    assert exc.value.status_code == 503
    assert exc.value.detail["status"] == "adopt_read_unavailable"
    assert db.query(MlPxqTier).filter(MlPxqTier.publicacion_ml_id == publicacion.id).count() == 0


def test_the_route_is_registered_as_post_pxq_item_id_adopt_live() -> None:
    routes = {(r.path, frozenset(r.methods)) for r in pxq_router.router.routes}

    assert ("/pxq/{item_id}/adopt-live", frozenset({"POST"})) in routes


def test_the_router_does_not_commit_on_top_of_the_service(db, publicacion, pxq_user, monkeypatch) -> None:
    """The service owns the single commit that also releases the publication
    row lock. A second commit in the router would open an empty transaction
    after the lock is already gone -- harmless today, and exactly the kind of
    thing that stops being harmless when someone adds a write after the call."""
    commits: List[int] = []
    original_commit = db.commit

    def _counting_commit() -> None:
        commits.append(1)
        original_commit()

    monkeypatch.setattr(db, "commit", _counting_commit)

    patcher, _ = _mock_client([_live("ML1", 3, 900.0)])
    try:
        _adopt(db, pxq_user, publicacion.mla)
    finally:
        patcher.stop()

    assert len(commits) == 1


def test_adopt_live_does_not_touch_the_sync_status_mapping() -> None:
    """Adopt-live raises `HTTPException` directly (design D14). It must not add
    keys here: `_SYNC_STATUS_TO_HTTP` is 1:1 coupled to `SYNC_STATUSES` by
    `test_pxq_router_live_endpoint.py::test_every_non_success_status_has_an_http_mapping`,
    so an adopt status added to either side breaks that test for a status the
    sync path can never return."""
    assert set(pxq_router._SYNC_STATUS_TO_HTTP) == {
        "disabled",
        "rejected_not_eligible",
        "rejected_read_unavailable",
        "rejected_eligibility_unknown",
        "divergence",
        "rejected_by_proxy",
        "submitted_unconfirmed",
        "ambiguous_needs_reconcile",
    }
