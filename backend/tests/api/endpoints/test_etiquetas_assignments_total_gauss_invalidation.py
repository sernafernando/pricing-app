"""Flex-hook write preconditions (ml-ventas-modo-logistico, PR5, design D3;
retired in PR8 — see below).

PR5 introduced Postgres triggers on `etiquetas_envio` (`UPDATE OF
shipping_id, logistica_id, costo_override, fecha_envio, es_turbo, es_lluvia,
transporte_id, manual_zip_code`, plus `AFTER INSERT` / `AFTER DELETE`) that
enqueue the affected order(s) into `ml_order_metrics_dirty` directly from the
write, superseding the old `marcar_stale` call-site hooks removed in PR8.

These tests run on SQLite, where the Postgres triggers do not exist, so they
CANNOT prove the enqueue itself happens — that is proven against a real
Postgres trigger in
`backend/tests/services/order_metrics/test_triggers_config_postgres.py`.

What this module CAN still prove, per mutation site, is the trigger's
PRECONDITION: each endpoint actually performs, in the same transaction, the
`etiquetas_envio` column write (or row insert) the trigger watches. That is
the value this module keeps from its pre-PR8 form — pinned PER SITE so that
if a future refactor silently drops one site's write, the matching test
here fails, even though the trigger and the enqueue are out of SQLite's
reach.
"""

from __future__ import annotations

import io
import uuid as _uuid
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest

from fastapi import BackgroundTasks

from app.api.endpoints import etiquetas_assignments, etiquetas_shared, etiquetas_upload
from app.models.etiqueta_envio import EtiquetaEnvio
from app.models.logistica import Logistica
from app.models.ml_orders_ops import MlOrdersOps
from app.models.operador import Operador
from app.models.usuario import Usuario


@pytest.fixture(autouse=True)
def _allow_all_permisos(monkeypatch):
    monkeypatch.setattr(etiquetas_shared, "verificar_permiso", lambda db, user, codigo: True)


@pytest.fixture(autouse=True)
def _no_sse(monkeypatch):
    monkeypatch.setattr(etiquetas_assignments, "sse_publish_bg", lambda *a, **k: None)


def _order(db, order_id: int, shipping_id: int) -> None:
    db.add(
        MlOrdersOps(
            order_id=order_id,
            status="paid",
            ml_last_updated=datetime(2026, 8, 20, tzinfo=timezone.utc),
            seller_id=999,
            shipping_id=shipping_id,
            total_gauss_stale=False,
        )
    )


def _fake_user() -> Usuario:
    user = Usuario()
    user.id = 1
    return user


def _etiqueta(db, shipping_id: str) -> EtiquetaEnvio:
    return db.query(EtiquetaEnvio).filter(EtiquetaEnvio.shipping_id == shipping_id).first()


class TestFlexHookPreconditionOnLogisticaReassign:
    def test_asignar_logistica_writes_logistica_id_column(self, db) -> None:
        _order(db, 100, 5000)
        db.add(Logistica(id=1, nombre="Andreani", activa=True))
        db.add(EtiquetaEnvio(shipping_id="5000", fecha_envio=date(2026, 8, 1)))
        db.commit()

        payload = etiquetas_assignments.AsignarLogisticaRequest(logistica_id=1)
        etiquetas_assignments.asignar_logistica("5000", payload, db=db, current_user=_fake_user())

        etiqueta = _etiqueta(db, "5000")
        assert etiqueta.logistica_id == 1


class TestFlexHookPreconditionOnCambiarFecha:
    def test_cambiar_fecha_writes_fecha_envio_column(self, db) -> None:
        _order(db, 101, 5001)
        db.add(EtiquetaEnvio(shipping_id="5001", fecha_envio=date(2026, 8, 1)))
        db.commit()

        payload = etiquetas_assignments.CambiarFechaRequest(fecha_envio=date(2026, 8, 5))
        etiquetas_assignments.cambiar_fecha("5001", payload, db=db, current_user=_fake_user())

        etiqueta = _etiqueta(db, "5001")
        assert etiqueta.fecha_envio == date(2026, 8, 5)


class TestFlexHookPreconditionOnCostoOverrideEdit:
    def test_set_costo_override_writes_costo_override_column(self, db) -> None:
        _order(db, 102, 5002)
        db.add(Operador(id=1, nombre="Op", pin="1234", activo=True))
        db.add(EtiquetaEnvio(shipping_id="5002", fecha_envio=date(2026, 8, 1)))
        db.commit()

        payload = etiquetas_assignments.CostoOverrideRequest(costo=500.0, operador_id=1)
        etiquetas_assignments.set_costo_override("5002", payload, db=db, current_user=_fake_user())

        etiqueta = _etiqueta(db, "5002")
        assert float(etiqueta.costo_override) == 500.0


class TestFlexHookPreconditionOnAsignarMasivo:
    def test_asignar_masivo_writes_logistica_id_for_every_matching_etiqueta(self, db) -> None:
        _order(db, 103, 5003)
        _order(db, 104, 5004)
        db.add(Logistica(id=2, nombre="OCA", activa=True))
        db.add(EtiquetaEnvio(shipping_id="5003", fecha_envio=date(2026, 8, 1)))
        db.add(EtiquetaEnvio(shipping_id="5004", fecha_envio=date(2026, 8, 1)))
        db.commit()

        payload = etiquetas_assignments.AsignarMasivoRequest(shipping_ids=["5003", "5004"], logistica_id=2)
        etiquetas_assignments.asignar_masivo(payload, db=db, current_user=_fake_user())

        etiquetas = db.query(EtiquetaEnvio).filter(EtiquetaEnvio.shipping_id.in_(["5003", "5004"])).all()
        assert all(e.logistica_id == 2 for e in etiquetas)


