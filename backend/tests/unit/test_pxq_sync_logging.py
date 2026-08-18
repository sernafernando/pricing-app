"""Structured-logging tests for the PxQ sync path (`ml_pxq_write_service.py`,
slice 1 of `pxq-adopt-live`).

Zero behavior change: these tests only assert on `caplog` records. Before
this change, `sync_pxq_tiers` emitted NO log lines anywhere -- the
divergence refusal in particular was completely silent server-side, the
only trace being the 409 the frontend rendered. Reconstructing the root
cause of a production incident (four publications losing their live PxQ
tiers) required multi-session code archaeology as a direct result.

Every test also enforces the lazy-`%s` formatting rule (design "Logging"
section, D14 companion): `record.args` must be truthy on every captured
record. An f-string bakes the message into `record.msg` and leaves
`record.args` empty (`()`), which is falsy -- so this guard fails loudly
the moment someone reaches for an f-string instead of lazy `%s` args.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from app.core.security import get_password_hash
from app.models.comision_versionada import ComisionBase, ComisionVersion
from app.models.ml_pxq_tier import ESTADO_LISTO, ESTADO_SINCRONIZADO, MlPxqTier
from app.models.producto import ProductoERP
from app.models.publicacion_ml import PublicacionML
from app.models.usuario import AuthProvider, RolUsuario, Usuario
from app.services import ml_pxq_write_service as write_service
from app.services.pxq_permissions_backfill import PXQ_ESCRIBIR_CODE


@pytest.fixture()
def pxq_user(db, rol_ventas) -> Usuario:
    user = Usuario(
        username="pxq_log_user",
        email="pxq_log_user@example.com",
        nombre="PxQ Logging User",
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
def producto(db) -> ProductoERP:
    p = ProductoERP(item_id=90301, codigo="SKU-PXQ-LOG", descripcion="Producto PxQ Logging", costo=1000.0)
    db.add(p)
    db.flush()
    return p


@pytest.fixture()
def comision_fixtures(db) -> ComisionVersion:
    """Resolvable commission-base context (D4): the write gate now needs
    `markup_resolved`, which needs both `costo_envio_total` AND this."""
    version = ComisionVersion(nombre="Test PxQ Logging", fecha_desde=date(2000, 1, 1), activo=True)
    db.add(version)
    db.flush()
    db.add(ComisionBase(version_id=version.id, grupo_id=1, comision_base=20.0))
    db.flush()
    return version


@pytest.fixture()
def publicacion(db, producto, comision_fixtures) -> PublicacionML:
    pub = PublicacionML(mla="MLA930001", item_id=producto.item_id, codigo="SKU-PXQ-LOG", pricelist_id=4)
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


def _assert_lazy_formatting(records) -> None:
    """Every captured record must carry non-empty `args` -- proof the
    message was built with lazy `%s` substitution, not an f-string. An
    f-string leaves `record.args` as an empty tuple `()`, which is falsy."""
    assert records, "expected at least one log record to inspect"
    for record in records:
        assert record.args, f"record {record.getMessage()!r} was not lazily formatted (record.args is empty)"


class TestDivergenceRefusalLogging:
    def test_divergence_refusal_logs_warning_with_item_id_and_count(
        self, db, publicacion, pxq_user, synced_tier, monkeypatch, caplog
    ) -> None:
        monkeypatch.setattr(write_service.settings, "PXQ_WRITE_ENABLED", True)
        # Live moved since the last sync (500 -> 470); local mirror unchanged.
        patcher, mock_client = _mock_client(live_prices=[{"id": "ML1", "quantity": 10, "amount": 470.0}])
        try:
            with caplog.at_level(logging.DEBUG, logger="app.services.ml_pxq_write_service"):
                outcome = write_service.sync_pxq_tiers(db, pxq_user, publicacion.mla)
        finally:
            patcher.stop()

        assert outcome["status"] == "divergence"

        warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
        divergence_records = [r for r in warning_records if "divergence" in r.getMessage()]
        assert divergence_records, (
            f"expected a WARNING divergence log line, got: {[r.getMessage() for r in caplog.records]}"
        )

        record = divergence_records[0]
        message = record.getMessage()
        assert publicacion.mla in message
        assert "1" in message  # divergence_count: exactly one divergent tier

        _assert_lazy_formatting(divergence_records)


class TestOutboundPostArrayLogging:
    def test_array_about_to_post_logs_info_with_breakdown(self, db, publicacion, pxq_user, monkeypatch, caplog) -> None:
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
            post_result={"ok": True, "status_code": 200, "ambiguous": False, "body": None},
        )
        mock_client.get_pxq_prices.side_effect = [
            [{"id": "ML1", "quantity": 10, "amount": 500.0}],
            [{"id": "ML1-NEW", "quantity": 10, "amount": 550.0}],
        ]
        try:
            with caplog.at_level(logging.DEBUG, logger="app.services.ml_pxq_write_service"):
                outcome = write_service.sync_pxq_tiers(db, pxq_user, publicacion.mla)
        finally:
            patcher.stop()

        assert outcome["status"] == "sincronizado"

        info_records = [r for r in caplog.records if r.levelno == logging.INFO]
        post_records = [r for r in info_records if "posting array" in r.getMessage()]
        assert post_records, (
            f"expected an INFO 'posting array' log line, got: {[r.getMessage() for r in caplog.records]}"
        )

        message = post_records[0].getMessage()
        assert "entries=1" in message
        # This scenario is a MODIFY: `ml_price_id="ML1"` exists, the snapshot
        # matches live, and only the local price moved (500 -> 550). The
        # emitted entry carries no id -- which is also true of a create -- so
        # the log used to call it `creates=1`. The array cannot answer this;
        # only the diff can.
        assert "keeps=0" in message
        assert "creates=0" in message
        assert "modifies=1" in message
        # The old id "ML1" is omitted from the array, so that live tier does
        # disappear -- array-replace implements a modify as exactly that.
        assert "deletes=1" in message

        _assert_lazy_formatting(post_records)

    def test_a_plain_create_is_not_logged_as_a_modify(self, db, publicacion, pxq_user, monkeypatch, caplog) -> None:
        """The mirror image of the defect: a never-synced tier must not be
        absorbed into the `modifies` bucket now that the bucket exists."""
        new_tier = MlPxqTier(
            publicacion_ml_id=publicacion.id,
            item_id=publicacion.mla,
            cantidad_minima=10,
            precio_unitario=Decimal("550.00"),
            costo_envio_total=Decimal("50.00"),
            ml_price_id=None,
            estado=ESTADO_LISTO,
            usuario_id=pxq_user.id,
        )
        db.add(new_tier)
        db.flush()

        monkeypatch.setattr(write_service.settings, "PXQ_WRITE_ENABLED", True)
        patcher, mock_client = _mock_client()
        mock_client.get_pxq_prices.side_effect = [
            [],
            [{"id": "ML1-NEW", "quantity": 10, "amount": 550.0}],
        ]
        try:
            with caplog.at_level(logging.DEBUG, logger="app.services.ml_pxq_write_service"):
                write_service.sync_pxq_tiers(db, pxq_user, publicacion.mla)
        finally:
            patcher.stop()

        post_records = [r for r in caplog.records if "posting array" in r.getMessage()]
        assert post_records, (
            f"expected an INFO 'posting array' log line, got: {[r.getMessage() for r in caplog.records]}"
        )

        message = post_records[0].getMessage()
        assert "entries=1" in message
        assert "creates=1" in message
        assert "modifies=0" in message
        assert "keeps=0" in message
        assert "deletes=0" in message

        _assert_lazy_formatting(post_records)


class TestUnconfirmedBranchesAreDistinguishable:
    """Two different root causes used to emit the byte-identical message
    `"PxQ sync unconfirmed after re-read"`:

      (a) the confirmation re-read itself FAILED -- we have no view of live at
          all, same class of fact as `live_tiers: null`;
      (b) the re-read SUCCEEDED but at least one row could not be matched in it
          -- we do have a view of live, and it disagrees.

    (a) points at the proxy/ML; (b) points at the write or at the mapping. A
    log that cannot tell them apart sends the next incident down the wrong
    path, which is the whole reason this logging exists.
    """

    def _unconfirmed_messages(self, caplog) -> list:
        return [
            r.getMessage() for r in caplog.records if r.levelno == logging.ERROR and "unconfirmed" in r.getMessage()
        ]

    def test_a_failed_confirmation_reread_and_an_incomplete_one_log_different_messages(
        self, db, publicacion, pxq_user, synced_tier, monkeypatch, caplog
    ) -> None:
        monkeypatch.setattr(write_service.settings, "PXQ_WRITE_ENABLED", True)

        # (a) re-read fails outright.
        patcher, mock_client = _mock_client()
        mock_client.get_pxq_prices.side_effect = [
            [{"id": "ML1", "quantity": 10, "amount": 500.0}],
            None,
        ]
        try:
            with caplog.at_level(logging.DEBUG, logger="app.services.ml_pxq_write_service"):
                outcome_a = write_service.sync_pxq_tiers(db, pxq_user, publicacion.mla)
                messages_a = self._unconfirmed_messages(caplog)
        finally:
            patcher.stop()

        assert outcome_a["status"] == "submitted_unconfirmed"
        assert messages_a, "expected an ERROR log line for the failed confirmation re-read"

        caplog.clear()

        # (b) re-read succeeds but comes back with nothing to match the row on.
        patcher, mock_client = _mock_client()
        mock_client.get_pxq_prices.side_effect = [
            [{"id": "ML1", "quantity": 10, "amount": 500.0}],
            [{"id": "SOMEONE-ELSE", "quantity": 99, "amount": 1.0}],
        ]
        try:
            with caplog.at_level(logging.DEBUG, logger="app.services.ml_pxq_write_service"):
                outcome_b = write_service.sync_pxq_tiers(db, pxq_user, publicacion.mla)
                messages_b = self._unconfirmed_messages(caplog)
        finally:
            patcher.stop()

        assert outcome_b["status"] == "submitted_unconfirmed"
        assert messages_b, "expected an ERROR log line for the incomplete confirmation"

        assert messages_a[0] != messages_b[0], (
            "the failed-re-read and incomplete-confirmation branches must be distinguishable in the log, "
            f"both said: {messages_a[0]!r}"
        )


class TestKillSwitchLogging:
    def test_kill_switch_logs_debug_and_makes_zero_ml_calls(
        self, db, publicacion, pxq_user, monkeypatch, caplog
    ) -> None:
        monkeypatch.setattr(write_service.settings, "PXQ_WRITE_ENABLED", False)
        patcher, mock_client = _mock_client()
        try:
            with caplog.at_level(logging.DEBUG, logger="app.services.ml_pxq_write_service"):
                outcome = write_service.sync_pxq_tiers(db, pxq_user, publicacion.mla)
        finally:
            patcher.stop()

        assert outcome["status"] == "disabled"
        mock_client.get_pxq_eligibility.assert_not_called()
        mock_client.get_pxq_prices.assert_not_called()
        mock_client.post_pxq_prices.assert_not_called()

        debug_records = [r for r in caplog.records if r.levelno == logging.DEBUG]
        skip_records = [r for r in debug_records if "skipped" in r.getMessage()]
        assert skip_records, f"expected a DEBUG kill-switch log line, got: {[r.getMessage() for r in caplog.records]}"
        assert publicacion.mla in skip_records[0].getMessage()

        _assert_lazy_formatting(skip_records)


class TestLazyFormattingAcrossAllOutcomes:
    def test_every_captured_record_uses_lazy_percent_s_args(
        self, db, publicacion, pxq_user, synced_tier, monkeypatch, caplog
    ) -> None:
        """Broader sweep across a full successful sync: every log line the
        service emits along the happy path must carry non-empty `args`."""
        monkeypatch.setattr(write_service.settings, "PXQ_WRITE_ENABLED", True)
        patcher, mock_client = _mock_client(
            live_prices=[{"id": "ML1", "quantity": 10, "amount": 500.0}],
            post_result={"ok": True, "status_code": 200, "ambiguous": False, "body": None},
        )
        try:
            with caplog.at_level(logging.DEBUG, logger="app.services.ml_pxq_write_service"):
                write_service.sync_pxq_tiers(db, pxq_user, publicacion.mla)
        finally:
            patcher.stop()

        _assert_lazy_formatting(caplog.records)
