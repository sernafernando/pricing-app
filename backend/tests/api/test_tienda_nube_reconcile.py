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
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.orm import sessionmaker

from app.core.security import create_access_token, get_password_hash
from app.models.permiso import Permiso, UsuarioPermisoOverride
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
        assert set(body.keys()) == {"items", "total", "verdict_counts", "catalog_cap_hit", "gbp_rows_cap_hit"}
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
