"""Unit tests for the PxQ write-orchestration service
`ml_pxq_write_service.py` (PR 3b, tasks 39-50, 56-58).

Order of operations under test (`sync_pxq_tiers`):
  1. kill-switch (`settings.PXQ_WRITE_ENABLED`) checked FIRST, before any
     permission/eligibility check or ML call.
  2. permission `pxq.escribir` -> else 403.
  3. eligibility: seller `business` tag, item `standard_price_by_quantity`
     tag -> else rejected.
  4. fresh LIVE read (never cached) -> None -> rejected_read_unavailable.
  5. `diff_pxq_tiers(...)` -- divergence -> refused, no write.
  6. POST the resulting array; on CONFIRMED success (re-read matches),
     persist the snapshot in the SAME transaction; on POST failure/
     ambiguity or a failed re-read, the snapshot must NOT be written.

All ml_webhook_client calls are mocked. No live-prod calls ever.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch


import httpx
import pytest
from fastapi import HTTPException

from app.core.security import get_password_hash
from app.models.comision_versionada import ComisionBase, ComisionVersion
from app.models.ml_pxq_tier import ESTADO_DESCONOCIDO, ESTADO_LISTO, ESTADO_SINCRONIZADO, MlPxqTier
from app.models.producto import ProductoERP
from app.models.publicacion_ml import PublicacionML
from app.models.usuario import AuthProvider, RolUsuario, Usuario
from app.services import ml_pxq_write_service as write_service
from app.services.ml_webhook_client import MLWebhookClient
from app.services.pxq_permissions_backfill import PXQ_ESCRIBIR_CODE


@pytest.fixture()
def pxq_user(db, rol_ventas) -> Usuario:
    user = Usuario(
        username="pxq_write_user",
        email="pxq_write_user@example.com",
        nombre="PxQ Write User",
        password_hash=get_password_hash("TestPass123!"),
        rol=RolUsuario.VENTAS,
        rol_id=rol_ventas.id,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(user)
    db.flush()
    user._permisos_cache = {PXQ_ESCRIBIR_CODE}
    return user


@pytest.fixture()
def pxq_user_no_permission(db, rol_ventas) -> Usuario:
    user = Usuario(
        username="pxq_write_user_noperm",
        email="pxq_write_user_noperm@example.com",
        nombre="PxQ Write User No Permission",
        password_hash=get_password_hash("TestPass123!"),
        rol=RolUsuario.VENTAS,
        rol_id=rol_ventas.id,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(user)
    db.flush()
    user._permisos_cache = set()
    return user


@pytest.fixture()
def comision_fixtures(db) -> ComisionVersion:
    """Resolvable commission-base context (D4/3.3): `markup_resolved` needs
    `markup_for_tiers` to resolve BOTH the pricing context (this fixture) and
    a tier's `costo_envio_total` -- the old gate only needed the second.
    Mirrors `test_pxq_markup_service.py`'s `comision_fixtures` fixture."""
    version = ComisionVersion(nombre="Test PxQ Write", fecha_desde=date(2000, 1, 1), activo=True)
    db.add(version)
    db.flush()
    db.add(ComisionBase(version_id=version.id, grupo_id=1, comision_base=20.0))
    db.flush()
    return version


@pytest.fixture()
def producto(db) -> ProductoERP:
    p = ProductoERP(item_id=90201, codigo="SKU-PXQ-WRITE", descripcion="Producto PxQ Write", costo=1000.0)
    db.add(p)
    db.flush()
    return p


@pytest.fixture()
def publicacion(db, producto, comision_fixtures) -> PublicacionML:
    pub = PublicacionML(mla="MLA920001", item_id=producto.item_id, codigo="SKU-PXQ-WRITE", pricelist_id=4)
    db.add(pub)
    db.flush()
    return pub


@pytest.fixture()
def synced_tier(db, publicacion, pxq_user) -> MlPxqTier:
    """A tier already synced once: carries a snapshot + ml_price_id."""
    tier = MlPxqTier(
        publicacion_ml_id=publicacion.id,
        item_id=publicacion.mla,
        cantidad_minima=10,
        precio_unitario=Decimal("500.00"),
        costo_envio_total=Decimal("50.00"),
        ml_price_id="ML1",
        cantidad_sincronizada=10,
        precio_sincronizado=Decimal("500.00"),
        estado=ESTADO_SINCRONIZADO,
        usuario_id=pxq_user.id,
    )
    db.add(tier)
    db.flush()
    return tier


def _eligible() -> dict:
    return {"item_tags": ["standard_price_by_quantity"], "seller_tags": ["business"]}


def _mock_client(**overrides):
    """Patches `write_service.ml_webhook_client` with AsyncMocks; overrides
    replace individual method return values."""
    patcher = patch.object(write_service, "ml_webhook_client")
    mock_client = patcher.start()
    mock_client.get_pxq_eligibility = AsyncMock(return_value=overrides.get("eligibility", _eligible()))
    mock_client.get_pxq_prices = AsyncMock(return_value=overrides.get("live_prices", []))
    mock_client.post_pxq_prices = AsyncMock(
        return_value=overrides.get("post_result", {"ok": True, "status_code": 200, "ambiguous": False, "body": None})
    )
    return patcher, mock_client


class TestKillSwitch:
    def test_disabled_blocks_before_any_check_or_call(self, db, publicacion, pxq_user, monkeypatch) -> None:
        monkeypatch.setattr(write_service.settings, "PXQ_WRITE_ENABLED", False)
        patcher, mock_client = _mock_client()
        try:
            outcome = write_service.sync_pxq_tiers(db, pxq_user, publicacion.mla)
        finally:
            patcher.stop()

        assert outcome["status"] == "disabled"
        assert outcome["synced"] is False
        mock_client.get_pxq_eligibility.assert_not_called()
        mock_client.get_pxq_prices.assert_not_called()
        mock_client.post_pxq_prices.assert_not_called()


