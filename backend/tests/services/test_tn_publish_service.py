"""Unit tests for `tn_publish_service.unpublish_product` (Slice 2 — write
orchestrator, the sole write consumer this slice).

No `@pytest.mark.asyncio` — `unpublish_product` is a plain sync function
that internally bridges the client's coroutine via `resolve_maybe_async`.
Uses an injected fake client (constructor arg `client=`) so no real HTTP is
issued and no `httpx.AsyncClient` patching is needed here.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from app.models.auditoria import Auditoria, TipoAccion
from app.models.tienda_nube_producto import TiendaNubeProducto
from app.models.tn_publish_override import TnPublishOverride
from app.models.usuario import AuthProvider, RolUsuario, Usuario
from app.services.tienda_nube_product_client import TnProductLookupError, TnRateLimited
from app.services.tn_publish_service import (
    InvalidPublishPriceError,
    _validate_publish_price,
    publish_product,
    sanitize_description_html,
    unpublish_product,
)


class _FakeClient:
    def __init__(self, outcome):
        self._outcome = outcome
        self.calls = []

    async def set_published(self, product_id, published):
        self.calls.append((product_id, published))
        # Same convention as `_FakePublishClient.create_product`: an
        # Exception instance is raised instead of returned — simulates
        # `TnRateLimited` on a 429.
        if isinstance(self._outcome, Exception):
            raise self._outcome
        return self._outcome


class _FakePublishClient:
    """Fake client for `publish_product` — supports `create_product`,
    `add_product_image`, and `get_product_by_sku` independently so a test
    can simulate e.g. the image step failing while creation succeeded, or a
    live pre-check/read-back returning a specific result or raising.

    `get_by_sku_results`, if given, is a queue popped in call order (the
    orchestrator may call `get_product_by_sku` up to twice: once as the live
    pre-check, and again as a read-back after an ambiguous create). An entry
    that IS an `Exception` instance is raised instead of returned — this
    simulates `TnProductLookupError`. Defaults to `None` (confirmed absent)
    for every call, so existing tests that don't care about the live
    pre-check/read-back are unaffected."""

    def __init__(self, create_outcome, image_outcome=None, get_by_sku_results=None, image_outcomes_by_src=None):
        self._create_outcome = create_outcome
        self._image_outcome = image_outcome or {"ok": True, "status_code": 201, "ambiguous": False, "body": {}}
        # Per-src override queue (used to simulate ONE src rate-limited among
        # several reachable srcs) — falls back to `_image_outcome` for any
        # src not present here.
        self._image_outcomes_by_src = image_outcomes_by_src or {}
        self._get_by_sku_results = list(get_by_sku_results) if get_by_sku_results is not None else None
        self.create_calls = []
        self.image_calls = []
        self.get_by_sku_calls = []

    async def create_product(self, payload):
        self.create_calls.append(payload)
        # Same convention as `get_by_sku_results`: an Exception instance is
        # raised instead of returned — simulates `TnRateLimited` on a 429.
        if isinstance(self._create_outcome, Exception):
            raise self._create_outcome
        return self._create_outcome

    async def add_product_image(self, product_id, src):
        self.image_calls.append((product_id, src))
        outcome = self._image_outcomes_by_src.get(src, self._image_outcome)
        # Same convention as `create_product`: an Exception instance is
        # raised instead of returned — simulates `TnRateLimited` on a 429.
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    async def get_product_by_sku(self, sku):
        self.get_by_sku_calls.append(sku)
        if self._get_by_sku_results is None:
            return None
        result = self._get_by_sku_results.pop(0) if self._get_by_sku_results else None
        if isinstance(result, Exception):
            raise result
        return result


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


def _make_producto(
    db, product_id=555, variant_id=1, published=True, variant_sku="SKU-1", activo=True
) -> TiendaNubeProducto:
    producto = TiendaNubeProducto(
        product_id=product_id,
        product_name="Test product",
        variant_id=variant_id,
        variant_sku=variant_sku,
        published=published,
    )
    db.add(producto)
    db.flush()
    # `activo` carries a Python-side column default of `True`, which
    # SQLAlchemy applies even when the attribute is explicitly set to
    # `None` at insert time. A post-insert UPDATE is the only way to
    # produce the legacy `activo IS NULL` row this suite needs.
    db.query(TiendaNubeProducto).filter(TiendaNubeProducto.id == producto.id).update({"activo": activo})
    db.flush()
    db.refresh(producto)
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


class TestUnpublishRateLimited:
    """Defect fix: `set_published` now raises `TnRateLimited` on a 429 (the
    client-level fix), so `unpublish_product` must catch it and return a
    structured `status="rate_limited"` outcome — mirroring exactly how
    `publish_product`/`TestPublishRateLimited` already handles it — instead
    of letting the exception propagate uncaught, or (before the client-level
    fix) misclassifying it as `rejected_by_proxy`."""

    def test_429_returns_structured_rate_limited_outcome(self, db):
        user = _make_user(db)
        _make_producto(db, product_id=555, published=True)
        fake_client = _FakeClient(TnRateLimited(retry_after=2.0))
        outcome = unpublish_product(db, user, 555, client=fake_client)
        assert outcome["submitted"] is False
        assert outcome["status"] == "rate_limited"
        assert outcome["status_code"] == 429
        # Nothing was attempted at TN's end — the local mirror is untouched.
        row = db.query(TiendaNubeProducto).filter(TiendaNubeProducto.product_id == 555).first()
        assert row.published is True

    def test_429_is_still_audit_logged(self, db):
        user = _make_user(db)
        _make_producto(db, product_id=555, published=True)
        fake_client = _FakeClient(TnRateLimited(retry_after=None))
        unpublish_product(db, user, 555, client=fake_client)
        audit_rows = db.query(Auditoria).filter(Auditoria.tipo_accion == TipoAccion.TN_DESPUBLICAR).all()
        assert len(audit_rows) == 1
        assert "rate_limited" in audit_rows[0].comentario


# PR-7 gap fix (task A): every existing test now also goes through the D3
# measurement gate (`validate_measurements`), so the default fixture below
# carries a complete set of the four measurement overrides — mirrors what
# the real modal always sends once a draft is unblocked (see
# `usePublishSubmit.buildOverrides`). Tests that specifically exercise the
# gate itself override `overrides` explicitly.
_VALID_MEASUREMENT_OVERRIDES = {"weight": "1.0", "width": "1.0", "depth": "1.0", "height": "1.0"}


def _publish_kwargs(**overrides):
    kwargs = dict(
        ean="EAN-PUB-1",
        # Slice 2 (publish price): every existing test in this module now
        # goes through the money-path guard, so the default fixture carries
        # a valid price. Tests that exercise the guard/price behavior itself
        # override `product_data` explicitly.
        product_data={"name": {"es": "Test Product"}, "price": "1000.00"},
        category_id=123,
        description_html="<p>Descripcion</p>",
        image_srcs=["https://cdn.example.com/img1.jpg", "https://cdn.example.com/img2.jpg"],
        # `measurements` is what the D3 gate reads (what to publish);
        # `overrides` is dirty-only (what the operator edited) and is
        # DELIBERATELY empty by default — the happy path edits nothing, and
        # gating on it once made every normal publish fail closed.
        measurements=dict(_VALID_MEASUREMENT_OVERRIDES),
        overrides={},
    )
    kwargs.update(overrides)
    return kwargs


class TestPublishIdempotency:
    def test_existing_local_mirror_for_ean_is_a_no_op(self, db):
        """Check-before-POST: if a TN product already exists locally for this
        EAN, publish must NOT re-create it (best-effort, local-mirror-only —
        no live TN GET is in scope this slice, same documented limitation as
        unpublish's reconcile-via-read gap)."""
        user = _make_user(db)
        _make_producto(db, product_id=777, variant_sku="EAN-PUB-1")
        fake_client = _FakePublishClient(
            create_outcome={"ok": True, "status_code": 201, "ambiguous": False, "body": {}}
        )
        outcome = publish_product(db, user, client=fake_client, **_publish_kwargs())
        assert outcome["status"] == "already_published"
        assert outcome["submitted"] is False
        assert fake_client.create_calls == []


class TestPublishStaleLocalMirror:
    """Production defect: the cheap local-mirror gate ignored `activo`, so a
    row left behind by a product TN no longer has (`activo=False`, set by
    the reconciliation sync's "deactivate everything, revive what
    /products returns" pass) permanently answered `already_published` and
    the EAN could never be republished. The gate must only short-circuit
    when the local row is still CREDIBLE; an explicitly-inactive row falls
    through to the live pre-check, which is the real authority."""

    def test_inactive_local_row_falls_through_and_publishes_when_tn_lacks_it(self, db):
        user = _make_user(db)
        _make_producto(db, product_id=777, variant_sku="EAN-PUB-1", activo=False)
        fake_client = _FakePublishClient(
            create_outcome={"ok": True, "status_code": 201, "ambiguous": False, "body": {"id": 888}},
            get_by_sku_results=[None],
        )
        outcome = publish_product(db, user, client=fake_client, **_publish_kwargs())
        assert outcome["status"] == "submitted"
        assert outcome["submitted"] is True
        # The live pre-check ran — it, not the local mirror, decided.
        assert fake_client.get_by_sku_calls == ["EAN-PUB-1"]
        assert len(fake_client.create_calls) == 1

    def test_inactive_local_row_but_tn_still_has_it_is_already_exists_no_duplicate(self, db):
        user = _make_user(db)
        _make_producto(db, product_id=777, variant_sku="EAN-PUB-1", activo=False)
        fake_client = _FakePublishClient(
            create_outcome={"ok": True, "status_code": 201, "ambiguous": False, "body": {}},
            get_by_sku_results=[{"id": 111, "variants": [{"id": 1110}]}],
        )
        outcome = publish_product(db, user, client=fake_client, **_publish_kwargs())
        assert outcome["status"] == "already_exists"
        assert outcome["submitted"] is False
        assert fake_client.create_calls == []

    def test_inactive_local_row_with_unreachable_tn_still_refuses_to_create(self, db):
        """Fail-closed is unchanged by the fix: falling through to the live
        pre-check must never degrade into publishing blind."""
        user = _make_user(db)
        _make_producto(db, product_id=777, variant_sku="EAN-PUB-1", activo=False)
        fake_client = _FakePublishClient(
            create_outcome={"ok": True, "status_code": 201, "ambiguous": False, "body": {}},
            get_by_sku_results=[TnProductLookupError("boom")],
        )
        outcome = publish_product(db, user, client=fake_client, **_publish_kwargs())
        assert outcome["status"] == "precheck_failed"
        assert fake_client.create_calls == []

    def test_active_local_row_still_short_circuits_without_calling_tn(self, db):
        """The common case must not gain a TN round-trip."""
        user = _make_user(db)
        _make_producto(db, product_id=777, variant_sku="EAN-PUB-1", activo=True)
        fake_client = _FakePublishClient(
            create_outcome={"ok": True, "status_code": 201, "ambiguous": False, "body": {}}
        )
        outcome = publish_product(db, user, client=fake_client, **_publish_kwargs())
        assert outcome["status"] == "already_published"
        assert fake_client.get_by_sku_calls == []
        assert fake_client.create_calls == []

    def test_null_activo_local_row_still_short_circuits(self, db):
        """`activo IS NULL` means "unknown", never "absent from TN" — only
        an explicit `False` is evidence the sync did not find the product.
        An unknown row keeps the conservative `already_published` answer."""
        user = _make_user(db)
        _make_producto(db, product_id=777, variant_sku="EAN-PUB-1", activo=None)
        fake_client = _FakePublishClient(
            create_outcome={"ok": True, "status_code": 201, "ambiguous": False, "body": {}}
        )
        outcome = publish_product(db, user, client=fake_client, **_publish_kwargs())
        assert outcome["status"] == "already_published"
        assert fake_client.get_by_sku_calls == []
        assert fake_client.create_calls == []


class TestPublishAlreadyPublishedAudit:
    def test_audit_row_records_the_ean_and_activo(self, db):
        """Diagnosing the production incident required deducing the product
        from `item_id` because `valores_nuevos` was null on this path."""
        user = _make_user(db)
        _make_producto(db, product_id=777, variant_sku="EAN-PUB-1", activo=True)
        fake_client = _FakePublishClient(
            create_outcome={"ok": True, "status_code": 201, "ambiguous": False, "body": {}}
        )
        publish_product(db, user, client=fake_client, **_publish_kwargs())
        audit_rows = db.query(Auditoria).filter(Auditoria.tipo_accion == TipoAccion.TN_PUBLICAR).all()
        assert len(audit_rows) == 1
        assert audit_rows[0].valores_nuevos is not None
        assert audit_rows[0].valores_nuevos["ean"] == "EAN-PUB-1"
        assert audit_rows[0].valores_nuevos["activo"] is True
        assert audit_rows[0].valores_nuevos["product_id"] == 777


class TestPublishSuccessfulWrite:
    def test_submitted_creates_product_adds_images_and_updates_mirror(self, db):
        user = _make_user(db)
        fake_client = _FakePublishClient(
            create_outcome={
                "ok": True,
                "status_code": 201,
                "ambiguous": False,
                "body": {"id": 999, "variants": [{"id": 9990}]},
            },
        )
        outcome = publish_product(db, user, client=fake_client, **_publish_kwargs())
        assert outcome["status"] == "submitted"
        assert outcome["submitted"] is True
        assert outcome["product_id"] == 999
        # category_id and description_html were merged into the create payload.
        payload = fake_client.create_calls[0]
        assert payload["categories"] == [123]
        assert payload["description"] == {"es": "<p>Descripcion</p>"}
        # Every image src was posted, in order.
        assert fake_client.image_calls == [
            (999, "https://cdn.example.com/img1.jpg"),
            (999, "https://cdn.example.com/img2.jpg"),
        ]
        row = db.query(TiendaNubeProducto).filter(TiendaNubeProducto.variant_sku == "EAN-PUB-1").first()
        assert row is not None
        assert row.product_id == 999
        # The REAL per-variant id from TN's response — never the product id
        # (see TestPublishMirrorVariantId below for the fabrication defect).
        assert row.variant_id == 9990

    def test_submitted_writes_an_audit_row(self, db):
        user = _make_user(db)
        fake_client = _FakePublishClient(
            create_outcome={"ok": True, "status_code": 201, "ambiguous": False, "body": {"id": 998}},
        )
        publish_product(db, user, client=fake_client, **_publish_kwargs())
        audit_rows = db.query(Auditoria).filter(Auditoria.tipo_accion == TipoAccion.TN_PUBLICAR).all()
        assert len(audit_rows) == 1
        assert audit_rows[0].item_id == 998

    def test_unreachable_image_url_is_skipped_not_sent_to_tn(self, db):
        """An obviously private/malformed src never reaches
        `add_product_image` — guarded locally via `is_publicly_reachable_url`
        (design's flagged image-reachability risk)."""
        user = _make_user(db)
        fake_client = _FakePublishClient(
            create_outcome={"ok": True, "status_code": 201, "ambiguous": False, "body": {"id": 997}},
        )
        outcome = publish_product(
            db,
            user,
            client=fake_client,
            **_publish_kwargs(image_srcs=["https://cdn.example.com/img1.jpg", "http://127.0.0.1/evil.jpg"]),
        )
        assert outcome["status"] == "submitted"
        assert fake_client.image_calls == [(997, "https://cdn.example.com/img1.jpg")]
        assert outcome["skipped_image_srcs"] == ["http://127.0.0.1/evil.jpg"]

    def test_rate_limited_image_is_reported_not_silently_dropped(self, db):
        """Defect fix: a 429 on `add_product_image` must NOT be silently
        lost (previously classified as a definitive rejection and only
        logged as a warning). The product was already created, so the
        publish still succeeds overall — but the rate-limited src is
        reported back distinctly from `skipped_image_srcs` (which is for
        locally-rejected URLs, a different failure mode) so the operator
        knows an image needs a manual retry."""
        user = _make_user(db)
        fake_client = _FakePublishClient(
            create_outcome={"ok": True, "status_code": 201, "ambiguous": False, "body": {"id": 996}},
            image_outcomes_by_src={
                "https://cdn.example.com/img2.jpg": TnRateLimited(retry_after=3.0),
            },
        )
        outcome = publish_product(db, user, client=fake_client, **_publish_kwargs())
        assert outcome["status"] == "submitted"
        assert outcome["submitted"] is True
        # Both images were attempted — the rate-limited one is not retried
        # synchronously (reported immediately instead).
        assert fake_client.image_calls == [
            (996, "https://cdn.example.com/img1.jpg"),
            (996, "https://cdn.example.com/img2.jpg"),
        ]
        assert outcome["rate_limited_image_srcs"] == ["https://cdn.example.com/img2.jpg"]
        assert outcome["skipped_image_srcs"] == []


class TestPublishMirrorVariantId:
    """Defect fix (tn-publisher-module PR-2): the local mirror insert used to
    set `variant_id = product_id` — a fabricated id the reconciliation UI
    then rendered as if it were real, until the next full catalog sync
    overwrote it. `variant_id` is NOT NULL on `TiendaNubeProducto` (see the
    model), so "leave it null" isn't an option — the fix instead extracts
    the REAL per-variant id from TN's response body (`variants[0]["id"]`,
    the same shape `tienda_nube_sync_shared.extract_variantes` reads from
    the catalog sync) and, when that's genuinely unavailable, skips the
    mirror insert entirely rather than fabricating a value — the row is
    created correctly by the next full sync instead (`published`'s
    established "unknown until backfilled" pattern, adapted for a NOT NULL
    column: skip instead of null)."""

    def test_submitted_with_no_variant_data_in_response_does_not_fabricate_row(self, db):
        user = _make_user(db)
        fake_client = _FakePublishClient(
            # No "variants" key at all — TN's response didn't carry per-variant
            # data (or a malformed/unexpected shape). The mirror MUST NOT be
            # created with variant_id=product_id in this case.
            create_outcome={"ok": True, "status_code": 201, "ambiguous": False, "body": {"id": 5001}},
        )
        outcome = publish_product(db, user, client=fake_client, **_publish_kwargs())
        assert outcome["status"] == "submitted"
        assert outcome["submitted"] is True
        assert outcome["product_id"] == 5001
        # No fabricated row — pending until the next full sync knows the
        # real variant id.
        assert db.query(TiendaNubeProducto).filter(TiendaNubeProducto.product_id == 5001).count() == 0

    def test_submitted_with_empty_variants_list_does_not_fabricate_row(self, db):
        user = _make_user(db)
        fake_client = _FakePublishClient(
            create_outcome={
                "ok": True,
                "status_code": 201,
                "ambiguous": False,
                "body": {"id": 5002, "variants": []},
            },
        )
        publish_product(db, user, client=fake_client, **_publish_kwargs())
        assert db.query(TiendaNubeProducto).filter(TiendaNubeProducto.product_id == 5002).count() == 0

    def test_submitted_with_real_variant_data_uses_the_real_variant_id(self, db):
        user = _make_user(db)
        fake_client = _FakePublishClient(
            create_outcome={
                "ok": True,
                "status_code": 201,
                "ambiguous": False,
                "body": {"id": 5003, "variants": [{"id": 50030}]},
            },
        )
        publish_product(db, user, client=fake_client, **_publish_kwargs())
        row = db.query(TiendaNubeProducto).filter(TiendaNubeProducto.product_id == 5003).first()
        assert row is not None
        assert row.variant_id == 50030
        # Never the product_id — that's exactly the fabrication this fixes.
        assert row.variant_id != row.product_id


class TestPublishPriceGuard:
    """Slice 2 money-path containment guard: an absent/non-numeric/
    non-positive submitted price is rejected BEFORE any TN call — no
    local-mirror query, no live pre-check, no create_product call."""

    def test_missing_price_is_rejected_before_any_local_or_tn_call(self, db):
        user = _make_user(db)
        fake_client = _FakePublishClient(
            create_outcome={"ok": True, "status_code": 201, "ambiguous": False, "body": {"id": 1}}
        )
        outcome = publish_product(
            db, user, client=fake_client, **_publish_kwargs(product_data={"name": {"es": "Test Product"}})
        )
        assert outcome["status"] == "rejected_invalid_price"
        assert outcome["submitted"] is False
        assert fake_client.create_calls == []
        assert fake_client.get_by_sku_calls == []

    def test_zero_price_is_rejected(self, db):
        user = _make_user(db)
        fake_client = _FakePublishClient(
            create_outcome={"ok": True, "status_code": 201, "ambiguous": False, "body": {"id": 1}}
        )
        outcome = publish_product(
            db,
            user,
            client=fake_client,
            **_publish_kwargs(product_data={"name": {"es": "Test Product"}, "price": "0"}),
        )
        assert outcome["status"] == "rejected_invalid_price"
        assert fake_client.create_calls == []

    def test_negative_price_is_rejected(self, db):
        user = _make_user(db)
        fake_client = _FakePublishClient(
            create_outcome={"ok": True, "status_code": 201, "ambiguous": False, "body": {"id": 1}}
        )
        outcome = publish_product(
            db,
            user,
            client=fake_client,
            **_publish_kwargs(product_data={"name": {"es": "Test Product"}, "price": "-10.00"}),
        )
        assert outcome["status"] == "rejected_invalid_price"
        assert fake_client.create_calls == []

    def test_non_numeric_price_is_rejected(self, db):
        user = _make_user(db)
        fake_client = _FakePublishClient(
            create_outcome={"ok": True, "status_code": 201, "ambiguous": False, "body": {"id": 1}}
        )
        outcome = publish_product(
            db,
            user,
            client=fake_client,
            **_publish_kwargs(product_data={"name": {"es": "Test Product"}, "price": "not-a-number"}),
        )
        assert outcome["status"] == "rejected_invalid_price"
        assert fake_client.create_calls == []

    def test_nan_price_is_rejected(self, db):
        """`Decimal("NaN")` parses without raising and compares False to
        everything, including `<= 0` — it must be rejected explicitly by
        name, not silently pass a naive positivity check."""
        user = _make_user(db)
        fake_client = _FakePublishClient(
            create_outcome={"ok": True, "status_code": 201, "ambiguous": False, "body": {"id": 1}}
        )
        outcome = publish_product(
            db,
            user,
            client=fake_client,
            **_publish_kwargs(product_data={"name": {"es": "Test Product"}, "price": "NaN"}),
        )
        assert outcome["status"] == "rejected_invalid_price"
        assert fake_client.create_calls == []

    def test_infinite_price_is_rejected(self, db):
        user = _make_user(db)
        fake_client = _FakePublishClient(
            create_outcome={"ok": True, "status_code": 201, "ambiguous": False, "body": {"id": 1}}
        )
        outcome = publish_product(
            db,
            user,
            client=fake_client,
            **_publish_kwargs(product_data={"name": {"es": "Test Product"}, "price": "Infinity"}),
        )
        assert outcome["status"] == "rejected_invalid_price"
        assert fake_client.create_calls == []

    def test_rejection_is_still_audit_logged(self, db):
        user = _make_user(db)
        fake_client = _FakePublishClient(
            create_outcome={"ok": True, "status_code": 201, "ambiguous": False, "body": {"id": 1}}
        )
        publish_product(
            db,
            user,
            client=fake_client,
            **_publish_kwargs(product_data={"name": {"es": "Test Product"}}),
        )
        audit_rows = db.query(Auditoria).filter(Auditoria.tipo_accion == TipoAccion.TN_PUBLICAR).all()
        assert len(audit_rows) == 1
        assert audit_rows[0].valores_nuevos is None


class TestValidatePublishPriceUnit:
    """Direct unit coverage of `_validate_publish_price` (money-path boundary
    conversion — see the Decimal(str(...)) gotcha documented on the
    function)."""

    def test_valid_decimal_string_returns_decimal(self):
        assert _validate_publish_price({"price": "1250.00"}) == Decimal("1250.00")

    def test_missing_price_raises(self):
        with pytest.raises(InvalidPublishPriceError):
            _validate_publish_price({})

    def test_none_price_raises(self):
        with pytest.raises(InvalidPublishPriceError):
            _validate_publish_price({"price": None})


class TestPublishPriceExactPayloadValue:
    """R2.6 — a test MUST assert the EXACT price value placed into the TN
    create payload, not just that a price key exists.

    The price MUST live on the variant, not the product root — the TN read
    path (`tienda_nube_sync_shared.py`) only ever reads `variant["price"]`,
    so a root-level `price` may simply be ignored by TN. See the module
    docstring / bugfix note in `tn_publish_service.publish_product` for the
    full reasoning."""

    def test_surcharge_path_exact_price_reaches_tn_create_payload(self, db):
        user = _make_user(db)
        fake_client = _FakePublishClient(
            create_outcome={"ok": True, "status_code": 201, "ambiguous": False, "body": {"id": 42}},
        )
        outcome = publish_product(
            db,
            user,
            client=fake_client,
            **_publish_kwargs(product_data={"name": {"es": "Test Product"}, "price": "1250.00"}),
        )
        assert outcome["status"] == "submitted"
        payload = fake_client.create_calls[0]
        assert "price" not in payload
        assert payload["variants"] == [
            {
                "sku": "EAN-PUB-1",
                "price": "1250.00",
                "weight": 1.0,
                "width": 1.0,
                "depth": 1.0,
                "height": 1.0,
            }
        ]

    def test_manual_entry_path_exact_price_reaches_tn_create_payload(self, db):
        user = _make_user(db)
        fake_client = _FakePublishClient(
            create_outcome={"ok": True, "status_code": 201, "ambiguous": False, "body": {"id": 43}},
        )
        outcome = publish_product(
            db,
            user,
            client=fake_client,
            **_publish_kwargs(product_data={"name": {"es": "Test Product"}, "price": "850.00"}),
            price_base_source="manual",
        )
        assert outcome["status"] == "submitted"
        payload = fake_client.create_calls[0]
        assert "price" not in payload
        assert payload["variants"] == [
            {
                "sku": "EAN-PUB-1",
                "price": "850.00",
                "weight": 1.0,
                "width": 1.0,
                "depth": 1.0,
                "height": 1.0,
            }
        ]


class TestPublishVariantSku:
    """A product created without a `sku` breaks the entire write-safety
    design of `publish_product`: both the idempotency pre-check and the
    ambiguous-outcome read-back call `get_product_by_sku(ean)`, which can
    never find a product that was never given a SKU. Without this, a retry
    after an ambiguous outcome creates a DUPLICATE instead of being detected
    — exactly what the idempotency design exists to prevent."""

    def test_variant_sku_equals_ean(self, db):
        user = _make_user(db)
        fake_client = _FakePublishClient(
            create_outcome={"ok": True, "status_code": 201, "ambiguous": False, "body": {"id": 46}},
        )
        outcome = publish_product(
            db,
            user,
            client=fake_client,
            **_publish_kwargs(ean="EAN-SKU-TEST", product_data={"name": {"es": "Test Product"}, "price": "500.00"}),
        )
        assert outcome["status"] == "submitted"
        payload = fake_client.create_calls[0]
        assert payload["variants"][0]["sku"] == "EAN-SKU-TEST"


class TestPublishPriceAudit:
    """R2.5 — the `TN_PUBLICAR` audit entry must record both the submitted
    price and the offset used on a successful publish."""

    def test_audit_records_submitted_price_offset_and_base_source(self, db):
        user = _make_user(db)
        fake_client = _FakePublishClient(
            create_outcome={"ok": True, "status_code": 201, "ambiguous": False, "body": {"id": 44}},
        )
        publish_product(
            db,
            user,
            client=fake_client,
            **_publish_kwargs(product_data={"name": {"es": "Test Product"}, "price": "1250.00"}),
            offset_percent=25,
            price_base_source="web_transferencia",
        )
        audit = (
            db.query(Auditoria).filter(Auditoria.tipo_accion == TipoAccion.TN_PUBLICAR, Auditoria.item_id == 44).one()
        )
        assert audit.valores_nuevos["submitted_price"] == "1250.00"
        assert audit.valores_nuevos["offset_percent"] == 25
        assert audit.valores_nuevos["price_base_source"] == "web_transferencia"

    def test_audit_records_manual_entry_base_source_with_no_offset(self, db):
        user = _make_user(db)
        fake_client = _FakePublishClient(
            create_outcome={"ok": True, "status_code": 201, "ambiguous": False, "body": {"id": 45}},
        )
        publish_product(
            db,
            user,
            client=fake_client,
            **_publish_kwargs(product_data={"name": {"es": "Test Product"}, "price": "850.00"}),
            offset_percent=None,
            price_base_source="manual",
        )
        audit = (
            db.query(Auditoria).filter(Auditoria.tipo_accion == TipoAccion.TN_PUBLICAR, Auditoria.item_id == 45).one()
        )
        assert audit.valores_nuevos["submitted_price"] == "850.00"
        assert audit.valores_nuevos["price_base_source"] == "manual"
        assert "offset_percent" not in audit.valores_nuevos


class TestPublishRejectedByProxy:
    def test_4xx_on_create_is_rejected_by_proxy_no_local_row(self, db):
        user = _make_user(db)
        fake_client = _FakePublishClient(
            create_outcome={"ok": False, "status_code": 422, "ambiguous": False, "body": {"error": "invalid"}},
        )
        outcome = publish_product(db, user, client=fake_client, **_publish_kwargs())
        assert outcome["status"] == "rejected_by_proxy"
        assert outcome["submitted"] is False
        assert isinstance(outcome["detail"], str)
        assert fake_client.image_calls == []
        assert db.query(TiendaNubeProducto).filter(TiendaNubeProducto.variant_sku == "EAN-PUB-1").count() == 0


class TestPublishMeasurementGate:
    """PR-7 gap fix (task A) — D3, fail-closed, server-side. A publish whose
    `overrides` don't resolve all four measurement fields must be blocked
    BEFORE any local-mirror query or TN call — mirrors
    `TestPublishPriceGuard`'s containment pattern."""

    def test_missing_all_four_measurements_is_blocked_before_any_tn_call(self, db):
        user = _make_user(db)
        fake_client = _FakePublishClient(
            create_outcome={"ok": True, "status_code": 201, "ambiguous": False, "body": {"id": 1}},
        )
        outcome = publish_product(db, user, client=fake_client, **_publish_kwargs(measurements={}))
        assert outcome["status"] == "blocked_measurements"
        assert outcome["submitted"] is False
        assert fake_client.create_calls == []
        assert fake_client.get_by_sku_calls == []

    def test_missing_one_measurement_names_it_and_only_it(self, db):
        user = _make_user(db)
        fake_client = _FakePublishClient(
            create_outcome={"ok": True, "status_code": 201, "ambiguous": False, "body": {"id": 1}},
        )
        overrides = {k: v for k, v in _VALID_MEASUREMENT_OVERRIDES.items() if k != "height"}
        outcome = publish_product(db, user, client=fake_client, **_publish_kwargs(measurements=overrides))
        assert outcome["status"] == "blocked_measurements"
        assert len(outcome["blocked_reasons"]) == 1
        assert "height" in outcome["blocked_reasons"][0]
        assert fake_client.create_calls == []

    def test_unparseable_measurement_value_is_treated_as_absent_and_blocks(self, db):
        user = _make_user(db)
        fake_client = _FakePublishClient(
            create_outcome={"ok": True, "status_code": 201, "ambiguous": False, "body": {"id": 1}},
        )
        overrides = {**_VALID_MEASUREMENT_OVERRIDES, "weight": "not-a-number"}
        outcome = publish_product(db, user, client=fake_client, **_publish_kwargs(measurements=overrides))
        assert outcome["status"] == "blocked_measurements"
        assert any("weight" in reason for reason in outcome["blocked_reasons"])

    def test_blocked_measurements_is_still_audit_logged(self, db):
        user = _make_user(db)
        fake_client = _FakePublishClient(
            create_outcome={"ok": True, "status_code": 201, "ambiguous": False, "body": {"id": 1}},
        )
        publish_product(db, user, client=fake_client, **_publish_kwargs(measurements={}))
        audit_rows = db.query(Auditoria).filter(Auditoria.tipo_accion == TipoAccion.TN_PUBLICAR).all()
        assert len(audit_rows) == 1
        assert audit_rows[0].valores_nuevos is None
        assert "blocked_measurements" in audit_rows[0].comentario

    def test_all_four_measurements_present_is_never_blocked(self, db):
        """Triangulation: the gate opens once all four resolve."""
        user = _make_user(db)
        fake_client = _FakePublishClient(
            create_outcome={"ok": True, "status_code": 201, "ambiguous": False, "body": {"id": 1}},
        )
        outcome = publish_product(db, user, client=fake_client, **_publish_kwargs())
        assert outcome["status"] == "submitted"


class TestPublishAssembledFieldsReachTn:
    """PR-7 gap fix (task A) — proves the fields `assemble_payload` now owns
    (weight/width/depth/height, stock, visibility, tags, seo_*) actually
    reach the TN create payload through the live `publish_product` path,
    not just through `assemble_payload`'s own unit tests."""

    def test_measurements_reach_the_variant(self, db):
        user = _make_user(db)
        fake_client = _FakePublishClient(
            create_outcome={"ok": True, "status_code": 201, "ambiguous": False, "body": {"id": 1}},
        )
        outcome = publish_product(
            db,
            user,
            client=fake_client,
            **_publish_kwargs(measurements={"weight": "1.5", "width": "10", "depth": "20", "height": "30"}),
        )
        assert outcome["status"] == "submitted"
        variant = fake_client.create_calls[0]["variants"][0]
        assert variant["weight"] == 1.5
        assert variant["width"] == 10.0
        assert variant["depth"] == 20.0
        assert variant["height"] == 30.0

    def test_stock_reaches_inventory_levels_never_variant_stock(self, db):
        user = _make_user(db)
        fake_client = _FakePublishClient(
            create_outcome={"ok": True, "status_code": 201, "ambiguous": False, "body": {"id": 1}},
        )
        outcome = publish_product(
            db,
            user,
            client=fake_client,
            **_publish_kwargs(
                product_data={"name": {"es": "Test Product"}, "price": "1000.00", "stock": 7},
            ),
        )
        assert outcome["status"] == "submitted"
        variant = fake_client.create_calls[0]["variants"][0]
        assert variant["inventory_levels"] == [{"stock": 7}]
        assert "stock" not in variant

    def test_absent_stock_omits_inventory_levels_never_fabricates_a_number(self, db):
        """Triangulation: no `stock` key in `product_data` must never become
        `[{"stock": 0}]` — see `assemble_payload`'s docstring."""
        user = _make_user(db)
        fake_client = _FakePublishClient(
            create_outcome={"ok": True, "status_code": 201, "ambiguous": False, "body": {"id": 1}},
        )
        outcome = publish_product(db, user, client=fake_client, **_publish_kwargs())
        assert outcome["status"] == "submitted"
        variant = fake_client.create_calls[0]["variants"][0]
        assert "inventory_levels" not in variant

    def test_barcode_cost_promotional_price_land_on_the_variant_not_the_root(self, db):
        """These three are VARIANT-level fields in TN v1. At the payload root
        TN ignores them with no error, so an operator edit would vanish —
        the same silent-loss class `inventory_levels` guards against. This
        test pins them onto the variant AND off the root."""
        user = _make_user(db)
        fake_client = _FakePublishClient(
            create_outcome={"ok": True, "status_code": 201, "ambiguous": False, "body": {"id": 1}},
        )
        outcome = publish_product(
            db,
            user,
            client=fake_client,
            **_publish_kwargs(
                product_data={
                    "name": {"es": "Test Product"},
                    "price": "1000.00",
                    "barcode": "7791234567890",
                    "cost": 500.0,
                    "promotional_price": 800.0,
                },
            ),
        )
        assert outcome["status"] == "submitted"
        payload = fake_client.create_calls[0]
        assert "barcode" not in payload
        assert "cost" not in payload
        assert "promotional_price" not in payload
        variant = payload["variants"][0]
        assert variant["barcode"] == "7791234567890"
        assert variant["cost"] == 500.0
        assert variant["promotional_price"] == "800.0"

    def test_visibility_and_free_shipping_reach_the_payload_root(self, db):
        user = _make_user(db)
        fake_client = _FakePublishClient(
            create_outcome={"ok": True, "status_code": 201, "ambiguous": False, "body": {"id": 1}},
        )
        outcome = publish_product(
            db,
            user,
            client=fake_client,
            **_publish_kwargs(
                product_data={
                    "name": {"es": "Test Product"},
                    "price": "1000.00",
                    "visibility": "hidden",
                    "free_shipping": True,
                },
            ),
        )
        assert outcome["status"] == "submitted"
        payload = fake_client.create_calls[0]
        assert payload["visibility"] == "hidden"
        assert payload["free_shipping"] is True
        assert "published" not in payload

    def test_tags_and_seo_fields_reach_the_payload(self, db):
        user = _make_user(db)
        fake_client = _FakePublishClient(
            create_outcome={"ok": True, "status_code": 201, "ambiguous": False, "body": {"id": 1}},
        )
        outcome = publish_product(
            db,
            user,
            client=fake_client,
            **_publish_kwargs(
                product_data={
                    "name": {"es": "Test Product"},
                    "price": "1000.00",
                    "tags": ["Marca", "Categoria"],
                    "seo_title": "Titulo SEO",
                    "seo_description": "Descripcion SEO",
                },
            ),
        )
        assert outcome["status"] == "submitted"
        payload = fake_client.create_calls[0]
        assert payload["tags"] == ["Marca", "Categoria"]
        assert payload["seo_title"] == {"es": "Titulo SEO"}
        assert payload["seo_description"] == {"es": "Descripcion SEO"}


class TestPublishCostGate:
    """D6/PC8, fail-closed: a USD cost with no `TipoCambio` row must block
    the publish server-side. The draft already refused to resolve it, but
    that verdict was decorative until the write path enforced it too — the
    item published with a null/unconverted cost and nothing named the
    missing rate."""

    def test_usd_cost_with_no_rate_blocks_before_any_tn_call(self, db):
        user = _make_user(db)
        fake_client = _FakePublishClient(
            create_outcome={"ok": True, "status_code": 201, "ambiguous": False, "body": {"id": 1}},
        )
        outcome = publish_product(db, user, client=fake_client, **_publish_kwargs(moneda_costo="USD"))
        assert outcome["status"] == "blocked_cost"
        assert outcome["submitted"] is False
        assert fake_client.create_calls == []
        assert any("tipo de cambio" in r.lower() for r in outcome["blocked_reasons"])

    def test_blocked_cost_is_audit_logged(self, db):
        user = _make_user(db)
        fake_client = _FakePublishClient(
            create_outcome={"ok": True, "status_code": 201, "ambiguous": False, "body": {"id": 1}},
        )
        publish_product(db, user, client=fake_client, **_publish_kwargs(moneda_costo="USD"))
        audit = db.query(Auditoria).filter(Auditoria.tipo_accion == TipoAccion.TN_PUBLICAR).one()
        assert "blocked_cost" in audit.comentario
        assert audit.valores_nuevos is None

    def test_ars_cost_publishes_without_needing_a_rate(self, db):
        user = _make_user(db)
        fake_client = _FakePublishClient(
            create_outcome={"ok": True, "status_code": 201, "ambiguous": False, "body": {"id": 1}},
        )
        outcome = publish_product(db, user, client=fake_client, **_publish_kwargs(moneda_costo="ARS"))
        assert outcome["status"] == "submitted"

    def test_usd_cost_with_a_rate_available_publishes(self, db):
        from app.models.tipo_cambio import TipoCambio

        db.add(TipoCambio(fecha=date.today(), moneda="USD", compra=1000.0, venta=1000.0))
        db.commit()
        user = _make_user(db)
        fake_client = _FakePublishClient(
            create_outcome={"ok": True, "status_code": 201, "ambiguous": False, "body": {"id": 1}},
        )
        outcome = publish_product(db, user, client=fake_client, **_publish_kwargs(moneda_costo="USD"))
        assert outcome["status"] == "submitted"


class TestPublishOverridePersistence:
    """PC5/D8 (task 5.4/5.5): a SUCCESSFUL publish upserts every
    operator-edited field into `tn_publish_override`, keyed by `(ean,
    campo)`. D8 is enforced structurally elsewhere (the core has no GBP
    write client on its call path); this only proves the upsert itself
    fires on success and stays silent on every other outcome."""

    def test_unknown_override_field_is_skipped_never_persisted(self, db):
        # Defense in depth behind the endpoint's 422 validator: a caller
        # bypassing `PublicarRequest` (a future internal consumer) must not
        # be able to persist arbitrary campos — the unknown key is skipped
        # with a warning while the known one still persists.
        user = _make_user(db)
        fake_client = _FakePublishClient(
            create_outcome={"ok": True, "status_code": 201, "ambiguous": False, "body": {"id": 993}},
        )
        publish_product(
            db,
            user,
            client=fake_client,
            **_publish_kwargs(
                ean="EAN-OVR-UNK",
                overrides={**_VALID_MEASUREMENT_OVERRIDES, "weight": "1.200", "campo_inventado": "zzz"},
            ),
        )
        campos = {row.campo for row in db.query(TnPublishOverride).filter(TnPublishOverride.ean == "EAN-OVR-UNK")}
        assert campos == {"weight", "width", "depth", "height"}

    def test_successful_publish_upserts_every_overridden_field(self, db):
        user = _make_user(db)
        fake_client = _FakePublishClient(
            create_outcome={"ok": True, "status_code": 201, "ambiguous": False, "body": {"id": 991}},
        )
        publish_product(
            db,
            user,
            client=fake_client,
            **_publish_kwargs(overrides={"weight": "1.200", "width": "13", "depth": "2.0", "height": "3.0"}),
        )
        rows = {
            row.campo: row.valor
            for row in db.query(TnPublishOverride).filter(TnPublishOverride.ean == "EAN-PUB-1").all()
        }
        assert rows == {"weight": "1.200", "width": "13", "depth": "2.0", "height": "3.0"}

    def test_re_publish_updates_the_existing_override_row_not_a_duplicate(self, db):
        user = _make_user(db)
        db.add(TnPublishOverride(ean="EAN-PUB-1", campo="weight", valor="0.900", usuario_id=user.id))
        db.commit()
        fake_client = _FakePublishClient(
            create_outcome={"ok": True, "status_code": 201, "ambiguous": False, "body": {"id": 992}},
        )
        publish_product(
            db,
            user,
            client=fake_client,
            **_publish_kwargs(ean="EAN-PUB-1", overrides={**_VALID_MEASUREMENT_OVERRIDES, "weight": "1.200"}),
        )
        rows = db.query(TnPublishOverride).filter(TnPublishOverride.ean == "EAN-PUB-1").all()
        assert len(rows) == 4
        assert next(r for r in rows if r.campo == "weight").valor == "1.200"

    def test_the_happy_path_publishes_and_persists_nothing(self, db):
        """The operator edited nothing: the item still PUBLISHES (its
        measurements travel in `measurements`), and precisely because
        nothing was edited, no `tn_publish_override` row is written.

        This is the end-to-end shape a previous revision got wrong by
        reading the D3 gate off `overrides`: dirty-only overrides meant an
        untouched item sent `{}` and every normal publish failed closed.
        Frontend and backend tests each passed in isolation while the flow
        between them was broken — hence this one asserts both halves."""
        user = _make_user(db)
        fake_client = _FakePublishClient(
            create_outcome={"ok": True, "status_code": 201, "ambiguous": False, "body": {"id": 993}},
        )
        outcome = publish_product(db, user, client=fake_client, **_publish_kwargs(overrides={}))
        assert outcome["status"] == "submitted"
        assert db.query(TnPublishOverride).count() == 0

    def test_rejected_invalid_price_persists_no_override(self, db):
        user = _make_user(db)
        publish_product(
            db,
            user,
            client=_FakePublishClient(create_outcome={"ok": True, "status_code": 201, "ambiguous": False, "body": {}}),
            **_publish_kwargs(overrides={"weight": "1.200"}, product_data={"name": {"es": "x"}, "price": None}),
        )
        assert db.query(TnPublishOverride).count() == 0

    def test_ambiguous_outcome_with_no_readback_persists_no_override(self, db):
        user = _make_user(db)
        fake_client = _FakePublishClient(
            create_outcome={"ok": False, "status_code": 503, "ambiguous": True, "body": None},
        )
        publish_product(db, user, client=fake_client, **_publish_kwargs())
        assert db.query(TnPublishOverride).count() == 0

    def test_no_gbp_erp_write_client_used_no_side_effect_beyond_override_table(self, db):
        """D8 structural proof: the override upsert touches ONLY
        `tn_publish_override` — it never calls any GBP/ERP write method on
        the injected client (which has none to call in the first place)."""
        user = _make_user(db)
        fake_client = _FakePublishClient(
            create_outcome={"ok": True, "status_code": 201, "ambiguous": False, "body": {"id": 994}},
        )
        publish_product(db, user, client=fake_client, **_publish_kwargs())
        assert not hasattr(fake_client, "update_erp") and not hasattr(fake_client, "write_gbp")


class TestPublishRateLimited:
    """`create_product` raises `TnRateLimited` on a 429 (added for
    `execute_batch`, which is not wired into this live path until the next
    slice). The live path must degrade to a structured outcome — before
    this handler existed, the exception escaped as an unhandled 500 and
    `_audit_publish` never ran."""

    def test_429_on_create_returns_structured_rate_limited_outcome(self, db):
        user = _make_user(db)
        fake_client = _FakePublishClient(create_outcome=TnRateLimited(retry_after=2.0))
        outcome = publish_product(db, user, client=fake_client, **_publish_kwargs())
        assert outcome["status"] == "rate_limited"
        assert outcome["submitted"] is False
        assert outcome["status_code"] == 429
        # A 429 is a definitive rejection: exactly one attempt, no images,
        # no local mirror row.
        assert len(fake_client.create_calls) == 1
        assert fake_client.image_calls == []
        assert db.query(TiendaNubeProducto).filter(TiendaNubeProducto.variant_sku == "EAN-PUB-1").count() == 0

    def test_rate_limited_outcome_is_audit_logged(self, db):
        user = _make_user(db)
        fake_client = _FakePublishClient(create_outcome=TnRateLimited(retry_after=None))
        publish_product(db, user, client=fake_client, **_publish_kwargs())
        audit = (
            db.query(Auditoria)
            .filter(Auditoria.tipo_accion == TipoAccion.TN_PUBLICAR, Auditoria.item_id.is_(None))
            .one()
        )
        # Nothing was created at TN, so no published-state transition may be
        # claimed — mirrors the rejected_by_proxy audit contract.
        assert audit.valores_nuevos is None
        assert "rate_limited" in audit.comentario


class TestPublishAmbiguousOutcome:
    def test_5xx_on_create_is_ambiguous_and_never_retried_no_local_row(self, db):
        user = _make_user(db)
        fake_client = _FakePublishClient(
            create_outcome={"ok": False, "status_code": 503, "ambiguous": True, "body": None},
        )
        outcome = publish_product(db, user, client=fake_client, **_publish_kwargs())
        assert outcome["status"] == "ambiguous"
        assert outcome["submitted"] is False
        assert len(fake_client.create_calls) == 1
        assert fake_client.image_calls == []
        assert db.query(TiendaNubeProducto).filter(TiendaNubeProducto.variant_sku == "EAN-PUB-1").count() == 0

    def test_ambiguous_outcome_is_still_audit_logged(self, db):
        user = _make_user(db)
        fake_client = _FakePublishClient(
            create_outcome={"ok": False, "status_code": None, "ambiguous": True, "body": None},
        )
        publish_product(db, user, client=fake_client, **_publish_kwargs())
        audit_rows = db.query(Auditoria).filter(Auditoria.tipo_accion == TipoAccion.TN_PUBLICAR).all()
        assert len(audit_rows) == 1


class TestSanitizeDescriptionHtml:
    """Server-side defense-in-depth sanitization (security review follow-up
    to sub-slice 3a) — applied unconditionally in `publish_product` BEFORE
    the frontend's planned DOMPurify (Slice 3c) even exists. Conservative
    allow-list: basic formatting/structure only."""

    def test_script_tag_is_stripped(self):
        result = sanitize_description_html("<p>Hello</p><script>alert(1)</script>")
        assert "<script" not in result
        assert "alert(1)" not in result
        assert "<p>Hello</p>" in result

    def test_event_handler_attribute_is_stripped(self):
        result = sanitize_description_html('<img src="x" onerror="alert(1)">')
        assert "onerror" not in result
        assert "alert(1)" not in result

    def test_javascript_url_in_link_is_stripped(self):
        result = sanitize_description_html('<a href="javascript:alert(1)">click</a>')
        assert "javascript:" not in result

    def test_iframe_is_stripped(self):
        result = sanitize_description_html('<iframe src="https://evil.example.com"></iframe>')
        assert "<iframe" not in result

    def test_style_tag_is_stripped(self):
        result = sanitize_description_html("<style>body{background:url(javascript:alert(1))}</style><p>ok</p>")
        assert "<style" not in result
        assert "<p>ok</p>" in result

    def test_safe_formatting_tags_survive(self):
        html = "<p>Some <b>bold</b> and <i>italic</i> and <strong>strong</strong> text</p>"
        result = sanitize_description_html(html)
        assert "<b>bold</b>" in result
        assert "<i>italic</i>" in result
        assert "<strong>strong</strong>" in result

    def test_lists_survive(self):
        html = "<ul><li>one</li><li>two</li></ul>"
        result = sanitize_description_html(html)
        assert "<ul>" in result
        assert "<li>one</li>" in result

    def test_safe_http_link_survives(self):
        html = '<a href="https://example.com">link</a>'
        result = sanitize_description_html(html)
        assert 'href="https://example.com"' in result
        assert ">link</a>" in result

    def test_headings_survive(self):
        result = sanitize_description_html("<h2>Title</h2><p>body</p>")
        assert "<h2>Title</h2>" in result


class TestPublishSanitizesDescription:
    def test_dangerous_description_html_is_sanitized_before_reaching_client(self, db):
        """The RAW (unsanitized) description must never reach
        `create_product` — only the sanitized version, proving the
        server-side pass actually runs in the publish path, not just as a
        standalone unused helper."""
        user = _make_user(db)
        fake_client = _FakePublishClient(
            create_outcome={"ok": True, "status_code": 201, "ambiguous": False, "body": {"id": 555}},
        )
        dangerous_html = '<p>Real desc</p><script>alert(1)</script><img src=x onerror="alert(2)">'
        publish_product(db, user, client=fake_client, **_publish_kwargs(description_html=dangerous_html))

        sent_payload = fake_client.create_calls[0]
        sent_description = sent_payload["description"]["es"]
        assert "<script" not in sent_description
        assert "onerror" not in sent_description
        assert "<p>Real desc</p>" in sent_description


class TestPublishLivePrecheck:
    """Security-review follow-up: the LIVE `get_product_by_sku` pre-check is
    now the authority for idempotency, restoring the reconcile-via-read
    step Slice 2 couldn't do. The cheap local-mirror check still runs first
    (see `TestPublishIdempotency`) but the live check decides for anything
    the local mirror doesn't already know about."""

    def test_live_precheck_finds_existing_product_no_create(self, db):
        user = _make_user(db)
        fake_client = _FakePublishClient(
            create_outcome={"ok": True, "status_code": 201, "ambiguous": False, "body": {}},
            get_by_sku_results=[{"id": 111, "variants": [{"id": 1110}]}],
        )
        outcome = publish_product(db, user, client=fake_client, **_publish_kwargs())
        assert outcome["status"] == "already_exists"
        assert outcome["submitted"] is False
        assert fake_client.create_calls == []
        # Best-effort: the local mirror is brought in sync with what TN
        # actually has, even though WE didn't create it this call.
        row = db.query(TiendaNubeProducto).filter(TiendaNubeProducto.product_id == 111).first()
        assert row is not None
        assert row.variant_sku == "EAN-PUB-1"
        assert row.variant_id == 1110

    def test_live_precheck_confirms_absent_creates(self, db):
        user = _make_user(db)
        fake_client = _FakePublishClient(
            create_outcome={"ok": True, "status_code": 201, "ambiguous": False, "body": {"id": 222}},
            get_by_sku_results=[None],
        )
        outcome = publish_product(db, user, client=fake_client, **_publish_kwargs())
        assert outcome["status"] == "submitted"
        assert len(fake_client.create_calls) == 1

    def test_live_precheck_errors_returns_precheck_failed_no_create(self, db):
        user = _make_user(db)
        fake_client = _FakePublishClient(
            create_outcome={"ok": True, "status_code": 201, "ambiguous": False, "body": {}},
            get_by_sku_results=[TnProductLookupError("timeout")],
        )
        outcome = publish_product(db, user, client=fake_client, **_publish_kwargs())
        assert outcome["status"] == "precheck_failed"
        assert outcome["submitted"] is False
        assert fake_client.create_calls == []

    def test_precheck_failed_is_still_audit_logged(self, db):
        user = _make_user(db)
        fake_client = _FakePublishClient(
            create_outcome={"ok": True, "status_code": 201, "ambiguous": False, "body": {}},
            get_by_sku_results=[TnProductLookupError("timeout")],
        )
        publish_product(db, user, client=fake_client, **_publish_kwargs())
        audit_rows = db.query(Auditoria).filter(Auditoria.tipo_accion == TipoAccion.TN_PUBLICAR).all()
        assert len(audit_rows) == 1
        assert "precheck_failed" in audit_rows[0].comentario


class TestPublishAmbiguousReadBack:
    """After an ambiguous `create_product` outcome (timeout/5xx), attempt
    ONE read-back via `get_product_by_sku` — a READ, not a write-retry, so
    this doesn't violate the no-retry-on-ambiguous-write rule."""

    def test_readback_finds_product_recovers_as_submitted(self, db):
        user = _make_user(db)
        fake_client = _FakePublishClient(
            create_outcome={"ok": False, "status_code": 503, "ambiguous": True, "body": None},
            # First call = live pre-check (confirmed absent) -> proceed to create.
            # Second call = read-back after the ambiguous create -> found.
            get_by_sku_results=[None, {"id": 333, "variants": [{"id": 3330}]}],
        )
        outcome = publish_product(db, user, client=fake_client, **_publish_kwargs())
        assert outcome["status"] == "submitted"
        assert outcome["submitted"] is True
        assert outcome["product_id"] == 333
        row = db.query(TiendaNubeProducto).filter(TiendaNubeProducto.product_id == 333).first()
        assert row is not None
        assert row.variant_id == 3330

    def test_readback_confirms_absent_stays_ambiguous(self, db):
        user = _make_user(db)
        fake_client = _FakePublishClient(
            create_outcome={"ok": False, "status_code": 503, "ambiguous": True, "body": None},
            get_by_sku_results=[None, None],
        )
        outcome = publish_product(db, user, client=fake_client, **_publish_kwargs())
        assert outcome["status"] == "ambiguous"
        assert outcome["submitted"] is False
        assert db.query(TiendaNubeProducto).filter(TiendaNubeProducto.variant_sku == "EAN-PUB-1").count() == 0

    def test_readback_itself_errors_stays_ambiguous(self, db):
        user = _make_user(db)
        fake_client = _FakePublishClient(
            create_outcome={"ok": False, "status_code": None, "ambiguous": True, "body": None},
            get_by_sku_results=[None, TnProductLookupError("timeout on readback")],
        )
        outcome = publish_product(db, user, client=fake_client, **_publish_kwargs())
        assert outcome["status"] == "ambiguous"
        assert outcome["submitted"] is False

    def test_recovered_via_readback_is_audit_logged(self, db):
        user = _make_user(db)
        fake_client = _FakePublishClient(
            create_outcome={"ok": False, "status_code": 503, "ambiguous": True, "body": None},
            get_by_sku_results=[None, {"id": 444}],
        )
        publish_product(db, user, client=fake_client, **_publish_kwargs())
        audit_rows = (
            db.query(Auditoria).filter(Auditoria.tipo_accion == TipoAccion.TN_PUBLICAR, Auditoria.item_id == 444).all()
        )
        assert len(audit_rows) == 1
        assert "submitted" in audit_rows[0].comentario


class TestCategoryProfileHintWrite:
    """PR-8 gap B: on a SUCCESSFUL publish where a profile was applied,
    `publish_product` upserts `tn_category_profile_hint(categoria,
    subcategoria, profile_id)` and increments `uso_count` — the write that
    was always missing, leaving `suggested_profile_id` permanently
    cold-start (see PR-8 brief). Mirrors `_upsert_publish_overrides`:
    best-effort, ONLY on `submitted`, never masks the TN outcome."""

    def _fake_client(self, product_id=999):
        return _FakePublishClient(
            create_outcome={"ok": True, "status_code": 201, "ambiguous": False, "body": {"id": product_id}},
        )

    def test_no_hint_written_when_no_profile_applied(self, db):
        from app.models.tn_category_profile_hint import TnCategoryProfileHint

        user = _make_user(db)
        publish_product(
            db, user, client=self._fake_client(), **_publish_kwargs(categoria="Hogar", subcategoria="Cocina")
        )
        assert db.query(TnCategoryProfileHint).count() == 0

    def test_hint_created_on_submitted_with_profile(self, db):
        from app.models.tn_category_profile_hint import TnCategoryProfileHint
        from app.models.tn_measurement_profile import TnMeasurementProfile

        user = _make_user(db)
        profile = TnMeasurementProfile(name="30x20x20", weight=1, width=30, height=20, depth=20)
        db.add(profile)
        db.flush()

        publish_product(
            db,
            user,
            client=self._fake_client(),
            **_publish_kwargs(categoria="Hogar", subcategoria="Cocina", profile_id=profile.id),
        )
        hint = db.query(TnCategoryProfileHint).one()
        assert hint.categoria == "Hogar"
        assert hint.subcategoria == "Cocina"
        assert hint.profile_id == profile.id
        assert hint.uso_count == 1

    def test_hint_increments_on_repeat_publish(self, db):
        from app.models.tn_category_profile_hint import TnCategoryProfileHint
        from app.models.tn_measurement_profile import TnMeasurementProfile

        user = _make_user(db)
        profile = TnMeasurementProfile(name="30x20x20", weight=1, width=30, height=20, depth=20)
        db.add(profile)
        db.flush()

        kwargs = _publish_kwargs(categoria="Hogar", subcategoria="Cocina", profile_id=profile.id)
        publish_product(db, user, client=self._fake_client(product_id=1), **kwargs)
        kwargs2 = _publish_kwargs(ean="EAN-PUB-2", categoria="Hogar", subcategoria="Cocina", profile_id=profile.id)
        publish_product(db, user, client=self._fake_client(product_id=2), **kwargs2)

        hint = db.query(TnCategoryProfileHint).one()
        assert hint.uso_count == 2

    def test_no_hint_written_on_rejected_invalid_price(self, db):
        from app.models.tn_category_profile_hint import TnCategoryProfileHint
        from app.models.tn_measurement_profile import TnMeasurementProfile

        user = _make_user(db)
        profile = TnMeasurementProfile(name="30x20x20", weight=1, width=30, height=20, depth=20)
        db.add(profile)
        db.flush()

        kwargs = _publish_kwargs(
            categoria="Hogar", subcategoria="Cocina", profile_id=profile.id, product_data={"name": {"es": "x"}}
        )
        publish_product(db, user, client=self._fake_client(), **kwargs)
        assert db.query(TnCategoryProfileHint).count() == 0

    def test_no_hint_written_on_ambiguous_outcome(self, db):
        from app.models.tn_category_profile_hint import TnCategoryProfileHint
        from app.models.tn_measurement_profile import TnMeasurementProfile

        user = _make_user(db)
        profile = TnMeasurementProfile(name="30x20x20", weight=1, width=30, height=20, depth=20)
        db.add(profile)
        db.flush()

        fake_client = _FakePublishClient(
            create_outcome={"ok": False, "status_code": 503, "ambiguous": True, "body": None},
            get_by_sku_results=[None, None],
        )
        publish_product(
            db,
            user,
            client=fake_client,
            **_publish_kwargs(categoria="Hogar", subcategoria="Cocina", profile_id=profile.id),
        )
        assert db.query(TnCategoryProfileHint).count() == 0

    def test_null_subcategoria_duplicate_publish_does_not_crash_and_does_not_duplicate(self, db):
        """Known gotcha: `UniqueConstraint("categoria", "subcategoria",
        "profile_id")` does NOT dedupe rows where `subcategoria IS NULL` in
        Postgres (NULLs are distinct) — the writer must query-then-update
        for that case instead of relying on the constraint."""
        from app.models.tn_category_profile_hint import TnCategoryProfileHint
        from app.models.tn_measurement_profile import TnMeasurementProfile

        user = _make_user(db)
        profile = TnMeasurementProfile(name="30x20x20", weight=1, width=30, height=20, depth=20)
        db.add(profile)
        db.flush()

        kwargs1 = _publish_kwargs(categoria="Hogar", subcategoria=None, profile_id=profile.id)
        publish_product(db, user, client=self._fake_client(product_id=1), **kwargs1)
        kwargs2 = _publish_kwargs(ean="EAN-PUB-2", categoria="Hogar", subcategoria=None, profile_id=profile.id)
        publish_product(db, user, client=self._fake_client(product_id=2), **kwargs2)

        hints = db.query(TnCategoryProfileHint).all()
        assert len(hints) == 1
        assert hints[0].uso_count == 2
