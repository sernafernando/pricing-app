"""`POST /api/promociones/recompute-precios`: ml-webhook asks pricing to recompute the promo price
columns of the items whose promo mirror it just updated (promo-ml-precio-inmediato T1).

Covers: `ml_ops.ingest` auth (the bridge service user, same as the activity ping), the request
enqueues one row per ITEM (MLAs of one item and repeated requests collapse), unknown MLAs are
reported and skipped, and the request is bounded (max 50 MLAs, MLA format checked).
"""

from __future__ import annotations

from datetime import timedelta
import pytest
from fastapi.testclient import TestClient

from app.core.security import create_access_token
from app.models.permiso import Permiso, RolPermisoBase
from app.models.producto import ProductoERP, TipoMoneda
from app.models.promo_price_recompute_queue import PromoPriceRecomputeQueue
from app.models.publicacion_ml import PublicacionML
from app.models.rol import Rol
from app.models.usuario import AuthProvider, Usuario
from app.services import promo_price_recompute

PATH = "/api/promociones/recompute-precios"

_seq = [0]


def _make_user(db, permiso_codigo: str | None) -> Usuario:
    _seq[0] += 1
    rol = Rol(codigo=f"PROMO_RECOMPUTE_{_seq[0]}", nombre="Rol test", es_sistema=True, orden=910, activo=True)
    db.add(rol)
    db.flush()
    if permiso_codigo:
        permiso = db.query(Permiso).filter(Permiso.codigo == permiso_codigo).first()
        if permiso is None:
            permiso = Permiso(codigo=permiso_codigo, nombre=permiso_codigo, categoria="ml_ops")
            db.add(permiso)
            db.flush()
        db.add(RolPermisoBase(rol_id=rol.id, permiso_id=permiso.id))
        db.flush()
    user = Usuario(
        username=f"promo-recompute-{_seq[0]}",
        nombre="Test",
        password_hash=None,
        rol=None,
        rol_id=rol.id,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(user)
    db.flush()
    return user


def _headers(user: Usuario) -> dict:
    token = create_access_token({"sub": user.username}, timedelta(days=90))
    return {"Authorization": f"Bearer {token}"}


def _make_item(db, item_id: int, *mlas: str) -> None:
    db.add(
        ProductoERP(
            item_id=item_id,
            codigo=f"COD{item_id}",
            descripcion="Producto de prueba",
            subcategoria_id=1,
            costo=1000.0,
            moneda_costo=TipoMoneda.ARS,
            iva=21.0,
        )
    )
    for mla in mlas:
        db.add(PublicacionML(mla=mla, item_id=item_id, pricelist_id=4))
    db.flush()


def _queued(db) -> list[int]:
    return sorted(row.item_id for row in db.query(PromoPriceRecomputeQueue).all())


class TestAuth:
    def test_401_without_token(self, client: TestClient, db):
        resp = client.post(PATH, json={"mlas": ["MLA100"]})
        assert resp.status_code == 401
        assert _queued(db) == []

    def test_403_without_ingest_permission(self, client: TestClient, db):
        _make_item(db, 7001, "MLA7001")
        user = _make_user(db, "promos.escribir")
        resp = client.post(PATH, json={"mlas": ["MLA7001"]}, headers=_headers(user))
        assert resp.status_code == 403
        assert _queued(db) == []


class TestEnqueue:
    def test_202_queues_the_item_of_each_mla(self, client: TestClient, db):
        _make_item(db, 7001, "MLA7001")
        _make_item(db, 7002, "MLA7002")
        bridge = _make_user(db, "ml_ops.ingest")

        resp = client.post(PATH, json={"mlas": ["MLA7001", "MLA7002"]}, headers=_headers(bridge))

        assert resp.status_code == 202
        assert resp.json() == {"accepted": True, "items_queued": 2, "unknown_mlas": []}
        assert _queued(db) == [7001, 7002]

    def test_mlas_of_one_item_and_repeated_requests_collapse_into_one_row(self, client: TestClient, db):
        _make_item(db, 7001, "MLA7001", "MLA7011")
        bridge = _make_user(db, "ml_ops.ingest")

        first = client.post(PATH, json={"mlas": ["MLA7001", "MLA7011", "MLA7001"]}, headers=_headers(bridge))
        second = client.post(PATH, json={"mlas": ["MLA7011"]}, headers=_headers(bridge))

        assert first.json()["items_queued"] == 1
        assert second.status_code == 202
        assert _queued(db) == [7001]

    def test_a_new_request_resets_a_parked_item(self, client: TestClient, db):
        _make_item(db, 7001, "MLA7001")
        db.add(PromoPriceRecomputeQueue(item_id=7001, attempts=promo_price_recompute.MAX_ATTEMPTS, last_error="boom"))
        db.flush()
        bridge = _make_user(db, "ml_ops.ingest")

        resp = client.post(PATH, json={"mlas": ["MLA7001"]}, headers=_headers(bridge))

        assert resp.status_code == 202
        row = db.query(PromoPriceRecomputeQueue).filter_by(item_id=7001).one()
        db.refresh(row)
        assert row.attempts == 0
        assert row.last_error is None

    def test_unknown_mlas_are_reported_and_queue_nothing(self, client: TestClient, db):
        bridge = _make_user(db, "ml_ops.ingest")

        resp = client.post(PATH, json={"mlas": ["MLA9999"]}, headers=_headers(bridge))

        assert resp.status_code == 202
        assert resp.json() == {"accepted": True, "items_queued": 0, "unknown_mlas": ["MLA9999"]}
        assert _queued(db) == []

    def test_a_mixed_request_queues_the_known_and_reports_the_unknown(self, client: TestClient, db):
        _make_item(db, 7001, "MLA7001")
        bridge = _make_user(db, "ml_ops.ingest")

        resp = client.post(PATH, json={"mlas": ["MLA9999", "MLA7001"]}, headers=_headers(bridge))

        assert resp.status_code == 202
        assert resp.json() == {"accepted": True, "items_queued": 1, "unknown_mlas": ["MLA9999"]}
        assert _queued(db) == [7001]


class TestBounds:
    def test_more_than_50_mlas_is_rejected(self, client: TestClient, db):
        bridge = _make_user(db, "ml_ops.ingest")
        mlas = [f"MLA{n}" for n in range(1, 52)]

        resp = client.post(PATH, json={"mlas": mlas}, headers=_headers(bridge))

        assert resp.status_code == 422
        assert _queued(db) == []

    @pytest.mark.parametrize("bad", ["", "MLB123", "MLA", "MLA12;DROP", "mla123"])
    def test_a_malformed_mla_is_rejected(self, client: TestClient, db, bad):
        bridge = _make_user(db, "ml_ops.ingest")

        resp = client.post(PATH, json={"mlas": [bad]}, headers=_headers(bridge))

        assert resp.status_code == 422

    def test_an_unknown_field_is_rejected(self, client: TestClient, db):
        _make_item(db, 7001, "MLA7001")
        bridge = _make_user(db, "ml_ops.ingest")

        resp = client.post(PATH, json={"mlas": ["MLA7001"], "price": 1}, headers=_headers(bridge))

        assert resp.status_code == 422
        assert _queued(db) == []

    def test_an_empty_list_is_rejected(self, client: TestClient, db):
        bridge = _make_user(db, "ml_ops.ingest")

        resp = client.post(PATH, json={"mlas": []}, headers=_headers(bridge))

        assert resp.status_code == 422
