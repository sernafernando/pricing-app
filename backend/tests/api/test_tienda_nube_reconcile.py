"""Integration tests for the TN reconciliation endpoints (Slice 1, read-only).

Covers: permission gate, paginated report shape, ban-list add/remove hides/
reveals a row, GBP fetch-failure surfaces a clear error without any partial
write, TOCTOU-safe double-ban, and empty/blank EAN validation.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.core.security import create_access_token, get_password_hash
from app.models.permiso import Permiso, UsuarioPermisoOverride
from app.models.rol import Rol
from app.models.tn_marked_for_deletion import TnMarkedForDeletion
from app.models.tn_reconcile_banlist import TnReconcileBanlist
from app.models.usuario import AuthProvider, RolUsuario, Usuario


def _bearer(user: Usuario) -> dict[str, str]:
    token = create_access_token(data={"sub": user.username})
    return {"Authorization": f"Bearer {token}"}


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


def _fetch_report(client, user, params=None):
    with patch(
        "app.api.endpoints.tienda_nube_reconcile.fetch_gbp_report_78",
        new=AsyncMock(return_value=_fake_gbp_rows()),
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


class TestPagination:
    """The report is paginated per repo convention (page/page_size), and the
    internal TN catalog query has an explicit ceiling — see B2 in the review.
    """

    def test_response_shape_includes_pagination_metadata(self, client, db, user_ver):
        response = _fetch_report(client, user_ver)
        assert response.status_code == 200
        body = response.json()
        assert set(body.keys()) == {"items", "total", "page", "page_size"}
        assert body["total"] == 1
        assert body["page"] == 1
        assert isinstance(body["items"], list)

    def test_page_size_is_capped(self, client, db, user_ver):
        response = _fetch_report(client, user_ver, params={"page_size": 10000})
        assert response.status_code == 422  # over the enforced le=200 ceiling

    def test_page_beyond_total_returns_empty_items(self, client, db, user_ver):
        response = _fetch_report(client, user_ver, params={"page": 99, "page_size": 50})
        assert response.status_code == 200
        body = response.json()
        assert body["items"] == []
        assert body["total"] == 1


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
        # A failed load never creates a banlist or mark-for-deletion row —
        # asserting against the tables this endpoint actually writes to
        # (not an unrelated table that would always read 0 and prove nothing).
        assert db.query(TnReconcileBanlist).count() == 0
        assert db.query(TnMarkedForDeletion).count() == 0