class TestPermissionGate:
    def test_missing_permission_raises_403(self, db, publicacion, pxq_user_no_permission, monkeypatch) -> None:
        monkeypatch.setattr(write_service.settings, "PXQ_WRITE_ENABLED", True)
        patcher, mock_client = _mock_client()
        try:
            with pytest.raises(HTTPException) as exc_info:
                write_service.sync_pxq_tiers(db, pxq_user_no_permission, publicacion.mla)
        finally:
            patcher.stop()

        assert exc_info.value.status_code == 403
        mock_client.get_pxq_eligibility.assert_not_called()


class TestEligibilityGate:
    def test_seller_missing_business_tag_blocks(self, db, publicacion, pxq_user, monkeypatch) -> None:
        monkeypatch.setattr(write_service.settings, "PXQ_WRITE_ENABLED", True)
        patcher, mock_client = _mock_client(
            eligibility={"item_tags": ["standard_price_by_quantity"], "seller_tags": []}
        )
        try:
            outcome = write_service.sync_pxq_tiers(db, pxq_user, publicacion.mla)
        finally:
            patcher.stop()

        assert outcome["status"] == "rejected_not_eligible"
        mock_client.get_pxq_prices.assert_not_called()
        mock_client.post_pxq_prices.assert_not_called()

    def test_item_missing_pxq_tag_blocks(self, db, publicacion, pxq_user, monkeypatch) -> None:
        monkeypatch.setattr(write_service.settings, "PXQ_WRITE_ENABLED", True)
        patcher, mock_client = _mock_client(eligibility={"item_tags": [], "seller_tags": ["business"]})
        try:
            outcome = write_service.sync_pxq_tiers(db, pxq_user, publicacion.mla)
        finally:
            patcher.stop()

        assert outcome["status"] == "rejected_not_eligible"
        mock_client.post_pxq_prices.assert_not_called()


class TestGateOrder:
    def test_gate_order_is_kill_switch_then_permission_then_eligibility_then_live_read(
        self, db, publicacion, pxq_user_no_permission, monkeypatch
    ) -> None:
        """Missing permission must short-circuit BEFORE eligibility is ever
        consulted -- proven by asserting zero calls, not just the final
        outcome."""
        monkeypatch.setattr(write_service.settings, "PXQ_WRITE_ENABLED", True)
        patcher, mock_client = _mock_client()
        try:
            with pytest.raises(HTTPException):
                write_service.sync_pxq_tiers(db, pxq_user_no_permission, publicacion.mla)
        finally:
            patcher.stop()
        mock_client.get_pxq_eligibility.assert_not_called()
        mock_client.get_pxq_prices.assert_not_called()


class TestLiveReadUnavailable:
    def test_none_live_read_rejects_before_diff(self, db, publicacion, pxq_user, monkeypatch) -> None:
        monkeypatch.setattr(write_service.settings, "PXQ_WRITE_ENABLED", True)
        patcher, mock_client = _mock_client(live_prices=None)
        try:
            outcome = write_service.sync_pxq_tiers(db, pxq_user, publicacion.mla)
        finally:
            patcher.stop()

        assert outcome["status"] == "rejected_read_unavailable"
        mock_client.post_pxq_prices.assert_not_called()


class TestMarkupResolvedGate:
    """D4 (slice C): the gate is `markup_resolved`, not `is_priceable`. A tier
    can carry a whole-shipment cost (`costo_envio_total`) and STILL be
    unresolved when the commission base cannot be resolved -- the old gate
    let that tier reach MercadoLibre anyway, because it only ever checked the
    shipping cost."""

    def test_unresolvable_commission_base_excludes_the_tier_by_default(self, db, pxq_user, monkeypatch) -> None:
        # Deliberately NO `comision_fixtures`: no `ComisionBase` row exists, so
        # `markup_for_tiers` cannot resolve a commission base for this tier
        # even though `costo_envio_total` is set.
        producto = ProductoERP(
            item_id=90301, codigo="SKU-PXQ-UNRESOLVED", descripcion="Producto sin comision", costo=1000.0
        )
        db.add(producto)
        db.flush()
        pub = PublicacionML(mla="MLA930001", item_id=producto.item_id, codigo="SKU-PXQ-UNRESOLVED", pricelist_id=4)
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
            outcome = write_service.sync_pxq_tiers(db, pxq_user, pub.mla)
        finally:
            patcher.stop()

        # Nothing to send: the only tier is excluded by the gate, so the diff
        # is empty and the POST is never attempted.
        mock_client.post_pxq_prices.assert_not_called()
        assert outcome["status"] in ("sincronizado", "divergence")
        db.refresh(tier)
        assert tier.estado == ESTADO_LISTO  # untouched: never considered for write


class TestBoundaryAssert:
    def test_full_sync_never_dirties_producto_pricing(
        self, db, publicacion, pxq_user, synced_tier, monkeypatch
    ) -> None:
        monkeypatch.setattr(write_service.settings, "PXQ_WRITE_ENABLED", True)
        patcher, mock_client = _mock_client(
            live_prices=[{"id": "ML1", "quantity": 10, "amount": 500.0}],
            post_result={"ok": True, "status_code": 200, "ambiguous": False, "body": None},
        )
        try:
            write_service.sync_pxq_tiers(db, pxq_user, publicacion.mla)
        finally:
            patcher.stop()
        db.refresh(synced_tier)
        assert synced_tier.estado == ESTADO_SINCRONIZADO


