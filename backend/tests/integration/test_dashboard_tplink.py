"""
Integration tests for the TP-Link brand dashboard endpoints.

Security contract verified here:
1. Permission gate (403 without dashboard_tplink.ver, 200 with it)
2. Store lock: client cannot override store; only store-2645 data returned
3. PM/marca bypass: brand user with no MarcaPM rows still gets data
4. Margin masking: sensitive fields ABSENT (not zero) when .ver_ganancia missing
5. Margin present: sensitive fields present when .ver_ganancia granted
6. Offsets absent always (no permission unlocks them)
7. SUPERADMIN full access (has all permissions by default)

TDD order followed: gate (RED) → scaffold (GREEN) → store-lock/masking (RED) →
handlers (GREEN) → verify all GREEN.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.core.security import create_access_token, get_password_hash
from app.models.ml_venta_metrica import MLVentaMetrica
from app.models.permiso import Permiso
from app.models.rol import Rol
from app.models.usuario import AuthProvider, RolUsuario, Usuario

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TPLINK_STORE_ID = 2645
OTHER_STORE_ID = 57997


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _bearer(user: Usuario) -> dict[str, str]:
    token = create_access_token(data={"sub": user.username})
    return {"Authorization": f"Bearer {token}"}


_venta_counter = 0


def _make_venta(
    db,
    *,
    store_id: int = TPLINK_STORE_ID,
    monto_total: float = 10000.0,
    ganancia: float = 2000.0,
    costo_total_sin_iva: float = 6000.0,
    costo_envio_ml: float = 500.0,
    comision_ml: float = 1500.0,
    monto_limpio: float = 8000.0,
    tipo_logistica: str = "flex",
    categoria: str = "Networking",
    marca: str = "TP-Link",
    offset_flex: float = 0.0,
) -> MLVentaMetrica:
    """Seed one MLVentaMetrica row."""
    global _venta_counter
    _venta_counter += 1
    v = MLVentaMetrica(
        id_operacion=_venta_counter,
        mla_id="MLA999",
        item_id=1001,
        codigo="TL-WR840N",
        descripcion="Router TP-Link",
        marca=marca,
        categoria=categoria,
        fecha_venta=datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
        cantidad=1,
        monto_unitario=monto_total,
        monto_total=monto_total,
        costo_unitario_sin_iva=costo_total_sin_iva,
        costo_total_sin_iva=costo_total_sin_iva,
        comision_ml=comision_ml,
        costo_envio_ml=costo_envio_ml,
        tipo_logistica=tipo_logistica,
        monto_limpio=monto_limpio,
        costo_total=costo_total_sin_iva + costo_envio_ml,
        ganancia=ganancia,
        markup_porcentaje=33.33,
        offset_flex=offset_flex,
        mlp_official_store_id=store_id,
        is_cancelled=False,  # explicit — SQLite ignores server_default
    )
    db.add(v)
    db.flush()
    return v


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def brand_rol(db) -> Rol:
    rol = Rol(codigo="BRAND", nombre="Brand", es_sistema=False, orden=99, activo=True)
    db.add(rol)
    db.flush()
    return rol


@pytest.fixture()
def perm_ver(db) -> Permiso:
    p = Permiso(
        codigo="dashboard_tplink.ver",
        nombre="Ver dashboard TP-Link",
        descripcion="Access",
        categoria="ventas_ml",
        orden=60,
        es_critico=False,
    )
    db.add(p)
    db.flush()
    return p


@pytest.fixture()
def perm_ver_ganancia(db) -> Permiso:
    p = Permiso(
        codigo="dashboard_tplink.ver_ganancia",
        nombre="Ver ganancia TP-Link",
        descripcion="Margin access",
        categoria="ventas_ml",
        orden=61,
        es_critico=False,
    )
    db.add(p)
    db.flush()
    return p


@pytest.fixture()
def user_no_perm(db, brand_rol) -> Usuario:
    """User authenticated but lacking any dashboard_tplink permission."""
    user = Usuario(
        username="brand_no_perm",
        email="noperm@tplink.com",
        nombre="No Perm User",
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
def user_ver_only(db, brand_rol, perm_ver) -> Usuario:
    """Brand user with only dashboard_tplink.ver — no margin access."""
    from app.models.permiso import UsuarioPermisoOverride

    user = Usuario(
        username="brand_ver_only",
        email="ver@tplink.com",
        nombre="Ver Only User",
        password_hash=get_password_hash("Pass123!"),
        rol=RolUsuario.VENTAS,
        rol_id=brand_rol.id,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(user)
    db.flush()

    override = UsuarioPermisoOverride(
        usuario_id=user.id,
        permiso_id=perm_ver.id,
        concedido=True,
    )
    db.add(override)
    db.flush()
    return user


@pytest.fixture()
def user_ver_ganancia(db, brand_rol, perm_ver, perm_ver_ganancia) -> Usuario:
    """Brand user with both permissions."""
    from app.models.permiso import UsuarioPermisoOverride

    user = Usuario(
        username="brand_full",
        email="full@tplink.com",
        nombre="Full Brand User",
        password_hash=get_password_hash("Pass123!"),
        rol=RolUsuario.VENTAS,
        rol_id=brand_rol.id,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(user)
    db.flush()

    for perm in (perm_ver, perm_ver_ganancia):
        override = UsuarioPermisoOverride(
            usuario_id=user.id,
            permiso_id=perm.id,
            concedido=True,
        )
        db.add(override)
    db.flush()
    return user


@pytest.fixture()
def superadmin_rol(db) -> Rol:
    """Role with codigo=SUPERADMIN so es_superadmin property returns True."""
    rol = Rol(codigo="SUPERADMIN", nombre="Super Admin", es_sistema=True, orden=0, activo=True)
    db.add(rol)
    db.flush()
    return rol


@pytest.fixture()
def superadmin_user(db, superadmin_rol) -> Usuario:
    """Super-admin user — has all permissions by design (rol_obj.codigo == 'SUPERADMIN')."""
    user = Usuario(
        username="superadmin_tplink_test",
        email="superadmin_t@pricing.com",
        nombre="Super Admin",
        password_hash=get_password_hash("Pass123!"),
        rol=RolUsuario.SUPERADMIN,
        rol_id=superadmin_rol.id,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(user)
    db.flush()
    return user


@pytest.fixture()
def tplink_venta(db) -> MLVentaMetrica:
    """One sale row for store 2645."""
    return _make_venta(db, store_id=TPLINK_STORE_ID, ganancia=2000.0, costo_total_sin_iva=6000.0)


@pytest.fixture()
def other_store_venta(db) -> MLVentaMetrica:
    """One sale row for a different store (57997)."""
    return _make_venta(db, store_id=OTHER_STORE_ID, monto_total=99000.0, ganancia=99000.0)


# ---------------------------------------------------------------------------
# T-04: Permission gate tests (RED before T-05)
# ---------------------------------------------------------------------------


BRAND_ENDPOINTS = [
    "/api/dashboard-tplink/metricas-generales",
    "/api/dashboard-tplink/por-categoria",
    "/api/dashboard-tplink/por-logistica",
    "/api/dashboard-tplink/por-dia",
    "/api/dashboard-tplink/top-productos",
    "/api/dashboard-tplink/categorias-disponibles",
]


class TestPermissionGate:
    def test_unauthenticated_returns_401(self, client) -> None:
        """No JWT → 401 or 403 (HTTPBearer returns 403 when credentials missing in some FastAPI versions)."""
        response = client.get("/api/dashboard-tplink/metricas-generales")
        assert response.status_code in (401, 403)

    def test_no_permission_returns_403(self, client, user_no_perm) -> None:
        """Valid JWT, user without dashboard_tplink.ver → 403."""
        response = client.get(
            "/api/dashboard-tplink/metricas-generales",
            headers=_bearer(user_no_perm),
        )
        assert response.status_code == 403

    def test_with_ver_permission_returns_200(self, client, user_ver_only) -> None:
        """Valid JWT + dashboard_tplink.ver → 200."""
        response = client.get(
            "/api/dashboard-tplink/metricas-generales",
            headers=_bearer(user_ver_only),
        )
        assert response.status_code == 200

    @pytest.mark.parametrize("endpoint", BRAND_ENDPOINTS)
    def test_all_endpoints_gate_403_without_permission(self, client, user_no_perm, endpoint: str) -> None:
        """All 6 brand endpoints return 403 for a user without .ver."""
        response = client.get(endpoint, headers=_bearer(user_no_perm))
        assert response.status_code == 403


# ---------------------------------------------------------------------------
# T-06: Store lock + PM bypass tests (RED before T-07)
# ---------------------------------------------------------------------------


class TestStoreLock:
    def test_store_lock_ignores_client_param(self, client, user_ver_only, tplink_venta, other_store_venta) -> None:
        """
        Client sends tiendas_oficiales=57997. Server must ignore it and return
        ONLY store-2645 data. The other-store sale has monto_total=99000 which
        would dominate the aggregates if included.
        """
        response = client.get(
            "/api/dashboard-tplink/metricas-generales?tiendas_oficiales=57997",
            headers=_bearer(user_ver_only),
        )
        assert response.status_code == 200
        data = response.json()
        # If 57997 data leaked in, total_ventas_ml would be ~109000 or 99000.
        # Only store 2645 data: monto_total=10000
        total = float(data["total_ventas_ml"])
        assert total < 50000, f"Expected only store-2645 data (≈10000) but got {total}; store-lock may be broken"

    def test_extra_query_param_silently_ignored(self, client, user_ver_only) -> None:
        """Unknown extra param does not cause 422 or server error."""
        response = client.get(
            "/api/dashboard-tplink/metricas-generales?unknown_param=foo",
            headers=_bearer(user_ver_only),
        )
        assert response.status_code == 200

    def test_pm_marca_bypass_returns_data_without_marcapm_rows(self, client, user_ver_only, tplink_venta) -> None:
        """
        Brand user has NO MarcaPM assignment.
        Without the bypass, aplicar_filtro_marcas_pm would filter to __NINGUNA__
        and return empty results. With the bypass, store-2645 data is returned.
        """
        response = client.get(
            "/api/dashboard-tplink/metricas-generales",
            headers=_bearer(user_ver_only),
        )
        assert response.status_code == 200
        data = response.json()
        total = float(data["total_ventas_ml"])
        assert total > 0, "Expected store-2645 data but got empty result (PM bypass may be missing)"


# ---------------------------------------------------------------------------
# T-08: Margin masking tests (RED before full T-07 implementation)
# ---------------------------------------------------------------------------

MARGIN_KEYS_METRICAS = {"total_ganancia", "markup_porcentaje", "total_costo", "total_comisiones"}


class TestMarginMasking:
    def test_margin_absent_when_no_ver_ganancia(self, client, user_ver_only, tplink_venta) -> None:
        """User with .ver only: margin keys ABSENT from metricas response (not null, not zero)."""
        response = client.get(
            "/api/dashboard-tplink/metricas-generales",
            headers=_bearer(user_ver_only),
        )
        assert response.status_code == 200
        data = response.json()
        present_margin_keys = MARGIN_KEYS_METRICAS & set(data.keys())
        assert not present_margin_keys, f"Margin keys should be ABSENT but found: {present_margin_keys}"

    def test_margin_present_when_ver_ganancia_granted(self, client, user_ver_ganancia, tplink_venta) -> None:
        """User with both permissions: margin keys ARE present with non-null values."""
        response = client.get(
            "/api/dashboard-tplink/metricas-generales",
            headers=_bearer(user_ver_ganancia),
        )
        assert response.status_code == 200
        data = response.json()
        for key in MARGIN_KEYS_METRICAS:
            assert key in data, f"Expected margin key '{key}' to be present"
            assert data[key] is not None, f"Margin key '{key}' should not be None"


# ---------------------------------------------------------------------------
# T-09: Offset absence tests (unconditional for all permission levels)
# ---------------------------------------------------------------------------

OFFSET_KEYS = {"total_offset_flex", "offset_flex"}


class TestOffsetAbsence:
    @pytest.mark.parametrize("user_fixture", ["user_ver_only", "user_ver_ganancia"])
    def test_offsets_absent_from_metricas(self, request, client, user_fixture: str) -> None:
        """total_offset_flex absent from metricas at any permission level."""
        user = request.getfixturevalue(user_fixture)
        response = client.get(
            "/api/dashboard-tplink/metricas-generales",
            headers=_bearer(user),
        )
        assert response.status_code == 200
        data = response.json()
        assert "total_offset_flex" not in data, "total_offset_flex must never appear in brand metricas response"

    @pytest.mark.parametrize("user_fixture", ["user_ver_only", "user_ver_ganancia"])
    def test_offsets_absent_from_logistica(self, request, client, user_fixture: str) -> None:
        """total_offset_flex absent from por-logistica at any permission level."""
        user = request.getfixturevalue(user_fixture)
        response = client.get(
            "/api/dashboard-tplink/por-logistica",
            headers=_bearer(user),
        )
        assert response.status_code == 200
        rows = response.json()
        for row in rows:
            assert "total_offset_flex" not in row, "total_offset_flex must never appear in brand logistica response"

    @pytest.mark.parametrize("user_fixture", ["user_ver_only", "user_ver_ganancia"])
    def test_no_operaciones_endpoint_exposes_offset(self, request, client, user_fixture: str) -> None:
        """
        The operaciones endpoint (if implemented) must not expose offset_flex.
        Using por-categoria as a proxy here since operaciones is excluded from
        the base 6 endpoints in the initial scaffold.
        This test asserts the general contract: no brand response contains offset keys.
        """
        user = request.getfixturevalue(user_fixture)
        response = client.get(
            "/api/dashboard-tplink/por-categoria",
            headers=_bearer(user),
        )
        assert response.status_code == 200
        rows = response.json()
        for row in rows:
            for key in OFFSET_KEYS:
                assert key not in row, f"Offset key '{key}' must never appear in brand category response"


# ---------------------------------------------------------------------------
# T-10: SUPERADMIN full access test
# ---------------------------------------------------------------------------


class TestSuperAdminAccess:
    def test_superadmin_gets_200_and_full_data(self, client, superadmin_user, tplink_venta) -> None:
        """es_superadmin=True user → 200 and margin keys present (no masking)."""
        response = client.get(
            "/api/dashboard-tplink/metricas-generales",
            headers=_bearer(superadmin_user),
        )
        assert response.status_code == 200
        data = response.json()
        # Superadmin sees everything including margins
        for key in MARGIN_KEYS_METRICAS:
            assert key in data, f"Superadmin should see margin key '{key}' but it was absent"
