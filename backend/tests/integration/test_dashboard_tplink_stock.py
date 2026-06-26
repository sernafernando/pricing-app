"""
Integration tests for GET /dashboard-tplink/stock.

Security contract:
1. 403 without dashboard_tplink.ver
2. 200 with ver only — margin fields absent (exclude_none)
3. 200 with ver_ganancia — costo_lista8, moneda_original, cotizacion present
4. Items with stock=0 are excluded
5. Items without coslis_id=8 entry are excluded
"""

from __future__ import annotations

from datetime import date

import pytest

from app.core.security import create_access_token, get_password_hash
from app.models.item_cost_list import ItemCostList
from app.models.producto import ProductoERP
from app.models.tipo_cambio import TipoCambio
from app.models.permiso import Permiso
from app.models.rol import Rol
from app.models.usuario import AuthProvider, RolUsuario, Usuario


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bearer(user: Usuario) -> dict[str, str]:
    token = create_access_token(data={"sub": user.username})
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def brand_rol(db) -> Rol:
    rol = Rol(codigo="BRAND_STOCK", nombre="Brand Stock", es_sistema=False, orden=99, activo=True)
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
    user = Usuario(
        username="stock_no_perm",
        email="stock_noperm@tplink.com",
        nombre="No Perm Stock",
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
    from app.models.permiso import UsuarioPermisoOverride

    user = Usuario(
        username="stock_ver_only",
        email="stock_ver@tplink.com",
        nombre="Ver Only Stock",
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
    from app.models.permiso import UsuarioPermisoOverride

    user = Usuario(
        username="stock_full",
        email="stock_full@tplink.com",
        nombre="Full Stock User",
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
def seed_stock(db) -> None:
    """Seed data for stock tests."""
    # USD exchange rate today
    tc = TipoCambio(
        fecha=date.today(),
        moneda="USD",
        compra=950.0,
        venta=1000.0,
    )
    db.add(tc)

    # Product 1: has stock + coslis_id=8 entry in USD
    prod1 = ProductoERP(
        item_id=1,
        codigo="TP001",
        descripcion="TP-Link Router",
        stock=5,
        activo=True,
    )
    db.add(prod1)

    cost1 = ItemCostList(
        comp_id=1,
        coslis_id=8,
        item_id=1,
        coslis_price=10.0,
        curr_id=2,  # USD
    )
    db.add(cost1)

    # Product 2: stock=0 — should be excluded
    prod2 = ProductoERP(
        item_id=2,
        codigo="TP002",
        descripcion="TP-Link Switch",
        stock=0,
        activo=True,
    )
    db.add(prod2)

    # Product 3: has stock but NO coslis_id=8 entry — should be excluded
    prod3 = ProductoERP(
        item_id=3,
        codigo="TP003",
        descripcion="TP-Link AP",
        stock=10,
        activo=True,
    )
    db.add(prod3)
    # Only coslis_id=1 (not 8) for prod3
    cost3 = ItemCostList(
        comp_id=1,
        coslis_id=1,
        item_id=3,
        coslis_price=5.0,
        curr_id=2,
    )
    db.add(cost3)

    db.flush()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestStockTPLink:
    def test_403_without_ver_permission(self, client, user_no_perm) -> None:
        """No dashboard_tplink.ver → 403."""
        response = client.get("/api/dashboard-tplink/stock", headers=_bearer(user_no_perm))
        assert response.status_code == 403

    def test_200_ver_only_excludes_margin_fields(self, client, user_ver_only, seed_stock) -> None:
        """User with .ver only: 200; margin fields absent (not null, not zero — excluded)."""
        response = client.get("/api/dashboard-tplink/stock", headers=_bearer(user_ver_only))
        assert response.status_code == 200
        rows = response.json()
        assert len(rows) == 1
        row = rows[0]
        assert row["codigo"] == "TP001"
        assert row["descripcion"] == "TP-Link Router"
        assert row["stock"] == 5
        # Margin fields MUST be absent (response_model_exclude_none=True)
        assert "costo_lista8" not in row
        assert "moneda_original" not in row
        assert "cotizacion" not in row

    def test_200_ver_ganancia_includes_margin_fields(self, client, user_ver_ganancia, seed_stock) -> None:
        """User with .ver_ganancia: margin fields present with correct values."""
        response = client.get("/api/dashboard-tplink/stock", headers=_bearer(user_ver_ganancia))
        assert response.status_code == 200
        rows = response.json()
        assert len(rows) == 1
        row = rows[0]
        assert row["codigo"] == "TP001"
        assert row["stock"] == 5
        # 10.0 USD * 1000 ARS/USD = 10000.00
        assert float(row["costo_lista8"]) == 10000.00
        assert row["moneda_original"] == "USD"
        assert float(row["cotizacion"]) == 1000.0

    def test_stock_zero_excluded(self, client, user_ver_only, seed_stock) -> None:
        """Items with stock=0 do not appear in the response."""
        response = client.get("/api/dashboard-tplink/stock", headers=_bearer(user_ver_only))
        assert response.status_code == 200
        rows = response.json()
        codigos = [r["codigo"] for r in rows]
        assert "TP002" not in codigos

    def test_item_without_coslis8_excluded(self, client, user_ver_only, seed_stock) -> None:
        """Items that have no coslis_id=8 entry do not appear in the response."""
        response = client.get("/api/dashboard-tplink/stock", headers=_bearer(user_ver_only))
        assert response.status_code == 200
        rows = response.json()
        codigos = [r["codigo"] for r in rows]
        assert "TP003" not in codigos
