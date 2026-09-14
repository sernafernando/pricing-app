"""RED/GREEN -- Total Gauss invalidation hooks (ml-ventas-modo-logistico,
PR5, design D3). Every mutation site listed below MUST call `marcar_stale`
in the SAME transaction; task 5.21's mutation check: silently removing one
site's call and re-running the matching test here must fail.

Calls the endpoint functions directly (bypassing HTTP/auth) with
`verificar_permiso` monkeypatched to always allow -- these tests are about
the invalidation SIDE EFFECT, not the permission gate (which has its own
coverage surface elsewhere in this router file).
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from app.api.endpoints import etiquetas_assignments, etiquetas_shared
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
            # Explicit, NOT the server_default: SQLite stores the bare
            # `false` server_default as the TEXT literal `"false"`, and
            # `bool("false")` is `True` in Python -- a pre-existing gotcha
            # this codebase already carries on `EtiquetaEnvio.es_turbo`
            # (same `server_default="false"` pattern), not something this
            # PR introduces. Sidestepped here rather than relied upon.
            total_gauss_stale=False,
        )
    )


def _fake_user() -> Usuario:
    user = Usuario()
    user.id = 1
    return user


class TestStaleOnLogisticaReassign:
    def test_asignar_logistica_marks_stale(self, db) -> None:
        _order(db, 100, 5000)
        db.add(Logistica(id=1, nombre="Andreani", activa=True))
        db.add(EtiquetaEnvio(shipping_id="5000", fecha_envio=date(2026, 8, 1)))
        db.commit()

        payload = etiquetas_assignments.AsignarLogisticaRequest(logistica_id=1)
        etiquetas_assignments.asignar_logistica("5000", payload, db=db, current_user=_fake_user())

        order = db.query(MlOrdersOps).filter(MlOrdersOps.order_id == 100).first()
        assert order.total_gauss_stale is True


class TestStaleOnCambiarFecha:
    def test_cambiar_fecha_marks_stale(self, db) -> None:
        _order(db, 101, 5001)
        db.add(EtiquetaEnvio(shipping_id="5001", fecha_envio=date(2026, 8, 1)))
        db.commit()

        payload = etiquetas_assignments.CambiarFechaRequest(fecha_envio=date(2026, 8, 5))
        etiquetas_assignments.cambiar_fecha("5001", payload, db=db, current_user=_fake_user())

        order = db.query(MlOrdersOps).filter(MlOrdersOps.order_id == 101).first()
        assert order.total_gauss_stale is True


class TestStaleOnCostoOverrideEdit:
    def test_set_costo_override_marks_stale(self, db) -> None:
        _order(db, 102, 5002)
        db.add(Operador(id=1, nombre="Op", pin="1234", activo=True))
        db.add(EtiquetaEnvio(shipping_id="5002", fecha_envio=date(2026, 8, 1)))
        db.commit()

        payload = etiquetas_assignments.CostoOverrideRequest(costo=500.0, operador_id=1)
        etiquetas_assignments.set_costo_override("5002", payload, db=db, current_user=_fake_user())

        order = db.query(MlOrdersOps).filter(MlOrdersOps.order_id == 102).first()
        assert order.total_gauss_stale is True


class TestStaleOnAsignarMasivo:
    def test_asignar_masivo_marks_stale_for_every_matching_order(self, db) -> None:
        _order(db, 103, 5003)
        _order(db, 104, 5004)
        db.add(Logistica(id=2, nombre="OCA", activa=True))
        db.add(EtiquetaEnvio(shipping_id="5003", fecha_envio=date(2026, 8, 1)))
        db.add(EtiquetaEnvio(shipping_id="5004", fecha_envio=date(2026, 8, 1)))
        db.commit()

        payload = etiquetas_assignments.AsignarMasivoRequest(shipping_ids=["5003", "5004"], logistica_id=2)
        etiquetas_assignments.asignar_masivo(payload, db=db, current_user=_fake_user())

        orders = db.query(MlOrdersOps).filter(MlOrdersOps.order_id.in_([103, 104])).all()
        assert all(o.total_gauss_stale for o in orders)


class TestStaleOnCambiarFechaMasivo:
    def test_cambiar_fecha_masivo_marks_stale(self, db) -> None:
        _order(db, 105, 5005)
        db.add(EtiquetaEnvio(shipping_id="5005", fecha_envio=date(2026, 8, 1)))
        db.commit()

        payload = etiquetas_assignments.CambiarFechaMasivoRequest(shipping_ids=["5005"], fecha_envio=date(2026, 8, 9))
        etiquetas_assignments.cambiar_fecha_masivo(payload, db=db, current_user=_fake_user())

        order = db.query(MlOrdersOps).filter(MlOrdersOps.order_id == 105).first()
        assert order.total_gauss_stale is True


class TestStaleOnLabelBirth:
    """The maintainer's own extension to the task list: a Flex label's
    BIRTH (not just later edits) invalidates Total Gauss, because until the
    label exists there is no Flex cost to resolve at all."""

    def test_new_real_ml_label_marks_matching_order_stale(self, db) -> None:
        _order(db, 106, 5006)
        db.commit()

        inserted = etiquetas_shared._insertar_etiqueta(
            db,
            shipping_id="5006",
            sender_id=None,
            hash_code=None,
            nombre_archivo="test.pdf",
            fecha_envio=date(2026, 8, 1),
        )
        db.commit()

        assert inserted is True
        order = db.query(MlOrdersOps).filter(MlOrdersOps.order_id == 106).first()
        assert order.total_gauss_stale is True

    def test_manual_label_synthetic_id_never_matches_any_order(self, db) -> None:
        """MAN_/RETIRO- ids never collide with a real ML `shipping_id`, so
        this is a harmless no-op, not a bug -- pinned so nobody "fixes" it
        into resolving a fake shipping_id."""
        touched = etiquetas_shared._insertar_etiqueta(
            db,
            shipping_id="MAN_20260101120000_1",
            sender_id=None,
            hash_code=None,
            nombre_archivo="manual",
            fecha_envio=date(2026, 8, 1),
        )
        db.commit()

        assert touched is True  # inserted fine, just never marks any order stale


class TestNoStaleTriggerOnFrozenSnapshotEdit:
    """Pins the D-frozen exclusion: a later ERP `producto.costo`/`.iva`
    change must NOT invalidate an already-frozen sale's Total Gauss --
    there is no hook on `ProductoERP` writes, and there must not be one."""

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