class TestSyncHappyPath:
    def test_full_sync_confirms_and_writes_snapshot(self, db, publicacion, pxq_user, monkeypatch) -> None:
        modified_tier = MlPxqTier(
            publicacion_ml_id=publicacion.id,
            item_id=publicacion.mla,
            cantidad_minima=10,
            precio_unitario=Decimal("550.00"),
            costo_envio_total=Decimal("50.00"),
            ml_price_id="ML1",
            cantidad_sincronizada=10,
            precio_sincronizado=Decimal("500.00"),
            estado=ESTADO_LISTO,
            usuario_id=pxq_user.id,
        )
        db.add(modified_tier)
        db.flush()

        monkeypatch.setattr(write_service.settings, "PXQ_WRITE_ENABLED", True)
        patcher, mock_client = _mock_client(
            live_prices=[{"id": "ML1", "quantity": 10, "amount": 500.0}],
            post_result={"ok": True, "status_code": 200, "ambiguous": False, "body": None},
        )
        # The FIRST get_pxq_prices call is the pre-write divergence read;
        # the SECOND (post-write) is the confirmation re-read reporting
        # the NEW id ML1-NEW for the modified tier.
        mock_client.get_pxq_prices.side_effect = [
            [{"id": "ML1", "quantity": 10, "amount": 500.0}],
            [{"id": "ML1-NEW", "quantity": 10, "amount": 550.0}],
        ]
        try:
            outcome = write_service.sync_pxq_tiers(db, pxq_user, publicacion.mla)
        finally:
            patcher.stop()

        assert outcome["synced"] is True
        assert outcome["status"] == "sincronizado"
        db.refresh(modified_tier)
        assert modified_tier.estado == ESTADO_SINCRONIZADO
        assert modified_tier.ml_price_id == "ML1-NEW"
        assert modified_tier.cantidad_sincronizada == 10
        assert modified_tier.precio_sincronizado == Decimal("550.00")

    def test_post_timeout_marks_desconocido_and_never_writes_snapshot(
        self, db, publicacion, pxq_user, synced_tier, monkeypatch
    ) -> None:
        # Move the tier so a real sync attempt would be a modify, to prove
        # the failed POST leaves the OLD snapshot untouched (never advanced
        # to the value we attempted to write).
        synced_tier.precio_unitario = Decimal("999.00")
        synced_tier.estado = ESTADO_LISTO
        db.flush()

        monkeypatch.setattr(write_service.settings, "PXQ_WRITE_ENABLED", True)
        patcher, mock_client = _mock_client(
            live_prices=[{"id": "ML1", "quantity": 10, "amount": 500.0}],
            post_result={"ok": False, "status_code": None, "ambiguous": True, "body": None},
        )
        try:
            outcome = write_service.sync_pxq_tiers(db, pxq_user, publicacion.mla)
        finally:
            patcher.stop()

        assert outcome["synced"] is False
        assert outcome["status"] == "ambiguous_needs_reconcile"
        db.refresh(synced_tier)
        assert synced_tier.estado == ESTADO_DESCONOCIDO
        assert synced_tier.ml_price_id == "ML1"  # untouched
        assert synced_tier.precio_sincronizado == Decimal("500.00")  # snapshot NOT advanced

    def test_confirmation_reread_failure_marks_unconfirmed_never_writes_snapshot(
        self, db, publicacion, pxq_user, synced_tier, monkeypatch
    ) -> None:
        synced_tier.precio_unitario = Decimal("777.00")
        synced_tier.estado = ESTADO_LISTO
        db.flush()

        monkeypatch.setattr(write_service.settings, "PXQ_WRITE_ENABLED", True)
        patcher, mock_client = _mock_client(
            post_result={"ok": True, "status_code": 200, "ambiguous": False, "body": None},
        )
        mock_client.get_pxq_prices.side_effect = [
            [{"id": "ML1", "quantity": 10, "amount": 500.0}],
            None,  # post-write confirmation read fails
        ]
        try:
            outcome = write_service.sync_pxq_tiers(db, pxq_user, publicacion.mla)
        finally:
            patcher.stop()

        # NOT synced: the POST left, but nobody could confirm what landed. This
        # assertion used to read `is True`, which encoded the defect rather than
        # catching it — the UI would have painted an unknown write as done.
        assert outcome["synced"] is False
        assert outcome["status"] == "submitted_unconfirmed"
        db.refresh(synced_tier)
        assert synced_tier.estado == ESTADO_DESCONOCIDO
        assert synced_tier.precio_sincronizado == Decimal("500.00")  # snapshot NOT advanced to 777

    def test_divergence_refuses_write_with_no_post_attempted(
        self, db, publicacion, pxq_user, synced_tier, monkeypatch
    ) -> None:
        monkeypatch.setattr(write_service.settings, "PXQ_WRITE_ENABLED", True)
        # Live moved since the last sync (500 -> 470); local mirror unchanged.
        patcher, mock_client = _mock_client(live_prices=[{"id": "ML1", "quantity": 10, "amount": 470.0}])
        try:
            outcome = write_service.sync_pxq_tiers(db, pxq_user, publicacion.mla)
        finally:
            patcher.stop()

        assert outcome["synced"] is False
        assert outcome["status"] == "divergence"
        mock_client.post_pxq_prices.assert_not_called()
        db.refresh(synced_tier)
        assert synced_tier.estado == ESTADO_SINCRONIZADO  # unchanged, no write happened


class TestProxyNotAttemptedIsNotAmbiguous:
    """End-to-end over the REAL client classifier (not a hand-written
    verdict), because the bug lived exactly in the seam between them.

    When `ml-webhook` answers 502 with `{"pxq_write": "not_attempted"}` it
    is stating that its own pre-write read failed and NOTHING reached ML.
    Classifying that by status alone made it ambiguous, and an ambiguous
    write here is not just a blocked retry: it marks every tier
    `desconocido` and hands an operator a reconciliation for a write that
    provably never happened."""

    def _patch_transport(self, monkeypatch, response: httpx.Response) -> None:
        transport = httpx.MockTransport(lambda request: response)
        original_init = httpx.AsyncClient.__init__

        def patched_init(self, *args, **kwargs):
            kwargs["transport"] = transport
            original_init(self, *args, **kwargs)

        monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

    def test_502_not_attempted_rejects_without_marking_desconocido(
        self, db, publicacion, pxq_user, synced_tier, monkeypatch
    ) -> None:
        # Pending change so an array is actually built and POSTed.
        synced_tier.precio_unitario = Decimal("999.00")
        synced_tier.estado = ESTADO_LISTO
        db.flush()

        monkeypatch.setattr(write_service.settings, "PXQ_WRITE_ENABLED", True)
        self._patch_transport(monkeypatch, httpx.Response(502, json={"pxq_write": "not_attempted"}))
        patcher, mock_client = _mock_client(live_prices=[{"id": "ML1", "quantity": 10, "amount": 500.0}])
        # The real POST method, so the real classifier decides -- mocking the
        # outcome dict here would only re-test the branch, never the seam.
        mock_client.post_pxq_prices = MLWebhookClient().post_pxq_prices
        try:
            outcome = write_service.sync_pxq_tiers(db, pxq_user, publicacion.mla)
        finally:
            patcher.stop()

        assert outcome["synced"] is False
        assert outcome["status"] == "rejected_by_proxy"
        assert outcome["status_code"] == 502
        db.refresh(synced_tier)
        assert synced_tier.estado == ESTADO_LISTO  # NOT marked desconocido
        assert synced_tier.precio_sincronizado == Decimal("500.00")  # snapshot untouched


