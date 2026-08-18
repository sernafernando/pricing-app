"""Integration tests for the TN reconciliation endpoints (Slice 1, read-only).

Covers: permission gate, one-shot (non-paginated) report shape with true
`verdict_counts` over the WHOLE result set, the `verdict` filter's closed
Literal validation (422 on an unknown verdict — never a silent empty
result), ban-list add/remove hides/reveals a row, GBP fetch-failure surfaces
a clear error without any partial write, TOCTOU-safe double-ban, and
empty/blank EAN validation.

Third review round changed `/reporte` from server-side paginated to a
one-shot full-set fetch (per the feature's original intent: "query it live
with a button") — sub-tab filtering and paging now happen client-side over
the already-fetched set, so the endpoint no longer accepts/returns
page/page_size.
"""

from __future__ import annotations

from contextlib import contextmanager
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.orm import sessionmaker

from app.core.security import create_access_token, get_password_hash
from app.models.permiso import Permiso, UsuarioPermisoOverride
from app.models.producto import ProductoERP, ProductoPricing
from app.models.rol import Rol
from app.models.tienda_nube_producto import TiendaNubeProducto
from app.models.tn_reconcile_banlist import TnReconcileBanlist
from app.models.usuario import AuthProvider, RolUsuario, Usuario


def _bearer(user: Usuario) -> dict[str, str]:
    token = create_access_token(data={"sub": user.username})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def _transient_auth_uses_test_db(db):
    """`GET /reporte` authenticates via `get_current_user_transient` (see
    blocker #2 — it must not ALSO hold a second `get_async_db` connection
    open across the SOAP await). That dependency opens its own session via
    `get_background_db()`, a plain contextmanager bound to the production
    `SessionLocal`/`engine` — NOT covered by the `client`/`db` fixtures'
    `app.dependency_overrides` (those only patch `get_db`/`get_async_db`).
    Patch it here so the transient auth lookup hits the SAME in-memory test
    session/transaction as everything else in the test instead of a
    separate, real, file-backed database. No commit/rollback here — the
    outer `db` fixture's transaction owns that.

    The patched session must be a SEPARATE session that actually CLOSES on
    exit, not the still-open `db` fixture session. `/reporte` runs
    `verificar_permiso` against the DETACHED user returned by transient
    auth; yielding a session that never closes lets any lazy load resolve
    silently, so the test could not fail for the very reason it exists to
    guard. Binding a fresh session to the same connection keeps visibility
    of the fixture's uncommitted rows while restoring the production
    lifecycle, exactly as `tests/unit/test_deps_transient_auth.py` does.
    """

    @contextmanager
    def _fake_background_db():
        session = sessionmaker(bind=db.connection())()
        try:
            yield session
            # Mirror the real get_background_db's "on success: commit": with
            # expire_on_commit=True the commit expires every loaded instance's
            # attributes before close. expire_all() reproduces that state
            # without a real commit (which would break the test transaction),
            # so the permission check runs against a genuinely detached,
            # expired-attribute user — the production /reporte 500 path.
            session.expire_all()
        finally:
            session.close()

    with patch("app.api.deps.get_background_db", _fake_background_db):
        yield


@pytest.fixture()
def brand_rol(db) -> Rol:
    rol = Rol(codigo="TN_TEST", nombre="TN Test", es_sistema=False, orden=99, activo=True)
    db.add(rol)
    db.flush()
    return rol


@pytest.fixture()
def perm_ver(db) -> Permiso:
    p = Permiso(
        codigo="admin.ver_tn_reconciliacion",
        nombre="Ver reconciliación Tienda Nube",
        descripcion="Access",
        categoria="administracion",
        orden=62,
        es_critico=False,
    )
    db.add(p)
    db.flush()
    return p


@pytest.fixture()
def perm_banlist(db) -> Permiso:
    p = Permiso(
        codigo="admin.gestionar_tn_reconcile_banlist",
        nombre="Gestionar banlist de reconciliación TN",
        descripcion="Manage banlist",
        categoria="administracion",
        orden=63,
        es_critico=False,
    )
    db.add(p)
    db.flush()
    return p