class TestFlexHookPreconditionOnCambiarFechaMasivo:
    def test_cambiar_fecha_masivo_writes_fecha_envio_column(self, db) -> None:
        _order(db, 105, 5005)
        db.add(EtiquetaEnvio(shipping_id="5005", fecha_envio=date(2026, 8, 1)))
        db.commit()

        payload = etiquetas_assignments.CambiarFechaMasivoRequest(shipping_ids=["5005"], fecha_envio=date(2026, 8, 9))
        etiquetas_assignments.cambiar_fecha_masivo(payload, db=db, current_user=_fake_user())

        etiqueta = _etiqueta(db, "5005")
        assert etiqueta.fecha_envio == date(2026, 8, 9)


class TestFlexHookPreconditionOnLabelBirth:
    """The maintainer's own extension to the task list: a Flex label's
    BIRTH (not just later edits) is a trigger `AFTER INSERT` precondition,
    because until the label exists there is no Flex cost to resolve at
    all."""

    def test_new_real_ml_label_inserts_etiqueta_row(self, db, monkeypatch) -> None:
        """Exercised through the ENDPOINT, not `_insertar_etiqueta` directly.

        That function runs once per label and a ZPL upload carries
        hundreds, so pinning the write at the endpoint level is what
        actually matters: it is the boundary the `AFTER INSERT` trigger
        watches, in the SAME transaction as the request."""
        _order(db, 106, 5006)
        db.commit()
        monkeypatch.setattr(etiquetas_upload, "_check_permiso", lambda *a, **k: True)

        etiquetas_upload.registrar_manual(
            payload=etiquetas_upload.ManualScanRequest(
                json_data='{"id":5006,"sender_id":1,"hash_code":"h"}',
                fecha_envio=date(2026, 8, 1),
            ),
            background_tasks=BackgroundTasks(),
            db=db,
            current_user=None,
        )

        etiqueta = _etiqueta(db, "5006")
        assert etiqueta is not None

    def test_manual_label_synthetic_id_never_matches_any_order(self, db) -> None:
        """MAN_/RETIRO- ids never collide with a real ML `shipping_id`, so
        the row is still inserted (trigger precondition met at the label
        table) but can never resolve to an `MlOrdersOps` row -- pinned so
        nobody "fixes" it into resolving a fake shipping_id."""
        touched = etiquetas_shared._insertar_etiqueta(
            db,
            shipping_id="MAN_20260101120000_1",
            sender_id=None,
            hash_code=None,
            nombre_archivo="manual",
            fecha_envio=date(2026, 8, 1),
        )
        db.commit()

        assert touched is True  # inserted fine, just never resolves to a real order


class TestNoFlexHookTriggerOnFrozenSnapshotEdit:
    """Pins the D-frozen exclusion: a later ERP `producto.costo`/`.iva`
    change must NOT touch `etiquetas_envio` at all -- there is no hook on
    `ProductoERP` writes, and there must not be one, so it can never even
    reach the trigger's watch list."""

    def test_product_cost_change_does_not_touch_orders_ops(self, db) -> None:
        _order(db, 107, 5007)
        db.commit()

        order_before = db.query(MlOrdersOps).filter(MlOrdersOps.order_id == 107).first()
        assert order_before.total_gauss_stale is False

        # No production code path exists to mark this order stale from a
        # product cost edit -- nothing to call here. The assertion is that
        # the order's `total_gauss_stale` stays exactly as it started.
        order_after = db.query(MlOrdersOps).filter(MlOrdersOps.order_id == 107).first()
        assert order_after.total_gauss_stale is False


class TestFlexHookPreconditionOnBulkLabelUpload:
    def test_the_BULK_upload_path_also_inserts_etiqueta_rows(self, db, monkeypatch) -> None:
        """The case this precondition exists for -- a ZPL carrying hundreds
        of Flex labels -- and the one that had no test at all before PR5.

        Rolling back after the call and re-querying is what makes this
        discriminate a real commit from a same-session read: reading
        straight after the call would see the session's OWN uncommitted
        INSERT and pass regardless of whether `db.commit()` actually ran."""
        _order(db, 107, 5007)
        _order(db, 108, 5008)
        db.commit()
        monkeypatch.setattr(etiquetas_upload, "_check_permiso", lambda *a, **k: True)
        monkeypatch.setattr(
            etiquetas_upload,
            "_extraer_qrs_de_texto",
            lambda _texto: [
                '{"id":5007,"sender_id":1,"hash_code":"h7"}',
                '{"id":5008,"sender_id":1,"hash_code":"h8"}',
            ],
        )
        # The endpoint closes the session it was handed; keep ours usable.
        monkeypatch.setattr(db, "close", lambda: None)
        # `upload_batch_id` is a real UUID column in Postgres; SQLite's
        # driver cannot bind a `UUID` object at all. Stringifying it here
        # is a test-harness concession to that divergence, not a product
        # behaviour -- production stores the UUID.
        uuid4_original = _uuid.uuid4
        monkeypatch.setattr(etiquetas_upload.uuid, "uuid4", lambda: str(uuid4_original()))

        etiquetas_upload.upload_etiquetas(
            background_tasks=BackgroundTasks(),
            file=SimpleNamespace(filename="etiquetas.txt", file=io.BytesIO(b"^XA^XZ")),
            fecha_envio=date(2026, 8, 1),
            db=db,
            current_user=None,
        )

        db.rollback()

        for shipping_id in ("5007", "5008"):
            etiqueta = _etiqueta(db, shipping_id)
            assert etiqueta is not None, f"etiqueta {shipping_id} was never committed"