class TestUnconfirmedIsNotSuccess:
    """`submitted_unconfirmed` means the POST left and the confirmation re-read
    failed: the mirror is `desconocido`, the snapshot did NOT advance, and the
    live state is genuinely unknown.

    Reporting `synced: True` for that contradicts the rule the whole service
    exists to hold, and it reaches the UI as a plain 200 — PR 4 would paint an
    unknown write as a finished one."""

    def test_unconfirmed_outcome_is_not_reported_as_synced(self) -> None:
        from app.services.ml_pxq_write_service import _unconfirmed_outcome

        outcome = _unconfirmed_outcome()

        assert outcome["status"] == "submitted_unconfirmed"
        assert outcome["synced"] is False


def test_an_unparseable_live_read_is_rejected_not_a_500() -> None:
    """The write path already has `rejected_read_unavailable` for a live read
    it cannot trust. A malformed payload is that same situation — refusing to
    write is right, raising a 500 is not, and the read endpoint was already
    fixed to degrade while this one still blew up."""
    from app.services.ml_pxq_write_service import _live_tiers_from_raw

    assert _live_tiers_from_raw([{"quantity": 10, "amount": "500.00"}]) is None
    assert _live_tiers_from_raw(["nonsense"]) is None
    assert _live_tiers_from_raw([{"id": 1, "quantity": 10, "amount": "500.00"}]) is not None


def test_a_non_numeric_amount_is_an_unavailable_read_not_a_500() -> None:
    from app.services.ml_pxq_write_service import _live_tiers_from_raw

    assert _live_tiers_from_raw([{"id": 1, "quantity": 10, "amount": "N/A"}]) is None


def test_an_unreadable_eligibility_check_is_not_reported_as_ineligible(monkeypatch) -> None:
    """A proxy that could not be read and a seller who genuinely is not
    enrolled produced the same answer: "not eligible for PxQ". One is a
    permanent fact about the account, the other is a transient outage — and
    telling someone the first when the second is true sends them to support
    for a problem that does not exist.

    Refusing to write is right either way; the reason must be honest."""
    from app.services import ml_pxq_write_service

    async def _unreadable(item_id):
        return None

    monkeypatch.setattr(ml_pxq_write_service.settings, "PXQ_WRITE_ENABLED", True)
    monkeypatch.setattr(ml_pxq_write_service.ml_webhook_client, "get_pxq_eligibility", _unreadable)
    monkeypatch.setattr(ml_pxq_write_service.PermisosService, "tiene_permiso", lambda self, usuario, codigo: True)

    outcome = ml_pxq_write_service.sync_pxq_tiers(db=None, item_id="MLA1", usuario=object())

    assert outcome["synced"] is False
    assert outcome["status"] == "rejected_eligibility_unknown"


class TestBehaviourNotSourceText:
    """These three used to assert on `inspect.getsource()` — that a string
    appeared somewhere in the function body. That proves the code was typed,
    not that it runs: rename a variable and the test breaks for the wrong
    reason; move the call behind a branch that never executes and it still
    passes. The mock harness can drive the real sync, so they do."""

    def test_an_unconfirmable_clear_marks_the_rows_desconocido(self, db, publicacion, pxq_user, monkeypatch) -> None:
        tier = MlPxqTier(
            publicacion_ml_id=publicacion.id,
            item_id=publicacion.mla,
            cantidad_minima=10,
            precio_unitario=Decimal("500.00"),
            costo_envio_total=Decimal("50.00"),
            ml_price_id="ML1",
            cantidad_sincronizada=10,
            precio_sincronizado=Decimal("500.00"),
            estado=ESTADO_SINCRONIZADO,
            usuario_id=pxq_user.id,
        )
        db.add(tier)
        db.flush()
        db.delete(tier)
        db.flush()

        monkeypatch.setattr(write_service.settings, "PXQ_WRITE_ENABLED", True)
        # The clear is sent, but the re-read still shows a tier: unverified.
        patcher, mock_client = _mock_client(live_prices=[{"id": "ML1", "quantity": 10, "amount": 500.0}])
        try:
            outcome = write_service.sync_pxq_tiers(db, pxq_user, publicacion.mla, allow_clear=True)
        finally:
            patcher.stop()

        assert outcome["synced"] is False
        assert outcome["status"] == "submitted_unconfirmed"

    def test_a_created_tier_does_not_adopt_an_untracked_live_id(self, db, publicacion, pxq_user, monkeypatch) -> None:
        """The untracked tier is listed FIRST in the confirmation and carries
        identical values. Without the untracked ids reaching the matcher, the
        created row adopts it — and the next sync modifies or deletes a tier
        that was never ours."""
        created = MlPxqTier(
            publicacion_ml_id=publicacion.id,
            item_id=publicacion.mla,
            cantidad_minima=10,
            precio_unitario=Decimal("500.00"),
            costo_envio_total=Decimal("50.00"),
            ml_price_id=None,
            estado=ESTADO_LISTO,
            usuario_id=pxq_user.id,
        )
        db.add(created)
        db.flush()

        monkeypatch.setattr(write_service.settings, "PXQ_WRITE_ENABLED", True)
        patcher, mock_client = _mock_client(
            live_prices=[{"id": "THEIRS", "quantity": 10, "amount": 500.0}],
        )
        mock_client.get_pxq_prices = AsyncMock(
            side_effect=[
                # live read: the untracked tier only
                [{"id": "THEIRS", "quantity": 10, "amount": 500.0}],
                # confirmation: untracked first, ours second, identical values
                [
                    {"id": "THEIRS", "quantity": 10, "amount": 500.0},
                    {"id": "OURS", "quantity": 10, "amount": 500.0},
                ],
            ]
        )
        try:
            outcome = write_service.sync_pxq_tiers(db, pxq_user, publicacion.mla)
        finally:
            patcher.stop()

        assert outcome["synced"] is True
        assert created.ml_price_id == "OURS"


