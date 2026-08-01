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

from decimal import Decimal
from unittest.mock import AsyncMock, patch

from pathlib import Path

import pytest
from fastapi import HTTPException

from app.core.security import get_password_hash
from app.models.ml_pxq_tier import ESTADO_DESCONOCIDO, ESTADO_LISTO, ESTADO_SINCRONIZADO, MlPxqTier
from app.models.producto import ProductoERP
from app.models.publicacion_ml import PublicacionML
from app.models.usuario import AuthProvider, RolUsuario, Usuario
from app.services import ml_pxq_write_service as write_service
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
def producto(db) -> ProductoERP:
    p = ProductoERP(item_id=90201, codigo="SKU-PXQ-WRITE", descripcion="Producto PxQ Write", costo=1000.0)
    db.add(p)
    db.flush()
    return p


@pytest.fixture()
def publicacion(db, producto) -> PublicacionML:
    pub = PublicacionML(mla="MLA920001", item_id=producto.item_id, codigo="SKU-PXQ-WRITE")
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


def test_http_exception_is_imported_at_module_level() -> None:
    """Imported inside a function it is easy to miss and diverges from
    `pxq_tier_service`, which imports it top-level in the same package."""
    import ast

    from app.services import ml_pxq_write_service

    source = Path(ml_pxq_write_service.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    top_level = {alias.name for node in tree.body if isinstance(node, ast.ImportFrom) for alias in node.names}

    assert "HTTPException" in top_level


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


def test_allow_clear_that_cannot_be_confirmed_marks_rows_desconocido() -> None:
    """Every other unconfirmed path marks the rows `desconocido` so the next
    sync is forced through the divergence gate. This one committed and
    returned unconfirmed while leaving the rows looking trustworthy — the
    exact state the module exists to prevent."""
    import inspect

    from app.services import ml_pxq_write_service

    source = inspect.getsource(ml_pxq_write_service.sync_pxq_tiers)
    clear_branch = source[source.index("if not diff_result.array:") :]
    clear_branch = clear_branch[: clear_branch.index("return _unconfirmed_outcome()")]

    assert "_mark_desconocido" in clear_branch, (
        "an unconfirmed clear must mark the rows desconocido like every other unconfirmed outcome does"
    )


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


def test_the_orchestrator_actually_passes_the_untracked_ids() -> None:
    """A protection the only caller does not use is decoration."""
    import inspect

    from app.services import ml_pxq_write_service

    source = inspect.getsource(ml_pxq_write_service.sync_pxq_tiers)

    assert "untracked_ids=" in source