@pytest.fixture()
def user_no_perm(db, brand_rol) -> Usuario:
    user = Usuario(
        username="tn_no_perm",
        email="tn_no_perm@test.com",
        nombre="No Perm",
        password_hash=get_password_hash("Pass123!"),
        rol=RolUsuario.VENTAS,
        rol_id=brand_rol.id,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(user)
    db.flush()
    return user


@pytest.fixture()
def user_ver(db, brand_rol, perm_ver, perm_banlist) -> Usuario:
    user = Usuario(
        username="tn_ver",
        email="tn_ver@test.com",
        nombre="Ver User",
        password_hash=get_password_hash("Pass123!"),
        rol=RolUsuario.VENTAS,
        rol_id=brand_rol.id,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(user)
    db.flush()

    for perm in (perm_ver, perm_banlist):
        db.add(UsuarioPermisoOverride(usuario_id=user.id, permiso_id=perm.id, concedido=True))
    db.flush()
    return user


def _fake_gbp_rows():
    return [
        {"Código": "EAN-100", "tnr_id": 0, "tnr_variationID": 0, "stock": 5},
    ]


def _mixed_verdict_gbp_rows():
    """3 FALTA_PUBLICAR + 1 MAL_VINCULADO — enough to prove verdict_counts
    reflects the true total per verdict, not just what fits on a page."""
    return [
        {"Código": "FP-1", "tnr_id": 0, "tnr_variationID": 0, "stock": 0},
        {"Código": "FP-2", "tnr_id": 0, "tnr_variationID": 0, "stock": 0},
        {"Código": "FP-3", "tnr_id": 0, "tnr_variationID": 0, "stock": 0},
        {"Código": "MV-1", "tnr_id": 999, "tnr_variationID": 0, "stock": 0},
    ]


def _fetch_report(client, user, params=None, gbp_rows=None):
    with patch(
        "app.api.endpoints.tienda_nube_reconcile.fetch_gbp_report_78",
        new=AsyncMock(return_value=gbp_rows if gbp_rows is not None else _fake_gbp_rows()),
    ):
        return client.get("/api/tienda-nube-reconcile/reporte", headers=_bearer(user), params=params or {})


class TestPermissionGate:
    def test_no_permission_returns_403(self, client, db, user_no_perm):
        response = client.get("/api/tienda-nube-reconcile/reporte", headers=_bearer(user_no_perm))
        assert response.status_code == 403

    def test_with_permission_returns_200(self, client, db, user_ver):
        response = _fetch_report(client, user_ver)
        assert response.status_code == 200
        body = response.json()
        assert any(row["ean"] == "EAN-100" and row["verdict"] == "FALTA_PUBLICAR" for row in body["items"])


class TestOneShotReport:
    """`/reporte` is a one-shot fetch of the FULL verdict set — no
    page/page_size navigation params (third review round: navigating pages
    used to trigger a fresh SOAP fetch per page, reproducing the exact
    pool-exhaustion shape an earlier round fixed). `verdict_counts` MUST
    always reflect the TRUE total per verdict across the WHOLE result set."""

    def test_response_shape_has_no_pagination_params(self, client, db, user_ver):
        response = _fetch_report(client, user_ver)
        assert response.status_code == 200
        body = response.json()
        assert set(body.keys()) == {
            "items",
            "total",
            "verdict_counts",
            "catalog_cap_hit",
            "gbp_rows_cap_hit",
            "erp_cap_hit",
        }
        assert body["total"] == 1
        assert isinstance(body["items"], list)

    def test_stale_page_params_are_ignored(self, client, db, user_ver):
        """A client still passing page/page_size (stale bookmark, old
        integration) gets the SAME full result set — FastAPI silently
        ignores unrecognized query params by default, so these have no
        effect rather than erroring or resurrecting old paging semantics."""
        response = _fetch_report(client, user_ver, params={"page": 2, "page_size": 1})
        body = response.json()
        # Full set still returned — `page`/`page_size` have no effect.
        assert len(body["items"]) == 1

    def test_returns_full_verdict_set_without_pagination(self, client, db, user_ver):
        response = _fetch_report(client, user_ver, gbp_rows=_mixed_verdict_gbp_rows())
        assert response.status_code == 200
        body = response.json()
        assert len(body["items"]) == 4
        assert body["total"] == 4

    def test_verdict_counts_reflect_full_totals(self, client, db, user_ver):
        response = _fetch_report(client, user_ver, gbp_rows=_mixed_verdict_gbp_rows())
        assert response.status_code == 200
        body = response.json()
        assert body["verdict_counts"]["FALTA_PUBLICAR"] == 3
        assert body["verdict_counts"]["MAL_VINCULADO"] == 1

    def test_verdict_filter_returns_only_that_verdict_with_accurate_total(self, client, db, user_ver):
        response = _fetch_report(
            client, user_ver, params={"verdict": "FALTA_PUBLICAR"}, gbp_rows=_mixed_verdict_gbp_rows()
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 3
        assert all(item["verdict"] == "FALTA_PUBLICAR" for item in body["items"])
        # verdict_counts is unaffected by the filter — full breakdown always.
        assert body["verdict_counts"]["MAL_VINCULADO"] == 1

    def test_unknown_verdict_filter_returns_422_not_a_silent_empty_result(self, client, db, user_ver):
        """The verdict taxonomy is a closed set — a typo like
        FALTA_PUBICAR must be rejected (422), never silently accepted and
        returned as `items: [], total: 0` (indistinguishable from "there
        really are no anomalies of this type", the dangerous reading in a
        reconciliation tool)."""
        response = _fetch_report(client, user_ver, params={"verdict": "FALTA_PUBICAR"})
        assert response.status_code == 422

    def test_catalog_cap_hit_flag_present_and_false_under_the_cap(self, client, db, user_ver):
        response = _fetch_report(client, user_ver)
        assert response.status_code == 200
        assert response.json()["catalog_cap_hit"] is False

    def test_gbp_rows_cap_hit_false_under_the_cap(self, client, db, user_ver):
        """The GBP side of the join is bounded too (round 6, item 1) — under
        the cap, the flag must be false and nothing is truncated."""
        response = _fetch_report(client, user_ver, gbp_rows=_mixed_verdict_gbp_rows())
        assert response.status_code == 200
        body = response.json()
        assert body["gbp_rows_cap_hit"] is False
        assert body["total"] == 4

    def test_gbp_rows_cap_hit_true_and_rows_limited(self, client, db, user_ver):
        """Over the cap: the flag is true (never silently truncated) AND the
        actual row count is bounded to the cap — bounding memory/response
        size is the whole point, not just reporting the overage."""
        gbp_rows = [{"Código": f"FP-{i}", "tnr_id": 0, "tnr_variationID": 0, "stock": 0} for i in range(3)]
        with patch("app.api.endpoints.tienda_nube_reconcile.GBP_ROWS_CAP", 2):
            response = _fetch_report(client, user_ver, gbp_rows=gbp_rows)
        assert response.status_code == 200
        body = response.json()
        assert body["gbp_rows_cap_hit"] is True
        assert body["total"] == 2
        assert len(body["items"]) == 2


class TestNewMatchAccuracyFields:
    """Task 9: response includes POR_CORREGIR as a valid verdict, tn_presence
    per row, and product_id/variant_id on FALTA_VINCULAR rows — regression
    guard that existing OK/MAL_PUBLICADO/DUPLICADO rows still serialize."""

    def test_por_corregir_is_accepted_by_verdict_filter(self, client, db, user_ver):
        gbp_rows = [{"Código": "023942321477", "tnr_id": 0, "tnr_variationID": 0, "stock": 0}]
        response = _fetch_report(client, user_ver, params={"verdict": "POR_CORREGIR"}, gbp_rows=gbp_rows)
        assert response.status_code == 200

    def test_falta_vincular_row_carries_matched_ids(self, client, db, user_ver):
        tn = TiendaNubeProducto(product_id=42, variant_id=7, variant_sku="779123", activo=True, published=None)
        db.add(tn)
        db.flush()

        gbp_rows = [{"Código": "779123", "tnr_id": 0, "tnr_variationID": 0, "stock": 0}]
        response = _fetch_report(client, user_ver, gbp_rows=gbp_rows)

        assert response.status_code == 200
        body = response.json()
        row = next(r for r in body["items"] if r["ean"] == "779123")
        assert row["verdict"] == "FALTA_VINCULAR"
        assert row["product_id"] == 42
        assert row["variant_id"] == 7

    def test_falta_publicar_row_has_null_matched_ids(self, client, db, user_ver):
        gbp_rows = [{"Código": "000999", "tnr_id": 0, "tnr_variationID": 0, "stock": 0}]
        response = _fetch_report(client, user_ver, gbp_rows=gbp_rows)

        assert response.status_code == 200
        row = response.json()["items"][0]
        assert row["verdict"] == "FALTA_PUBLICAR"
        assert row["product_id"] is None
        assert row["variant_id"] is None

    def test_row_carries_tn_presence(self, client, db, user_ver):
        tn = TiendaNubeProducto(product_id=42, variant_id=7, variant_sku="779123", activo=True, published=True)
        db.add(tn)
        db.flush()

        gbp_rows = [{"Código": "779123", "tnr_id": 0, "tnr_variationID": 0, "stock": 0}]
        response = _fetch_report(client, user_ver, gbp_rows=gbp_rows)

        assert response.status_code == 200
        row = response.json()["items"][0]
        assert row["tn_presence"] == "published"

    def test_row_tn_presence_not_in_tn_when_nothing_resolves(self, client, db, user_ver):
        gbp_rows = [{"Código": "NOWHERE", "tnr_id": 0, "tnr_variationID": 0, "stock": 0}]
        response = _fetch_report(client, user_ver, gbp_rows=gbp_rows)

        assert response.status_code == 200
        row = response.json()["items"][0]
        assert row["tn_presence"] == "not_in_tn"

    def test_existing_mal_vinculado_row_still_serializes(self, client, db, user_ver):
        """Regression: an unrelated pre-existing verdict must serialize
        unchanged alongside the new fields (present, defaulted/null)."""
        gbp_rows = [{"Código": "123", "tnr_id": 999, "tnr_variationID": 0, "stock": 0}]
        response = _fetch_report(client, user_ver, gbp_rows=gbp_rows)

        assert response.status_code == 200
        row = response.json()["items"][0]
        assert row["verdict"] == "MAL_VINCULADO"
        assert row["product_id"] is None
        assert row["variant_id"] is None
        assert "tn_presence" in row


class TestRowReasonTaxonomy:
    """PR1: `reason`/`reason_detail` mirrored 1:1 from `ReconcileRow` onto
    `ReconcileRowResponse` (R1.5). Unaffected verdicts keep serializing with
    both fields `null` (additive-only regression guard)."""

    def test_falta_publicar_row_has_null_reason(self, client, db, user_ver):
        gbp_rows = [{"Código": "000999", "tnr_id": 0, "tnr_variationID": 0, "stock": 0}]
        response = _fetch_report(client, user_ver, gbp_rows=gbp_rows)

        assert response.status_code == 200
        row = response.json()["items"][0]
        assert row["verdict"] == "FALTA_PUBLICAR"
        assert row["reason"] is None
        assert row["reason_detail"] is None

    def test_dead_link_reason_serializes_with_operands(self, client, db, user_ver):
        tn = TiendaNubeProducto(product_id=42, variant_id=7, variant_sku="999999999999", activo=True, published=True)
        db.add(tn)
        db.flush()

        gbp_rows = [{"Código": "000000000000", "tnr_id": 999, "tnr_variationID": 88, "stock": 0}]
        response = _fetch_report(client, user_ver, gbp_rows=gbp_rows)

        assert response.status_code == 200
        row = response.json()["items"][0]
        assert row["verdict"] == "MAL_PUBLICADO"
        assert row["reason"] == "DEAD_LINK"
        assert row["reason_detail"]["claimed_tnr_id"] == 999
        assert row["reason_detail"]["claimed_tnr_variation_id"] == 88
        assert row["reason_detail"]["expected_ean"] == "000000000000"
        assert row["reason_detail"]["tn_sku_found"] is None

    def test_sku_mismatch_reason_serializes_with_operands(self, client, db, user_ver):
        tn = TiendaNubeProducto(product_id=501, variant_id=12, variant_sku="999-different", activo=True)
        db.add(tn)
        db.flush()

        gbp_rows = [{"Código": "123", "tnr_id": 501, "tnr_variationID": 12, "stock": 0}]
        response = _fetch_report(client, user_ver, gbp_rows=gbp_rows)

        assert response.status_code == 200
        row = response.json()["items"][0]
        assert row["verdict"] == "MAL_PUBLICADO"
        assert row["reason"] == "SKU_MISMATCH"
        assert row["reason_detail"]["tn_sku_found"] == "999-different"
        assert row["reason_detail"]["expected_ean"] == "123"

    def test_no_variant_link_reason_serializes(self, client, db, user_ver):
        gbp_rows = [{"Código": "123", "tnr_id": 501, "tnr_variationID": 0, "stock": 0}]
        response = _fetch_report(client, user_ver, gbp_rows=gbp_rows)

        assert response.status_code == 200
        row = response.json()["items"][0]
        assert row["verdict"] == "MAL_VINCULADO"
        assert row["reason"] == "NO_VARIANT_LINK"
        assert row["reason_detail"]["claimed_tnr_id"] == 501
        assert row["reason_detail"]["claimed_tnr_variation_id"] is None


class TestRowGbpFields:
    """Sub-slice 3c follow-up: the row response must carry the raw GBP
    product fields the publish modal needs (`ml_desc`, `images`,
    `categoria`, `subcategoria`) directly — the frontend must never need a
    second full-report `/gbp-parser` re-fetch matched by EAN client-side."""

    def test_row_carries_ml_desc_categoria_subcategoria(self, client, db, user_ver):
        gbp_rows = [
            {
                "Código": "GBP-1",
                "tnr_id": 0,
                "tnr_variationID": 0,
                "stock": 0,
                "ML_desc": "<p>Descripción</p>",
                "Categoría": "Electrónica",
                "SubCategoría": "Auriculares",
            }
        ]
        response = _fetch_report(client, user_ver, gbp_rows=gbp_rows)
        assert response.status_code == 200
        row = next(r for r in response.json()["items"] if r["ean"] == "GBP-1")
        assert row["ml_desc"] == "<p>Descripción</p>"
        assert row["categoria"] == "Electrónica"
        assert row["subcategoria"] == "Auriculares"

    def test_row_images_filters_empty_slots_and_preserves_order(self, client, db, user_ver):
        gbp_rows = [
            {
                "Código": "GBP-2",
                "tnr_id": 0,
                "tnr_variationID": 0,
                "stock": 0,
                "image1": "https://x/1.jpg",
                "image2": "",
                "image3": None,
                "image4": "https://x/4.jpg",
            }
        ]
        response = _fetch_report(client, user_ver, gbp_rows=gbp_rows)
        assert response.status_code == 200
        row = next(r for r in response.json()["items"] if r["ean"] == "GBP-2")
        assert row["images"] == ["https://x/1.jpg", "https://x/4.jpg"]

    def test_row_gbp_fields_default_to_none_or_empty_when_missing(self, client, db, user_ver):
        response = _fetch_report(client, user_ver)  # _fake_gbp_rows() has no ML_desc/images/categoría
        assert response.status_code == 200
        row = next(r for r in response.json()["items"] if r["ean"] == "EAN-100")
        assert row["ml_desc"] is None
        assert row["categoria"] is None
        assert row["subcategoria"] is None
        assert row["images"] == []

    def test_row_carries_erp_desc_from_gbp_descripcion_column(self, client, db, user_ver):
        """PR5: report 78's `Descripción` column is the ERP description — it
        covers rows that have no `ML_title` at all (never-published-to-ML
        products), which is exactly the identity fallback this field feeds."""
        gbp_rows = [
            {
                "Código": "GBP-3",
                "tnr_id": 0,
                "tnr_variationID": 0,
                "stock": 0,
                "Descripción": "Auricular inalambrico modelo X",
            }
        ]
        response = _fetch_report(client, user_ver, gbp_rows=gbp_rows)
        assert response.status_code == 200
        row = next(r for r in response.json()["items"] if r["ean"] == "GBP-3")
        assert row["erp_desc"] == "Auricular inalambrico modelo X"

    def test_row_erp_desc_is_none_when_missing(self, client, db, user_ver):
        response = _fetch_report(client, user_ver)  # _fake_gbp_rows() has no Descripción key
        assert response.status_code == 200
        row = next(r for r in response.json()["items"] if r["ean"] == "EAN-100")
        assert row["erp_desc"] is None


class TestBanlist:
    def test_ban_hides_row_and_unban_reveals_it(self, client, db, user_ver):
        before = _fetch_report(client, user_ver)
        assert any(row["ean"] == "EAN-100" for row in before.json()["items"])

        ban_response = client.post(
            "/api/tienda-nube-reconcile/banear",
            json={"ean": "EAN-100", "motivo": "test"},
            headers=_bearer(user_ver),
        )
        assert ban_response.status_code == 200
        assert db.query(TnReconcileBanlist).filter(TnReconcileBanlist.ean == "EAN-100").count() == 1

        after_ban = _fetch_report(client, user_ver)
        assert not any(row["ean"] == "EAN-100" for row in after_ban.json()["items"])

        banlist_id = ban_response.json()["banlist_id"]
        unban_response = client.post(
            "/api/tienda-nube-reconcile/desbanear",
            json={"banlist_id": banlist_id},
            headers=_bearer(user_ver),
        )
        assert unban_response.status_code == 200
        assert db.query(TnReconcileBanlist).count() == 0

        after_unban = _fetch_report(client, user_ver)
        assert any(row["ean"] == "EAN-100" for row in after_unban.json()["items"])

    def test_ban_requires_permission(self, client, db, user_no_perm):
        response = client.post(
            "/api/tienda-nube-reconcile/banear",
            json={"ean": "EAN-100"},
            headers=_bearer(user_no_perm),
        )
        assert response.status_code == 403

    def test_double_ban_returns_400_not_500(self, client, db, user_ver):
        """TOCTOU guard: a concurrent double-ban must surface the intended
        400 ('already banned'), never an unhandled IntegrityError 500."""
        first = client.post(
            "/api/tienda-nube-reconcile/banear",
            json={"ean": "DUPBAN"},
            headers=_bearer(user_ver),
        )
        assert first.status_code == 200

        second = client.post(
            "/api/tienda-nube-reconcile/banear",
            json={"ean": "DUPBAN"},
            headers=_bearer(user_ver),
        )
        assert second.status_code == 400
        assert db.query(TnReconcileBanlist).filter(TnReconcileBanlist.ean == "DUPBAN").count() == 1

    def test_blank_ean_is_rejected(self, client, db, user_ver):
        response = client.post(
            "/api/tienda-nube-reconcile/banear",
            json={"ean": ""},
            headers=_bearer(user_ver),
        )
        assert response.status_code == 422
        assert db.query(TnReconcileBanlist).count() == 0

    def test_whitespace_only_ean_is_rejected(self, client, db, user_ver):
        response = client.post(
            "/api/tienda-nube-reconcile/banear",
            json={"ean": "   "},
            headers=_bearer(user_ver),
        )
        assert response.status_code == 422
        assert db.query(TnReconcileBanlist).count() == 0

    def test_ean_is_stripped_before_storing(self, client, db, user_ver):
        response = client.post(
            "/api/tienda-nube-reconcile/banear",
            json={"ean": "  PADDED-EAN  "},
            headers=_bearer(user_ver),
        )
        assert response.status_code == 200
        stored = db.query(TnReconcileBanlist).filter(TnReconcileBanlist.ean == "PADDED-EAN").first()
        assert stored is not None

    def test_get_baneados_lists_active_bans(self, client, db, user_ver):
        client.post(
            "/api/tienda-nube-reconcile/banear",
            json={"ean": "LISTME", "motivo": "reason"},
            headers=_bearer(user_ver),
        )

        response = client.get("/api/tienda-nube-reconcile/baneados", headers=_bearer(user_ver))
        assert response.status_code == 200
        body = response.json()
        assert any(entry["ean"] == "LISTME" and entry["motivo"] == "reason" for entry in body)

    def test_get_baneados_requires_permission(self, client, db, user_no_perm):
        response = client.get("/api/tienda-nube-reconcile/baneados", headers=_bearer(user_no_perm))
        assert response.status_code == 403

    def test_unban_removed_from_baneados_list(self, client, db, user_ver):
        ban_response = client.post(
            "/api/tienda-nube-reconcile/banear",
            json={"ean": "TOREMOVE"},
            headers=_bearer(user_ver),
        )
        banlist_id = ban_response.json()["banlist_id"]

        client.post(
            "/api/tienda-nube-reconcile/desbanear",
            json={"banlist_id": banlist_id},
            headers=_bearer(user_ver),
        )

        response = client.get("/api/tienda-nube-reconcile/baneados", headers=_bearer(user_ver))
        assert not any(entry["ean"] == "TOREMOVE" for entry in response.json())

    def test_bulk_unban_via_sequential_calls(self, client, db, user_ver):
        """Bulk unban is a frontend-orchestrated sequence of individual
        /desbanear calls (mirrors ItemsSinMLA.jsx's desbanearSeleccionados
        pattern) — no dedicated bulk endpoint exists. Confirms the single
        endpoint tolerates being called repeatedly in a loop."""
        ids = []
        for ean in ("BULK-1", "BULK-2", "BULK-3"):
            resp = client.post(
                "/api/tienda-nube-reconcile/banear",
                json={"ean": ean},
                headers=_bearer(user_ver),
            )
            ids.append(resp.json()["banlist_id"])

        for banlist_id in ids:
            resp = client.post(
                "/api/tienda-nube-reconcile/desbanear",
                json={"banlist_id": banlist_id},
                headers=_bearer(user_ver),
            )
            assert resp.status_code == 200

        assert db.query(TnReconcileBanlist).count() == 0


@pytest.fixture()
def perm_publicacion(db) -> Permiso:
    p = Permiso(
        codigo="admin.gestionar_tn_publicacion",
        nombre="Gestionar publicación Tienda Nube",
        descripcion="Publish/unpublish",
        categoria="administracion",
        orden=64,
        es_critico=True,
    )
    db.add(p)
    db.flush()
    return p


@pytest.fixture()
def user_publicacion(db, brand_rol, perm_publicacion) -> Usuario:
    user = Usuario(
        username="tn_pub",
        email="tn_pub@test.com",
        nombre="Pub User",
        password_hash=get_password_hash("Pass123!"),
        rol=RolUsuario.VENTAS,
        rol_id=brand_rol.id,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(user)
    db.flush()
    db.add(UsuarioPermisoOverride(usuario_id=user.id, permiso_id=perm_publicacion.id, concedido=True))
    db.flush()
    return user


class TestDespublicarEndpoint:
    def test_requires_permission(self, client, db, user_no_perm):
        response = client.post(
            "/api/tienda-nube-reconcile/despublicar",
            json={"product_id": 555},
            headers=_bearer(user_no_perm),
        )
        assert response.status_code == 403

    def test_successful_unpublish_returns_submitted_and_audits(self, client, db, user_publicacion):
        producto = TiendaNubeProducto(
            product_id=555, product_name="Test", variant_id=1, variant_sku="SKU-1", published=True
        )
        db.add(producto)
        db.commit()

        fake_outcome = {"submitted": True, "status": "submitted", "status_code": 200}
        with patch("app.api.endpoints.tienda_nube_reconcile.unpublish_product", return_value=fake_outcome) as mocked:
            response = client.post(
                "/api/tienda-nube-reconcile/despublicar",
                json={"product_id": 555},
                headers=_bearer(user_publicacion),
            )
        assert response.status_code == 200
        body = response.json()
        assert body["submitted"] is True
        assert body["status"] == "submitted"
        mocked.assert_called_once()

    def test_not_found_product_returns_200_with_rejected_status(self, client, db, user_publicacion):
        fake_outcome = {"submitted": False, "status": "rejected_not_found", "detail": "no rows"}
        with patch("app.api.endpoints.tienda_nube_reconcile.unpublish_product", return_value=fake_outcome):
            response = client.post(
                "/api/tienda-nube-reconcile/despublicar",
                json={"product_id": 999999},
                headers=_bearer(user_publicacion),
            )
        assert response.status_code == 200
        assert response.json()["status"] == "rejected_not_found"


class TestPublicarEndpoint:
    def _payload(self, **overrides):
        payload = {
            "ean": "EAN-PUB-1",
            "product_data": {"name": {"es": "Test Product"}},
            "category_id": 123,
            "description_html": "<p>Descripcion</p>",
            "image_srcs": ["https://cdn.example.com/img1.jpg"],
        }
        payload.update(overrides)
        return payload

    def test_requires_permission(self, client, db, user_no_perm):
        response = client.post(
            "/api/tienda-nube-reconcile/publicar",
            json=self._payload(),
            headers=_bearer(user_no_perm),
        )
        assert response.status_code == 403

    def test_successful_publish_returns_submitted_and_audits(self, client, db, user_publicacion):
        fake_outcome = {
            "submitted": True,
            "status": "submitted",
            "product_id": 999,
            "skipped_image_srcs": [],
        }
        with patch("app.api.endpoints.tienda_nube_reconcile.publish_product", return_value=fake_outcome) as mocked:
            response = client.post(
                "/api/tienda-nube-reconcile/publicar",
                json=self._payload(),
                headers=_bearer(user_publicacion),
            )
        assert response.status_code == 200
        body = response.json()
        assert body["submitted"] is True
        assert body["status"] == "submitted"
        assert body["product_id"] == 999
        mocked.assert_called_once()

    def test_already_published_returns_200_with_that_status(self, client, db, user_publicacion):
        fake_outcome = {"submitted": False, "status": "already_published", "detail": "exists"}
        with patch("app.api.endpoints.tienda_nube_reconcile.publish_product", return_value=fake_outcome):
            response = client.post(
                "/api/tienda-nube-reconcile/publicar",
                json=self._payload(),
                headers=_bearer(user_publicacion),
            )
        assert response.status_code == 200
        assert response.json()["status"] == "already_published"

    def test_rejected_invalid_price_surfaces_as_400_not_200(self, client, db, user_publicacion):
        """Slice 2 (publish price): unlike every other `publish_product`
        rejection status (returned as 200 with `submitted=False`), an
        invalid submitted price is a hard validation failure — 4xx."""
        fake_outcome = {
            "submitted": False,
            "status": "rejected_invalid_price",
            "detail": "El producto no tiene un precio de publicación.",
        }
        with patch("app.api.endpoints.tienda_nube_reconcile.publish_product", return_value=fake_outcome):
            response = client.post(
                "/api/tienda-nube-reconcile/publicar",
                json=self._payload(product_data={"name": {"es": "Test Product"}}),
                headers=_bearer(user_publicacion),
            )
        assert response.status_code == 400

    def test_offset_percent_and_price_base_source_are_forwarded_to_publish_product(self, client, db, user_publicacion):
        fake_outcome = {"submitted": True, "status": "submitted", "product_id": 1, "skipped_image_srcs": []}
        with patch("app.api.endpoints.tienda_nube_reconcile.publish_product", return_value=fake_outcome) as mocked:
            response = client.post(
                "/api/tienda-nube-reconcile/publicar",
                json=self._payload(
                    product_data={"name": {"es": "Test Product"}, "price": "1250.00"},
                    offset_percent=25,
                    price_base_source="web_transferencia",
                ),
                headers=_bearer(user_publicacion),
            )
        assert response.status_code == 200
        _, kwargs = mocked.call_args
        assert kwargs["offset_percent"] == 25
        assert kwargs["price_base_source"] == "web_transferencia"

    def test_blank_ean_is_rejected(self, client, db, user_publicacion):
        response = client.post(
            "/api/tienda-nube-reconcile/publicar",
            json=self._payload(ean=""),
            headers=_bearer(user_publicacion),
        )
        assert response.status_code == 422

    def test_empty_image_srcs_is_valid(self, client, db, user_publicacion):
        """No images is allowed (some products may legitimately have none
        yet) — this endpoint never invents an image."""
        fake_outcome = {"submitted": True, "status": "submitted", "product_id": 1, "skipped_image_srcs": []}
        with patch("app.api.endpoints.tienda_nube_reconcile.publish_product", return_value=fake_outcome):
            response = client.post(
                "/api/tienda-nube-reconcile/publicar",
                json=self._payload(image_srcs=[]),
                headers=_bearer(user_publicacion),
            )
        assert response.status_code == 200


class TestCategoriaSugeridaEndpoint:
    """Sub-slice 3b — embedder-assisted TN category suggestion. Reuses
    `admin.gestionar_tn_publicacion` (same write-gate — this feeds the
    publish flow), never raises on embedder unavailability."""

    def test_requires_permission(self, client, db, user_no_perm):
        response = client.post(
            "/api/tienda-nube-reconcile/categoria-sugerida",
            json={"category_text": "Celulares"},
            headers=_bearer(user_no_perm),
        )
        assert response.status_code == 403

    def test_blank_category_text_returns_422(self, client, db, user_publicacion):
        response = client.post(
            "/api/tienda-nube-reconcile/categoria-sugerida",
            json={"category_text": "   "},
            headers=_bearer(user_publicacion),
        )
        assert response.status_code == 422

    def test_successful_suggestion_returns_top_and_list(self, client, db, user_publicacion):
        fake_result = {
            "suggestions": [
                {"tn_category_id": 2, "category_path_text": "Electrónica > Celulares", "similarity": 0.9},
                {"tn_category_id": 1, "category_path_text": "Electrónica", "similarity": 0.7},
            ],
            "top": {"tn_category_id": 2, "category_path_text": "Electrónica > Celulares", "similarity": 0.9},
        }
        with patch("app.api.endpoints.tienda_nube_reconcile.suggest_category", return_value=fake_result) as mocked:
            response = client.post(
                "/api/tienda-nube-reconcile/categoria-sugerida",
                json={"category_text": "Celulares y Smartphones"},
                headers=_bearer(user_publicacion),
            )
        assert response.status_code == 200
        body = response.json()
        assert body["top"]["tn_category_id"] == 2
        assert len(body["suggestions"]) == 2
        mocked.assert_called_once()

    def test_embedder_unavailable_returns_200_with_empty_suggestion(self, client, db, user_publicacion):
        fake_result = {"suggestions": [], "top": None}
        with patch("app.api.endpoints.tienda_nube_reconcile.suggest_category", return_value=fake_result):
            response = client.post(
                "/api/tienda-nube-reconcile/categoria-sugerida",
                json={"category_text": "Celulares y Smartphones"},
                headers=_bearer(user_publicacion),
            )
        assert response.status_code == 200
        body = response.json()
        assert body["suggestions"] == []
        assert body["top"] is None


class TestReporteStockExposed:
    """Slice 4: `stock` (already parsed for the DESPUBLICAR check but
    discarded before this slice) is now surfaced on the response row so the
    frontend can render/sort it."""

    def test_stock_is_present_and_numeric(self, client, db, user_ver):
        # Real GBP key is `Stock_Disponible`, not `stock` (verified live 2026-07-30).
        gbp_rows = [{"Código": "EAN-STOCK", "tnr_id": 0, "tnr_variationID": 0, "Stock_Disponible": 7}]
        response = _fetch_report(client, user_ver, gbp_rows=gbp_rows)
        assert response.status_code == 200
        row = response.json()["items"][0]
        assert row["stock"] == 7

    def test_stock_absent_is_serialized_as_json_null_not_zero(self, client, db, user_ver):
        gbp_rows = [{"Código": "EAN-NOSTOCK", "tnr_id": 0, "tnr_variationID": 0}]
        response = _fetch_report(client, user_ver, gbp_rows=gbp_rows)
        assert response.status_code == 200
        row = response.json()["items"][0]
        assert row["stock"] is None


class TestReportePublishPriceFieldsExposed:
    """Slice 2 (publish price, money path): the bulk `productos_erp`/
    `productos_pricing` join surfaces `precio_web_transferencia`/
    `participa_web_transferencia`/`precio_lista_ml` per row, keyed by the
    GBP `Item_ID`. Both prices are serialized as STRINGS."""

    def test_price_fields_resolve_via_item_id_join(self, client, db, user_ver):
        producto_erp = ProductoERP(item_id=555, codigo="EAN-PRICE", descripcion="Producto de prueba")
        db.add(producto_erp)
        db.flush()
        db.add(
            ProductoPricing(
                item_id=555,
                precio_web_transferencia=Decimal("1000.00"),
                participa_web_transferencia=True,
                precio_lista_ml=900.0,
            )
        )
        db.commit()

        gbp_rows = [{"Código": "EAN-PRICE", "tnr_id": 0, "tnr_variationID": 0, "Stock_Disponible": 5, "Item_ID": "555"}]
        response = _fetch_report(client, user_ver, gbp_rows=gbp_rows)
        assert response.status_code == 200
        row = response.json()["items"][0]
        assert row["precio_web_transferencia"] == "1000.00"
        assert row["participa_web_transferencia"] is True
        assert row["precio_lista_ml"] == "900.0"

    def test_unresolved_item_id_exposes_none_never_fabricates(self, client, db, user_ver):
        gbp_rows = [
            {"Código": "EAN-NOPRICE", "tnr_id": 0, "tnr_variationID": 0, "Stock_Disponible": 5, "Item_ID": "999999"}
        ]
        response = _fetch_report(client, user_ver, gbp_rows=gbp_rows)
        assert response.status_code == 200
        row = response.json()["items"][0]
        assert row["precio_web_transferencia"] is None
        assert row["participa_web_transferencia"] is None
        assert row["precio_lista_ml"] is None


class TestReconcilePublishFieldsPassthrough:
    """PR-3 (tn-publish-core foundation, PC1/PC2/PC3): the row response now
    carries the full publish field set — sourced through the strict
    extract -> resolve conversion layer — replacing the earlier discard
    where the row only carried a hand-picked subset of `gbp_row`. Only
    emitted for publish-candidate verdicts (FALTA_PUBLICAR/FALTA_VINCULAR)
    to control response payload growth across the other ~800 rows."""

    def _complete_gbp_row(self, **overrides) -> dict:
        row = {
            "Código": "EAN-FULL",
            "tnr_id": 0,
            "tnr_variationID": 0,
            "Stock_Disponible": "5",
            "weight": "1000.000000000",
            "wide": "2.000000000",
            "large": "13.000000000",
            "height": "8.000000000",
            "Marca": "ADATA",
            "coslis_price": "100.00",
            "iclh_price": "95.00",
            "Moneda_Costo": "USD",
            "tnr_lastPromotionalPrice": "45000.00",
        }
        row.update(overrides)
        return row

    def test_falta_publicar_row_carries_full_field_set_converted(self, client, db, user_ver):
        response = _fetch_report(client, user_ver, gbp_rows=[self._complete_gbp_row()])

        assert response.status_code == 200
        row = response.json()["items"][0]
        assert row["verdict"] == "FALTA_PUBLICAR"
        assert row["marca"] == "ADATA"
        assert row["cost"] == "100.00"
        assert row["barcode"] == "EAN-FULL"
        assert row["promotional_price"] == "45000.00"
        assert row["weight_kg"] == pytest.approx(1.000)
        assert row["width_cm"] == pytest.approx(13.0)
        assert row["depth_cm"] == pytest.approx(2.0)
        assert row["height_cm"] == pytest.approx(8.0)

    def test_falta_vincular_row_also_carries_full_field_set(self, client, db, user_ver):
        tn = TiendaNubeProducto(product_id=61, variant_id=9, variant_sku="EAN-FULL-2", activo=True)
        db.add(tn)
        db.flush()

        gbp_rows = [self._complete_gbp_row(Código="EAN-FULL-2")]
        response = _fetch_report(client, user_ver, gbp_rows=gbp_rows)

        assert response.status_code == 200
        row = response.json()["items"][0]
        assert row["verdict"] == "FALTA_VINCULAR"
        assert row["marca"] == "ADATA"
        assert row["weight_kg"] == pytest.approx(1.000)

    def test_non_candidate_verdict_leaves_publish_fields_null(self, client, db, user_ver):
        """MAL_VINCULADO is a data-quality anomaly, not a publish candidate
        — the new fields must stay `null` even when the GBP row is
        complete, so the payload-growth guardrail actually holds."""
        gbp_rows = [self._complete_gbp_row(Código="123", tnr_id=501, tnr_variationID=0)]
        response = _fetch_report(client, user_ver, gbp_rows=gbp_rows)

        assert response.status_code == 200
        row = response.json()["items"][0]
        assert row["verdict"] == "MAL_VINCULADO"
        assert row["marca"] is None
        assert row["cost"] is None
        assert row["barcode"] is None
        assert row["promotional_price"] is None
        assert row["weight_kg"] is None
        assert row["width_cm"] is None
        assert row["depth_cm"] is None
        assert row["height_cm"] is None

    def test_absent_measurement_serializes_as_null_not_zero(self, client, db, user_ver):
        gbp_rows = [self._complete_gbp_row(weight="0.000000000", height="0.000000000")]
        response = _fetch_report(client, user_ver, gbp_rows=gbp_rows)

        assert response.status_code == 200
        row = response.json()["items"][0]
        assert row["weight_kg"] is None
        assert row["height_cm"] is None
        # A real, present dimension on the SAME row must not be swept into
        # `None` by the absent ones — proves the per-field Absent handling,
        # not a blanket "something was blank so null everything" fallback.
        assert row["width_cm"] == pytest.approx(13.0)

    def test_row_missing_a_required_key_degrades_gracefully_no_500(self, client, db, user_ver):
        """A publish-candidate row with an incomplete GBP payload (e.g. an
        older/partial fixture, or a live ERP column rename affecting the
        whole report) MUST NOT crash the one-shot report for every other
        row. `extract_report_row` still raises internally (proven directly
        in `test_tn_publish_core_extract.py`); this test proves the
        endpoint-level wiring catches it per-row and leaves the new fields
        `null` rather than propagating a 500 across the whole response.

        D13: the broken row must ALSO carry an explicit, non-null
        `publish_fields_error` naming the missing key — distinguishable
        from a row whose measurements are simply absent — and a healthy
        row in the SAME response must stay entirely unaffected
        (`publish_fields_error is None`, fields populated)."""
        incomplete_row = {"Código": "EAN-PARTIAL", "tnr_id": 0, "tnr_variationID": 0}
        healthy_row = self._complete_gbp_row(Código="EAN-HEALTHY", tnr_id=0, tnr_variationID=0)

        response = _fetch_report(client, user_ver, gbp_rows=[incomplete_row, healthy_row])

        assert response.status_code == 200
        items = {row["barcode"] or row["ean"]: row for row in response.json()["items"]}
        broken = items["EAN-PARTIAL"]
        assert broken["verdict"] == "FALTA_PUBLICAR"
        assert broken["marca"] is None
        assert broken["weight_kg"] is None
        assert broken["publish_fields_error"] is not None
        assert "weight" in broken["publish_fields_error"]

        healthy = items["EAN-HEALTHY"]
        assert healthy["verdict"] == "FALTA_PUBLICAR"
        assert healthy["marca"] == "ADATA"
        assert healthy["publish_fields_error"] is None

    def test_row_with_unparseable_measurement_value_degrades_gracefully_no_500(self, client, db, user_ver):
        """A publish-candidate row where GBP sends a non-numeric, non-blank
        value for a measurement field (e.g. `weight = "N/A"`, a broken GBP
        schema/data export) MUST NOT 500 the whole report. Before the fix,
        `_is_absent_value` treated the junk value as "present", so it flowed
        straight into `float(...)` in the conversion layer and raised an
        uncaught `ValueError` `build_publish_fields` did not catch — the
        same failure mode `test_row_missing_a_required_key_degrades_
        gracefully_no_500` covers, reached through the VALUE path instead
        of the KEY path.

        Junk is NOT absence (S1's core distinction): a genuinely absent
        measurement (`weight = "0.000000000"`) resolves to `None`; a junk
        measurement (`weight = "N/A"`) must surface as an explicit,
        non-null `publish_fields_error` naming both the offending field
        and the offending raw value, distinguishable from plain absence —
        and a healthy row in the SAME response must stay entirely
        unaffected."""
        junk_weight_row = self._complete_gbp_row(Código="EAN-JUNK-WEIGHT", weight="N/A")
        junk_dimension_row = self._complete_gbp_row(Código="EAN-JUNK-DIM", large="not-a-number")
        healthy_row = self._complete_gbp_row(Código="EAN-HEALTHY-2")

        response = _fetch_report(client, user_ver, gbp_rows=[junk_weight_row, junk_dimension_row, healthy_row])

        assert response.status_code == 200
        items = {row["barcode"] or row["ean"]: row for row in response.json()["items"]}

        junk_weight = items["EAN-JUNK-WEIGHT"]
        assert junk_weight["verdict"] == "FALTA_PUBLICAR"
        assert junk_weight["weight_kg"] is None
        assert junk_weight["publish_fields_error"] is not None
        assert "weight" in junk_weight["publish_fields_error"]
        assert "N/A" in junk_weight["publish_fields_error"]

        junk_dimension = items["EAN-JUNK-DIM"]
        assert junk_dimension["verdict"] == "FALTA_PUBLICAR"
        assert junk_dimension["width_cm"] is None
        assert junk_dimension["publish_fields_error"] is not None
        assert "large" in junk_dimension["publish_fields_error"]

        healthy = items["EAN-HEALTHY-2"]
        assert healthy["verdict"] == "FALTA_PUBLICAR"
        assert healthy["marca"] == "ADATA"
        assert healthy["publish_fields_error"] is None


class TestReporteMlTitleAndAdminUrl:
    """Response fields the UI rebuild needs: `ml_title` (editable title field
    source) and `tn_admin_url` (link to the matched TN product in the TN
    admin), per row."""

    def test_ml_title_is_taken_from_gbp_ml_title_field(self, client, db, user_ver):
        gbp_rows = [
            {"Código": "EAN-TITLE", "tnr_id": 0, "tnr_variationID": 0, "stock": 5, "ML_title": "Titulo GBP"},
        ]
        response = _fetch_report(client, user_ver, gbp_rows=gbp_rows)
        assert response.status_code == 200
        row = response.json()["items"][0]
        assert row["ml_title"] == "Titulo GBP"

    def test_ml_title_is_none_when_missing(self, client, db, user_ver):
        response = _fetch_report(client, user_ver)
        assert response.status_code == 200
        row = response.json()["items"][0]
        assert row["ml_title"] is None

    def test_tn_admin_url_present_for_matched_tn_product(self, client, db, user_ver, monkeypatch):
        monkeypatch.setattr(
            "app.api.endpoints.tienda_nube_reconcile.settings.TN_ADMIN_BASE_URL",
            "https://gaussonline3.mitiendanube.com/admin/products",
        )
        producto = TiendaNubeProducto(
            product_id=777, product_name="Test", variant_id=1, variant_sku="EAN-MATCH", published=True
        )
        db.add(producto)
        db.commit()
        gbp_rows = [{"Código": "EAN-MATCH", "tnr_id": 0, "tnr_variationID": 0, "stock": 5}]

        response = _fetch_report(client, user_ver, gbp_rows=gbp_rows)
        assert response.status_code == 200
        row = response.json()["items"][0]
        assert row["tn_matches"][0]["tn_admin_url"] == "https://gaussonline3.mitiendanube.com/admin/products/777"

    def test_tn_admin_url_none_when_base_url_unset(self, client, db, user_ver):
        # Real default (TN_ADMIN_BASE_URL is None / unset in .env): a matched
        # product gets NO "Editar en TN" link — never a fabricated URL that 404s.
        producto = TiendaNubeProducto(
            product_id=888, product_name="Test", variant_id=1, variant_sku="EAN-NOURL", published=True
        )
        db.add(producto)
        db.commit()
        gbp_rows = [{"Código": "EAN-NOURL", "tnr_id": 0, "tnr_variationID": 0, "stock": 5}]

        response = _fetch_report(client, user_ver, gbp_rows=gbp_rows)
        assert response.status_code == 200
        row = response.json()["items"][0]
        assert row["tn_matches"][0]["tn_admin_url"] is None

    def test_tn_admin_url_absent_when_no_tn_match(self, client, db, user_ver):
        response = _fetch_report(client, user_ver)
        assert response.status_code == 200
        row = response.json()["items"][0]
        # No TN product resolves → no matches → no per-match admin link exists.
        assert row["tn_matches"] == []


class TestCategoriasEndpoint:
    """Category search-by-name for the modal's manual category picker."""

    def test_requires_permission(self, client, db, user_no_perm):
        response = client.get(
            "/api/tienda-nube-reconcile/categorias", params={"q": "cel"}, headers=_bearer(user_no_perm)
        )
        assert response.status_code == 403

    def test_happy_path_case_insensitive_substring_match(self, client, db, user_publicacion):
        from app.models.tn_category_embedding import TnCategoryEmbedding

        db.add(
            TnCategoryEmbedding(
                tn_category_id=1,
                category_path_text="Electrónica > Celulares y Smartphones",
                embedding=[0.0] * 384,
            )
        )
        db.add(
            TnCategoryEmbedding(
                tn_category_id=2,
                category_path_text="Hogar > Muebles",
                embedding=[0.0] * 384,
            )
        )
        db.commit()

        response = client.get(
            "/api/tienda-nube-reconcile/categorias", params={"q": "celulares"}, headers=_bearer(user_publicacion)
        )
        assert response.status_code == 200
        body = response.json()
        assert len(body) == 1
        assert body[0]["tn_category_id"] == 1
        assert body[0]["category_path"] == "Electrónica > Celulares y Smartphones"

    def test_empty_query_returns_empty_list(self, client, db, user_publicacion):
        response = client.get(
            "/api/tienda-nube-reconcile/categorias", params={"q": ""}, headers=_bearer(user_publicacion)
        )
        assert response.status_code == 200
        assert response.json() == []

    def test_limit_param_bounds_results(self, client, db, user_publicacion):
        from app.models.tn_category_embedding import TnCategoryEmbedding

        for i in range(5):
            db.add(
                TnCategoryEmbedding(
                    tn_category_id=100 + i,
                    category_path_text=f"Categoria Test {i}",
                    embedding=[0.0] * 384,
                )
            )
        db.commit()

        response = client.get(
            "/api/tienda-nube-reconcile/categorias",
            params={"q": "categoria test", "limit": 2},
            headers=_bearer(user_publicacion),
        )
        assert response.status_code == 200
        assert len(response.json()) == 2


class TestGracefulDegradation:
    def test_gbp_fetch_failure_returns_clear_error_no_partial_write(self, client, db, user_ver):
        from app.services.tn_reconciliation_service import GBPFetchError

        with patch(
            "app.api.endpoints.tienda_nube_reconcile.fetch_gbp_report_78",
            new=AsyncMock(side_effect=GBPFetchError("SOAP timeout")),
        ):
            response = client.get("/api/tienda-nube-reconcile/reporte", headers=_bearer(user_ver))

        assert response.status_code == 502
        assert "SOAP timeout" in response.json()["error"]["message"]
        # A failed load never creates a banlist row — asserting against the
        # table this endpoint actually writes to (not an unrelated table
        # that would always read 0 and prove nothing).
        assert db.query(TnReconcileBanlist).count() == 0