class TestTheEmittedArrayIsOrdered:
    """The array handed to `post_pxq_prices` is POSTed under ARRAY-REPLACE
    semantics: it IS the entire price ladder MercadoLibre will hold afterwards.
    It was built off a `db.query(...).all()` with no `ORDER BY`, so its order
    was whatever plan the database happened to choose -- meaning the same
    mirror could produce two different payloads on two runs, on the one call in
    this feature that cannot be undone. It is also the likely reason ML hands
    the tiers BACK unordered: we send them that way.

    Rows are inserted 5, 10, 2 on purpose. SQLite scans in rowid order, so an
    ascending INSERT would pass with no `ORDER BY` at all and prove nothing.
    """

    def test_emitted_array_is_ascending_by_quantity(self, db, publicacion, pxq_user, monkeypatch) -> None:
        # Never-synced rows, so every one of them is a create and the emitted
        # array is exactly the mirror in mirror order -- no keeps or untracked
        # entries to muddy which order is being observed.
        for cantidad in (5, 10, 2):
            db.add(
                MlPxqTier(
                    publicacion_ml_id=publicacion.id,
                    item_id=publicacion.mla,
                    cantidad_minima=cantidad,
                    precio_unitario=Decimal("500.00"),
                    costo_envio_total=Decimal("50.00"),
                    ml_price_id=None,
                    estado=ESTADO_LISTO,
                    usuario_id=pxq_user.id,
                )
            )
        db.flush()

        monkeypatch.setattr(write_service.settings, "PXQ_WRITE_ENABLED", True)
        patcher, mock_client = _mock_client()
        mock_client.get_pxq_prices = AsyncMock(
            side_effect=[
                # live read: ML holds nothing yet
                [],
                # confirmation re-read: the three creates came back
                [
                    {"id": "ML2", "quantity": 2, "amount": 500.0},
                    {"id": "ML5", "quantity": 5, "amount": 500.0},
                    {"id": "ML10", "quantity": 10, "amount": 500.0},
                ],
            ]
        )
        try:
            outcome = write_service.sync_pxq_tiers(db, pxq_user, publicacion.mla)
        finally:
            patcher.stop()

        assert outcome["synced"] is True
        posted_array = mock_client.post_pxq_prices.await_args.args[1]
        assert [entry["quantity"] for entry in posted_array] == [2, 5, 10]

    def test_publicacion_ml_id_is_read_off_a_defined_row_not_an_arbitrary_one(
        self, db, publicacion, pxq_user, monkeypatch
    ) -> None:
        """`priceable_rows[0].publicacion_ml_id` is a POSITIONAL read. It is
        harmless in itself -- every row for one `item_id` shares a publication
        -- but resting it on an undefined order means the log line it feeds is
        reproducible only by luck. Ordering the query makes index 0 mean
        something: the lowest quantity."""
        for cantidad in (5, 10, 2):
            db.add(
                MlPxqTier(
                    publicacion_ml_id=publicacion.id,
                    item_id=publicacion.mla,
                    cantidad_minima=cantidad,
                    precio_unitario=Decimal("500.00"),
                    costo_envio_total=Decimal("50.00"),
                    ml_price_id=None,
                    estado=ESTADO_LISTO,
                    usuario_id=pxq_user.id,
                )
            )
        db.flush()

        captured: list = []
        monkeypatch.setattr(write_service.settings, "PXQ_WRITE_ENABLED", True)
        monkeypatch.setattr(
            write_service,
            "_desired_tiers_from_mirror",
            lambda rows, markup_map, **kwargs: (captured.append([row.cantidad_minima for row in rows]), [])[1],
        )
        patcher, _mock = _mock_client()
        try:
            write_service.sync_pxq_tiers(db, pxq_user, publicacion.mla)
        finally:
            patcher.stop()

        assert captured == [[2, 5, 10]]


class TestClassificationHappensBeforeConfirmation:
    """D5: `sync_pxq_tiers` must classify keep/create/modify from the PRE-POST
    shape of each row. Once `remap_and_confirm` has run, every surviving row
    looks like a keep (its snapshot now equals its own values), so the
    classification has to be captured strictly BEFORE that call -- this test
    proves the ORDER, not just that a classification exists."""

    def test_classification_runs_before_remap_and_confirm(self, db, publicacion, pxq_user, monkeypatch) -> None:
        create_tier = MlPxqTier(
            publicacion_ml_id=publicacion.id,
            item_id=publicacion.mla,
            cantidad_minima=10,
            precio_unitario=Decimal("500.00"),
            costo_envio_total=Decimal("50.00"),
            ml_price_id=None,
            estado=ESTADO_LISTO,
            usuario_id=pxq_user.id,
        )
        modify_tier = MlPxqTier(
            publicacion_ml_id=publicacion.id,
            item_id=publicacion.mla,
            cantidad_minima=20,
            precio_unitario=Decimal("999.00"),
            costo_envio_total=Decimal("50.00"),
            ml_price_id="ML20",
            cantidad_sincronizada=20,
            precio_sincronizado=Decimal("800.00"),
            estado=ESTADO_LISTO,
            usuario_id=pxq_user.id,
        )
        keep_tier = MlPxqTier(
            publicacion_ml_id=publicacion.id,
            item_id=publicacion.mla,
            cantidad_minima=30,
            precio_unitario=Decimal("700.00"),
            costo_envio_total=Decimal("50.00"),
            ml_price_id="ML30",
            cantidad_sincronizada=30,
            precio_sincronizado=Decimal("700.00"),
            estado=ESTADO_SINCRONIZADO,
            usuario_id=pxq_user.id,
        )
        db.add_all([create_tier, modify_tier, keep_tier])
        db.flush()

        monkeypatch.setattr(write_service.settings, "PXQ_WRITE_ENABLED", True)
        patcher, mock_client = _mock_client(
            live_prices=[
                {"id": "ML20", "quantity": 20, "amount": 800.0},
                {"id": "ML30", "quantity": 30, "amount": 700.0},
            ],
            post_result={"ok": True, "status_code": 200, "ambiguous": False, "body": None},
        )
        mock_client.get_pxq_prices.side_effect = [
            [
                {"id": "ML20", "quantity": 20, "amount": 800.0},
                {"id": "ML30", "quantity": 30, "amount": 700.0},
            ],
            [
                {"id": "ML10-NEW", "quantity": 10, "amount": 500.0},
                {"id": "ML20-NEW", "quantity": 20, "amount": 999.0},
                {"id": "ML30", "quantity": 30, "amount": 700.0},
            ],
        ]

        call_order: list = []
        real_classify = write_service._classify_tier
        real_remap = write_service.remap_and_confirm

        def spy_classify(row):
            call_order.append(("classify", row.id))
            return real_classify(row)

        def spy_remap(*args, **kwargs):
            call_order.append(("remap", None))
            return real_remap(*args, **kwargs)

        monkeypatch.setattr(write_service, "_classify_tier", spy_classify)
        monkeypatch.setattr(write_service, "remap_and_confirm", spy_remap)
        try:
            outcome = write_service.sync_pxq_tiers(db, pxq_user, publicacion.mla)
        finally:
            patcher.stop()

        assert outcome["synced"] is True
        classify_calls = [c for c in call_order if c[0] == "classify"]
        remap_calls = [c for c in call_order if c[0] == "remap"]
        assert classify_calls, "classification must run"
        assert remap_calls, "remap_and_confirm must run"
        assert max(i for i, c in enumerate(call_order) if c[0] == "classify") < min(
            i for i, c in enumerate(call_order) if c[0] == "remap"
        ), "every classify call must happen BEFORE remap_and_confirm"


