"""Unit tests for `tn_publish_service.unpublish_product` (Slice 2 — write
orchestrator, the sole write consumer this slice).

No `@pytest.mark.asyncio` — `unpublish_product` is a plain sync function
that internally bridges the client's coroutine via `resolve_maybe_async`.
Uses an injected fake client (constructor arg `client=`) so no real HTTP is
issued and no `httpx.AsyncClient` patching is needed here.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from app.models.auditoria import Auditoria, TipoAccion
from app.models.tienda_nube_producto import TiendaNubeProducto
from app.models.usuario import AuthProvider, RolUsuario, Usuario
from app.services.tn_publish_service import unpublish_product


class _FakeClient:
    def __init__(self, outcome):
        self._outcome = outcome
        self.calls = []

    async def set_published(self, product_id, published):
        self.calls.append((product_id, published))
        return self._outcome


def _make_user(db) -> Usuario:
    user = Usuario(
        username="tn_pub_test",
        email="tn_pub_test@test.com",
        nombre="Publish Test",
        password_hash="x",
        rol=RolUsuario.VENTAS,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(user)
    db.flush()
    return user


def _make_producto(db, product_id=555, variant_id=1, published=True) -> TiendaNubeProducto:
    producto = TiendaNubeProducto(
        product_id=product_id,
        product_name="Test product",
        variant_id=variant_id,
        variant_sku="SKU-1",
        published=published,
    )
    db.add(producto)
    db.flush()
    return producto


class TestNotFound:
    def test_no_local_rows_returns_rejected_not_found(self, db):
        user = _make_user(db)
        outcome = unpublish_product(db, user, 999999, client=MagicMock())
        assert outcome["status"] == "rejected_not_found"
        assert outcome["submitted"] is False


class TestIdempotentNoOp:
    def test_already_unpublished_skips_the_write(self, db):
        user = _make_user(db)
        _make_producto(db, product_id=555, published=False)
        fake_client = _FakeClient({"ok": True, "status_code": 200, "ambiguous": False, "body": {}})
        outcome = unpublish_product(db, user, 555, client=fake_client)
        assert outcome["status"] == "already_unpublished"
        assert fake_client.calls == []

    def test_multiple_variant_rows_all_unpublished_skips_the_write(self, db):
        user = _make_user(db)
        _make_producto(db, product_id=555, variant_id=1, published=False)
        _make_producto(db, product_id=555, variant_id=2, published=False)
        fake_client = _FakeClient({"ok": True, "status_code": 200, "ambiguous": False, "body": {}})
        outcome = unpublish_product(db, user, 555, client=fake_client)
        assert outcome["status"] == "already_unpublished"
        assert fake_client.calls == []


class TestSuccessfulWrite:
    def test_submitted_updates_local_mirror_for_all_variant_rows(self, db):
        user = _make_user(db)
        _make_producto(db, product_id=555, variant_id=1, published=True)
        _make_producto(db, product_id=555, variant_id=2, published=True)
        fake_client = _FakeClient({"ok": True, "status_code": 200, "ambiguous": False, "body": {}})
        outcome = unpublish_product(db, user, 555, client=fake_client)
        assert outcome["status"] == "submitted"
        assert outcome["submitted"] is True
        rows = db.query(TiendaNubeProducto).filter(TiendaNubeProducto.product_id == 555).all()
        assert all(row.published is False for row in rows)
        assert fake_client.calls == [(555, False)]

    def test_submitted_writes_an_audit_row(self, db):
        user = _make_user(db)
        _make_producto(db, product_id=555, published=True)
        fake_client = _FakeClient({"ok": True, "status_code": 200, "ambiguous": False, "body": {}})
        unpublish_product(db, user, 555, client=fake_client)
        audit_rows = db.query(Auditoria).filter(Auditoria.tipo_accion == TipoAccion.TN_DESPUBLICAR).all()
        assert len(audit_rows) == 1
        # A real write happened, so the structured transition is recorded.
        assert audit_rows[0].valores_nuevos == {"published": False}
        assert audit_rows[0].item_id == 555
        assert audit_rows[0].usuario_id == user.id


class TestRejectedByProxy:
    def test_4xx_is_rejected_by_proxy_local_mirror_unchanged(self, db):
        user = _make_user(db)
        _make_producto(db, product_id=555, published=True)
        fake_client = _FakeClient({"ok": False, "status_code": 404, "ambiguous": False, "body": {"error": "nf"}})
        outcome = unpublish_product(db, user, 555, client=fake_client)
        assert outcome["status"] == "rejected_by_proxy"
        assert outcome["submitted"] is False
        # TN's rejection body is a dict; `detail` must be serialized to a
        # string so the endpoint's `Optional[str]` response model never 500s.
        assert isinstance(outcome["detail"], str)
        assert "nf" in outcome["detail"]
        row = db.query(TiendaNubeProducto).filter(TiendaNubeProducto.product_id == 555).first()
        assert row.published is True

    def test_rejected_audit_row_does_not_claim_a_published_change(self, db):
        user = _make_user(db)
        _make_producto(db, product_id=556, published=True)
        fake_client = _FakeClient({"ok": False, "status_code": 422, "ambiguous": False, "body": {"error": "x"}})
        unpublish_product(db, user, 556, client=fake_client)
        audit = db.query(Auditoria).filter(Auditoria.item_id == 556).one()
        # Nothing was written to TN, so the structured fields must not record
        # a True->False transition that never happened.
        assert audit.valores_nuevos is None
        assert audit.valores_anteriores is None
        assert "rejected_by_proxy" in audit.comentario


class TestAmbiguousOutcome:
    def test_5xx_is_ambiguous_and_never_retried_local_mirror_unchanged(self, db):
        user = _make_user(db)
        _make_producto(db, product_id=555, published=True)
        fake_client = _FakeClient({"ok": False, "status_code": 503, "ambiguous": True, "body": None})
        outcome = unpublish_product(db, user, 555, client=fake_client)
        assert outcome["status"] == "ambiguous"
        assert outcome["submitted"] is False
        # No retry: the fake client was called exactly once.
        assert fake_client.calls == [(555, False)]
        row = db.query(TiendaNubeProducto).filter(TiendaNubeProducto.product_id == 555).first()
        assert row.published is True

    def test_ambiguous_outcome_is_still_audit_logged(self, db):
        user = _make_user(db)
        _make_producto(db, product_id=555, published=True)
        fake_client = _FakeClient({"ok": False, "status_code": None, "ambiguous": True, "body": None})
        unpublish_product(db, user, 555, client=fake_client)
        audit_rows = db.query(Auditoria).filter(Auditoria.tipo_accion == TipoAccion.TN_DESPUBLICAR).all()
        assert len(audit_rows) == 1