class TestOverridePublicarSinMarkup:
    """D4/D7: `publicar_sin_markup` is a PER-REQUEST override, never sticky,
    and there is no per-tier override -- it either lets every unresolved tier
    of this sync through the gate, or it does not."""

    def _make_unresolved_tier(self, db, pxq_user) -> tuple:
        # No comision_fixtures for THIS publication -> markup never resolves,
        # even with costo_envio_total set.
        producto = ProductoERP(item_id=90401, codigo="SKU-PXQ-OVERRIDE", descripcion="Producto override", costo=1000.0)
        db.add(producto)
        db.flush()
        pub = PublicacionML(mla="MLA940001", item_id=producto.item_id, codigo="SKU-PXQ-OVERRIDE", pricelist_id=4)
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
        return pub, tier

    def test_override_unset_excludes_unresolved_tier(self, db, pxq_user, monkeypatch) -> None:
        pub, tier = self._make_unresolved_tier(db, pxq_user)
        monkeypatch.setattr(write_service.settings, "PXQ_WRITE_ENABLED", True)
        patcher, mock_client = _mock_client(live_prices=[])
        try:
            write_service.sync_pxq_tiers(db, pxq_user, pub.mla, publicar_sin_markup=False)
        finally:
            patcher.stop()
        mock_client.post_pxq_prices.assert_not_called()

    def test_override_set_includes_unresolved_tier_subject_to_diff(self, db, pxq_user, monkeypatch) -> None:
        pub, tier = self._make_unresolved_tier(db, pxq_user)
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
            outcome = write_service.sync_pxq_tiers(db, pxq_user, pub.mla, publicar_sin_markup=True)
        finally:
            patcher.stop()
        mock_client.post_pxq_prices.assert_called_once()
        assert outcome["synced"] is True

    def test_override_still_refused_by_divergence(self, db, pxq_user, monkeypatch) -> None:
        pub, tier = self._make_unresolved_tier(db, pxq_user)
        monkeypatch.setattr(write_service.settings, "PXQ_WRITE_ENABLED", True)
        # Live moved since last sync would matter for a modify; here it's a
        # create with an untracked live entry of DIFFERENT shape than what we
        # are about to send is fine (creates never diverge) -- so force a
        # divergence via an existing ml_price_id with no snapshot instead.
        tier.ml_price_id = "GHOST"
        db.flush()
        patcher, mock_client = _mock_client(live_prices=[])
        try:
            outcome = write_service.sync_pxq_tiers(db, pxq_user, pub.mla, publicar_sin_markup=True)
        finally:
            patcher.stop()
        assert outcome["status"] == "divergence"
        mock_client.post_pxq_prices.assert_not_called()

    def test_override_is_per_request_not_sticky(self, db, pxq_user, monkeypatch) -> None:
        pub, tier = self._make_unresolved_tier(db, pxq_user)
        monkeypatch.setattr(write_service.settings, "PXQ_WRITE_ENABLED", True)
        patcher, mock_client = _mock_client(live_prices=[])
        try:
            write_service.sync_pxq_tiers(db, pxq_user, pub.mla, publicar_sin_markup=True)
            mock_client.post_pxq_prices.reset_mock()
            mock_client.get_pxq_prices = AsyncMock(return_value=[])
            write_service.sync_pxq_tiers(db, pxq_user, pub.mla)
        finally:
            patcher.stop()
        mock_client.post_pxq_prices.assert_not_called()


class TestAuditTrailForPublishedPrices:
    """D6/corrección 3: exactly one `Auditoria` row per create/modify tier
    CONFIRMED by ML (`estado == ESTADO_SINCRONIZADO` post-confirm). Keeps and
    unconfirmed rows never get one."""

    def test_confirmed_creates_and_modifies_get_one_audit_row_each(
        self, db, publicacion, pxq_user, monkeypatch
    ) -> None:
        from app.models.auditoria import Auditoria, TipoAccion

        create_tier = MlPxqTier(
            publicacion_ml_id=publicacion.id,
            item_id=publicacion.mla,
            cantidad_minima=10,
            precio_unitario=Decimal("500.00"),
            costo_envio_total=Decimal("50.00"),
            ml_price_id=None,
            estado=ESTADO_LISTO,
            usuario_id=pxq_user.id,
        )
        modify_tier = MlPxqTier(
            publicacion_ml_id=publicacion.id,
            item_id=publicacion.mla,
            cantidad_minima=20,
            precio_unitario=Decimal("999.00"),
            costo_envio_total=Decimal("50.00"),
            ml_price_id="ML20",
            cantidad_sincronizada=20,
            precio_sincronizado=Decimal("800.00"),
            estado=ESTADO_LISTO,
            usuario_id=pxq_user.id,
        )
        keep_tier = MlPxqTier(
            publicacion_ml_id=publicacion.id,
            item_id=publicacion.mla,
            cantidad_minima=30,
            precio_unitario=Decimal("700.00"),
            costo_envio_total=Decimal("50.00"),
            ml_price_id="ML30",
            cantidad_sincronizada=30,
            precio_sincronizado=Decimal("700.00"),
            estado=ESTADO_SINCRONIZADO,
            usuario_id=pxq_user.id,
        )
        db.add_all([create_tier, modify_tier, keep_tier])
        db.flush()

        monkeypatch.setattr(write_service.settings, "PXQ_WRITE_ENABLED", True)
        patcher, mock_client = _mock_client(
            live_prices=[
                {"id": "ML20", "quantity": 20, "amount": 800.0},
                {"id": "ML30", "quantity": 30, "amount": 700.0},
            ],
            post_result={"ok": True, "status_code": 200, "ambiguous": False, "body": None},
        )
        mock_client.get_pxq_prices.side_effect = [
            [
                {"id": "ML20", "quantity": 20, "amount": 800.0},
                {"id": "ML30", "quantity": 30, "amount": 700.0},
            ],
            [
                {"id": "ML10-NEW", "quantity": 10, "amount": 500.0},
                {"id": "ML20-NEW", "quantity": 20, "amount": 999.0},
                {"id": "ML30", "quantity": 30, "amount": 700.0},
            ],
        ]
        try:
            outcome = write_service.sync_pxq_tiers(db, pxq_user, publicacion.mla)
        finally:
            patcher.stop()

        assert outcome["synced"] is True
        rows = db.query(Auditoria).filter(Auditoria.tipo_accion == TipoAccion.PXQ_PRECIO_PUBLICADO).all()
        assert len(rows) == 2
        acciones = sorted(r.valores_nuevos["accion"] for r in rows)
        assert acciones == ["create", "modify"]
        for r in rows:
            assert r.item_id == publicacion.item_id  # ERP int, never the MLA
            assert r.valores_nuevos["mla"] == publicacion.mla
            assert r.valores_nuevos["override_used"] is False
            assert "markup" in r.valores_nuevos
            assert "limpio" in r.valores_nuevos
            assert "comision_total" in r.valores_nuevos

    def test_unconfirmed_create_gets_zero_audit_rows(self, db, publicacion, pxq_user, monkeypatch) -> None:
        from app.models.auditoria import Auditoria, TipoAccion

        create_tier = MlPxqTier(
            publicacion_ml_id=publicacion.id,
            item_id=publicacion.mla,
            cantidad_minima=10,
            precio_unitario=Decimal("500.00"),
            costo_envio_total=Decimal("50.00"),
            ml_price_id=None,
            estado=ESTADO_LISTO,
            usuario_id=pxq_user.id,
        )
        db.add(create_tier)
        db.flush()

        monkeypatch.setattr(write_service.settings, "PXQ_WRITE_ENABLED", True)
        patcher, mock_client = _mock_client(
            live_prices=[],
            post_result={"ok": True, "status_code": 200, "ambiguous": False, "body": None},
        )
        # Confirmation re-read comes back with NOTHING matching -> unconfirmed.
        mock_client.get_pxq_prices.side_effect = [[], []]
        try:
            outcome = write_service.sync_pxq_tiers(db, pxq_user, publicacion.mla)
        finally:
            patcher.stop()

        assert outcome["synced"] is False
        rows = db.query(Auditoria).filter(Auditoria.tipo_accion == TipoAccion.PXQ_PRECIO_PUBLICADO).all()
        assert rows == []

    def test_keeps_are_never_audited(self, db, publicacion, pxq_user, synced_tier, monkeypatch) -> None:
        from app.models.auditoria import Auditoria, TipoAccion

        monkeypatch.setattr(write_service.settings, "PXQ_WRITE_ENABLED", True)
        patcher, mock_client = _mock_client(
            live_prices=[{"id": "ML1", "quantity": 10, "amount": 500.0}],
            post_result={"ok": True, "status_code": 200, "ambiguous": False, "body": None},
        )
        mock_client.get_pxq_prices.side_effect = [
            [{"id": "ML1", "quantity": 10, "amount": 500.0}],
            [{"id": "ML1", "quantity": 10, "amount": 500.0}],
        ]
        try:
            outcome = write_service.sync_pxq_tiers(db, pxq_user, publicacion.mla)
        finally:
            patcher.stop()
        assert outcome["synced"] is True
        rows = db.query(Auditoria).filter(Auditoria.tipo_accion == TipoAccion.PXQ_PRECIO_PUBLICADO).all()
        assert rows == []

    def test_override_published_tier_has_no_markup_figure_but_marks_override_used(
        self, db, pxq_user, monkeypatch
    ) -> None:
        from app.models.auditoria import Auditoria, TipoAccion

        producto = ProductoERP(
            item_id=90402, codigo="SKU-PXQ-OVERRIDE-AUDIT", descripcion="Producto override audit", costo=1000.0
        )
        db.add(producto)
        db.flush()
        pub = PublicacionML(mla="MLA940002", item_id=producto.item_id, codigo="SKU-PXQ-OVERRIDE-AUDIT", pricelist_id=4)
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
            outcome = write_service.sync_pxq_tiers(db, pxq_user, pub.mla, publicar_sin_markup=True)
        finally:
            patcher.stop()

        assert outcome["synced"] is True
        rows = db.query(Auditoria).filter(Auditoria.tipo_accion == TipoAccion.PXQ_PRECIO_PUBLICADO).all()
        assert len(rows) == 1
        payload = rows[0].valores_nuevos
        assert payload["override_used"] is True
        assert "markup" not in payload
        assert "limpio" not in payload
        assert "comision_total" not in payload


class TestAuditOrderAndFailureIsolation:
    """D6: the business commit is a separate, EARLIER unit of work from the
    audit write. A failure in `registrar_auditoria` must never roll back the
    already-committed snapshot and must never degrade `synced: true`."""

    def test_business_commit_happens_before_any_audit_write(self, db, publicacion, pxq_user, monkeypatch) -> None:
        create_tier = MlPxqTier(
            publicacion_ml_id=publicacion.id,
            item_id=publicacion.mla,
            cantidad_minima=10,
            precio_unitario=Decimal("500.00"),
            costo_envio_total=Decimal("50.00"),
            ml_price_id=None,
            estado=ESTADO_LISTO,
            usuario_id=pxq_user.id,
        )
        db.add(create_tier)
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

        call_order: list = []
        commit_spy = MagicMock(wraps=db.commit)
        real_registrar = write_service.registrar_auditoria

        def spy_registrar(db_arg, **kwargs):
            call_order.append("audit")
            return real_registrar(db_arg, **kwargs)

        def spy_commit():
            call_order.append("commit")
            return commit_spy()

        monkeypatch.setattr(write_service, "registrar_auditoria", spy_registrar)
        monkeypatch.setattr(db, "commit", spy_commit)
        try:
            write_service.sync_pxq_tiers(db, pxq_user, publicacion.mla)
        finally:
            patcher.stop()

        assert "commit" in call_order and "audit" in call_order
        assert call_order.index("commit") < call_order.index("audit")

    def test_audit_failure_does_not_revert_snapshot_or_degrade_synced(
        self, db, publicacion, pxq_user, monkeypatch
    ) -> None:
        from sqlalchemy.exc import SQLAlchemyError

        create_tier = MlPxqTier(
            publicacion_ml_id=publicacion.id,
            item_id=publicacion.mla,
            cantidad_minima=10,
            precio_unitario=Decimal("500.00"),
            costo_envio_total=Decimal("50.00"),
            ml_price_id=None,
            estado=ESTADO_LISTO,
            usuario_id=pxq_user.id,
        )
        db.add(create_tier)
        db.flush()
        tier_id = create_tier.id

        monkeypatch.setattr(write_service.settings, "PXQ_WRITE_ENABLED", True)
        patcher, mock_client = _mock_client(
            live_prices=[],
            post_result={"ok": True, "status_code": 200, "ambiguous": False, "body": None},
        )
        mock_client.get_pxq_prices.side_effect = [
            [],
            [{"id": "ML10", "quantity": 10, "amount": 500.0}],
        ]

        def failing_registrar(*args, **kwargs):
            raise SQLAlchemyError("boom")

        monkeypatch.setattr(write_service, "registrar_auditoria", failing_registrar)
        try:
            outcome = write_service.sync_pxq_tiers(db, pxq_user, publicacion.mla)
        finally:
            patcher.stop()

        assert outcome["synced"] is True
        assert outcome["status"] == "sincronizado"
        assert outcome.get("audit_warning")
        refreshed = db.get(MlPxqTier, tier_id)
        assert refreshed.estado == ESTADO_SINCRONIZADO
        assert refreshed.ml_price_id == "ML10"


class TestAuditPublicacionLookupFailureIsIsolatedToo:
    """D6 real bug (GGA pre-push finding): the `PublicacionML` lookup used to
    resolve the ERP `item_id` for the audit row ran OUTSIDE the
    `try/except SQLAlchemyError` that protects `registrar_auditoria`. A pool
    exhaustion or dropped connection on THAT query propagated uncaught -- a
    500 after ML already confirmed and the business commit (A) already
    landed, exactly what the except exists to prevent."""

    def test_publicacion_lookup_failure_does_not_revert_snapshot_or_degrade_synced(
        self, db, publicacion, pxq_user, monkeypatch
    ) -> None:
        from sqlalchemy.exc import SQLAlchemyError

        create_tier = MlPxqTier(
            publicacion_ml_id=publicacion.id,
            item_id=publicacion.mla,
            cantidad_minima=10,
            precio_unitario=Decimal("500.00"),
            costo_envio_total=Decimal("50.00"),
            ml_price_id=None,
            estado=ESTADO_LISTO,
            usuario_id=pxq_user.id,
        )
        db.add(create_tier)
        db.flush()
        tier_id = create_tier.id

        monkeypatch.setattr(write_service.settings, "PXQ_WRITE_ENABLED", True)
        patcher, mock_client = _mock_client(
            live_prices=[],
            post_result={"ok": True, "status_code": 200, "ambiguous": False, "body": None},
        )
        mock_client.get_pxq_prices.side_effect = [
            [],
            [{"id": "ML10", "quantity": 10, "amount": 500.0}],
        ]

        # `resolve_pxq_pricing_context` (via `markup_for_tiers`, called EARLY in
        # the gate) also queries `PublicacionML` -- so the failure has to be
        # scoped to the SECOND such query (the audit lookup), not the first,
        # or the sync would refuse before it ever reaches the write path and
        # prove nothing about the bug under test.
        real_query = db.query
        publicacion_query_count = {"n": 0}

        def failing_query(model, *args, **kwargs):
            if model is write_service.PublicacionML:
                publicacion_query_count["n"] += 1
                if publicacion_query_count["n"] >= 2:
                    raise SQLAlchemyError("pool exhausted")
            return real_query(model, *args, **kwargs)

        monkeypatch.setattr(db, "query", failing_query)
        try:
            outcome = write_service.sync_pxq_tiers(db, pxq_user, publicacion.mla)
        finally:
            patcher.stop()

        assert outcome["synced"] is True
        assert outcome["status"] == "sincronizado"
        assert outcome.get("audit_warning")
        # `db.query` is monkeypatched for the whole test, so re-reading via a
        # fresh query would recurse into the same failure -- use `db.get`
        # instead, exactly as the OTHER D6 failure-isolation test does.
        refreshed = db.get(MlPxqTier, tier_id)
        assert refreshed.estado == ESTADO_SINCRONIZADO
        assert refreshed.ml_price_id == "ML10"
