"""
T-11 — Integration tests: TP-Link aggregation endpoints read TplinkVentaMetrica.

Verifies that after the PR2 cutover, all 6 aggregation endpoints read from
`tplink_ventas_metricas` (TplinkVentaMetrica) instead of `ml_ventas_metricas`
(MLVentaMetrica).

Isolation proof: we seed TplinkVentaMetrica with known amounts (e.g. 10 000)
and MLVentaMetrica with deliberately different amounts (99 999). Endpoints must
return the TP-Link values, not the ML values.

Also verifies:
- Date range (Argentina TZ semantics): rows outside range excluded
- Category filter: only matching category returned
- is_cancelled=True rows excluded
- 403 without dashboard_tplink.ver
- Margin fields absent when caller lacks dashboard_tplink.ver_ganancia
- Margin fields present when caller has dashboard_tplink.ver_ganancia
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.core.security import create_access_token, get_password_hash
from app.models.tplink_venta_metrica import TplinkVentaMetrica
from app.models.ml_venta_metrica import MLVentaMetrica
from app.models.mercadolibre_item_publicado import MercadoLibreItemPublicado
from app.models.permiso import Permiso
from app.models.rol import Rol
from app.models.usuario import AuthProvider, RolUsuario, Usuario

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TPLINK_STORE_ID = 2645
OTHER_STORE_ID = 57997

# Known amounts seeded in TplinkVentaMetrica — endpoints must return these.
TP_MONTO_TOTAL = 10000.0
TP_GANANCIA = 2000.0
TP_COSTO = 6000.0
TP_ENVIO = 500.0
TP_COMISION = 1500.0
TP_LIMPIO = 8000.0

# Different amounts seeded in MLVentaMetrica — if an endpoint returns these,
# it is still reading from the old ML table (bug).
ML_MONTO_TOTAL = 99999.0

# ---------------------------------------------------------------------------
# Counters (module-level to generate unique IDs per helper call)
# ---------------------------------------------------------------------------

_tp_counter = 0
_ml_counter = 500_000  # offset to avoid collision with _tp_counter


def _make_tplink_venta(
    db,
    *,
    monto_total: float = TP_MONTO_TOTAL,
    ganancia: float = TP_GANANCIA,
    costo_total_sin_iva: float = TP_COSTO,
    costo_envio_ml: float = TP_ENVIO,
    comision_ml: float = TP_COMISION,
    monto_limpio: float = TP_LIMPIO,
    tipo_logistica: str = "flex",
    categoria: str = "Networking",
    marca: str = "TP-Link",
    fecha_venta: datetime | None = None,
    is_cancelled: bool = False,
) -> TplinkVentaMetrica:
    """Seed one TplinkVentaMetrica row. No publication needed — the new filter
    queries the table directly without a store subquery."""
    global _tp_counter
    _tp_counter += 1

    if fecha_venta is None:
        fecha_venta = datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc)

    row = TplinkVentaMetrica(
        id_operacion=_tp_counter,
        mla_id=str(_tp_counter),
        item_id=1001 + _tp_counter,
        codigo=f"TL-{_tp_counter}",
        descripcion="Router TP-Link",
        marca=marca,
        categoria=categoria,
        fecha_venta=fecha_venta,
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
        mlp_official_store_id=TPLINK_STORE_ID,
        is_cancelled=is_cancelled,
    )
    db.add(row)
    db.flush()
    return row


def _make_ml_venta_decoy(
    db,
    *,
    monto_total: float = ML_MONTO_TOTAL,
) -> MLVentaMetrica:
    """Seed one MLVentaMetrica row with a deliberately different amount so that
    any endpoint that still reads MLVentaMetrica would return the wrong number."""
    global _ml_counter
    _ml_counter += 1

    pub_id = _ml_counter
    db.add(
        MercadoLibreItemPublicado(
            mlp_id=pub_id,
            mlp_official_store_id=TPLINK_STORE_ID,
        )
    )

    row = MLVentaMetrica(
        id_operacion=_ml_counter,
        mla_id=str(pub_id),
        item_id=9000 + _ml_counter,
        codigo=f"DECOY-{_ml_counter}",
        descripcion="ML Decoy Row",
        marca="TP-Link",
        categoria="Networking",
        fecha_venta=datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc),
        cantidad=1,
        monto_unitario=monto_total,
        monto_total=monto_total,
        costo_unitario_sin_iva=0.0,
        costo_total_sin_iva=0.0,
        comision_ml=0.0,
        costo_envio_ml=0.0,
        tipo_logistica="flex",
        monto_limpio=monto_total,
        costo_total=0.0,
        ganancia=0.0,
        markup_porcentaje=0.0,
        mlp_official_store_id=TPLINK_STORE_ID,
        is_cancelled=False,
    )
    db.add(row)
    db.flush()
    return row


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _bearer(user: Usuario) -> dict[str, str]:
    token = create_access_token(data={"sub": user.username})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def brand_rol(db) -> Rol:
    rol = Rol(codigo="BRAND_T", nombre="Brand T", es_sistema=False, orden=98, activo=True)
    db.add(rol)
    db.flush()
    return rol


@pytest.fixture()
def perm_ver_t(db) -> Permiso:
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
def perm_ver_ganancia_t(db) -> Permiso:
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
def user_no_perm_t(db, brand_rol) -> Usuario:
    user = Usuario(
        username="t_no_perm",
        email="t_noperm@tplink.com",
        nombre="No Perm T",
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
def user_ver_t(db, brand_rol, perm_ver_t) -> Usuario:
    from app.models.permiso import UsuarioPermisoOverride

    user = Usuario(
        username="t_ver_only",
        email="t_ver@tplink.com",
        nombre="Ver Only T",
        password_hash=get_password_hash("Pass123!"),
        rol=RolUsuario.VENTAS,
        rol_id=brand_rol.id,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(user)
    db.flush()
    db.add(UsuarioPermisoOverride(usuario_id=user.id, permiso_id=perm_ver_t.id, concedido=True))
    db.flush()
    return user


@pytest.fixture()
def user_ver_ganancia_t(db, brand_rol, perm_ver_t, perm_ver_ganancia_t) -> Usuario:
    from app.models.permiso import UsuarioPermisoOverride

    user = Usuario(
        username="t_ver_ganancia",
        email="t_full@tplink.com",
        nombre="Full T",
        password_hash=get_password_hash("Pass123!"),
        rol=RolUsuario.VENTAS,
        rol_id=brand_rol.id,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(user)
    db.flush()
    for perm in (perm_ver_t, perm_ver_ganancia_t):
        db.add(UsuarioPermisoOverride(usuario_id=user.id, permiso_id=perm.id, concedido=True))
    db.flush()
    return user


# ---------------------------------------------------------------------------
# Tests — Permission gate
# ---------------------------------------------------------------------------


def test_metricas_generales_403_without_ver(client, user_no_perm_t):
    """All aggregation endpoints require dashboard_tplink.ver."""
    resp = client.get(
        "/api/dashboard-tplink/metricas-generales",
        headers=_bearer(user_no_perm_t),
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Tests — Isolation: endpoints read TplinkVentaMetrica, not MLVentaMetrica
# ---------------------------------------------------------------------------


def test_metricas_generales_reads_tplink_table(client, db, user_ver_t):
    """metricas-generales must return TplinkVentaMetrica totals, not MLVentaMetrica."""
    _make_tplink_venta(db, monto_total=10000.0)
    _make_ml_venta_decoy(db, monto_total=99999.0)

    resp = client.get(
        "/api/dashboard-tplink/metricas-generales",
        headers=_bearer(user_ver_t),
    )
    assert resp.status_code == 200
    data = resp.json()
    # Must match TplinkVentaMetrica value, not the ML decoy (99 999)
    assert float(data["total_ventas_ml"]) == pytest.approx(10000.0)
    assert float(data["total_envios"]) == pytest.approx(TP_ENVIO)
    assert data["cantidad_operaciones"] == 1


def test_por_categoria_reads_tplink_table(client, db, user_ver_t):
    """por-categoria must aggregate TplinkVentaMetrica rows."""
    _make_tplink_venta(db, categoria="Switches", monto_total=5000.0)
    _make_ml_venta_decoy(db)  # different amount — should NOT show up

    resp = client.get(
        "/api/dashboard-tplink/por-categoria",
        headers=_bearer(user_ver_t),
    )
    assert resp.status_code == 200
    data = resp.json()
    # Only TplinkVentaMetrica row's category present
    categorias = [r["categoria"] for r in data]
    assert "Switches" in categorias
    # TplinkVentaMetrica monto — not the ML 99999 decoy
    switch_row = next(r for r in data if r["categoria"] == "Switches")
    assert float(switch_row["total_ventas"]) == pytest.approx(5000.0)


def test_por_logistica_reads_tplink_table(client, db, user_ver_t):
    """por-logistica must read TplinkVentaMetrica."""
    _make_tplink_venta(db, tipo_logistica="fulfillment", monto_total=7500.0)

    resp = client.get(
        "/api/dashboard-tplink/por-logistica",
        headers=_bearer(user_ver_t),
    )
    assert resp.status_code == 200
    data = resp.json()
    tipos = [r["tipo_logistica"] for r in data]
    assert "fulfillment" in tipos
    row = next(r for r in data if r["tipo_logistica"] == "fulfillment")
    assert float(row["total_ventas"]) == pytest.approx(7500.0)


@pytest.mark.skip(reason="por-dia uses func.timezone() — PostgreSQL only, skipped on SQLite")
def test_por_dia_reads_tplink_table(client, db, user_ver_t):
    """por-dia must read TplinkVentaMetrica."""
    _make_tplink_venta(db, monto_total=3333.0)
    _make_ml_venta_decoy(db)

    resp = client.get(
        "/api/dashboard-tplink/por-dia",
        headers=_bearer(user_ver_t),
    )
    assert resp.status_code == 200
    data = resp.json()
    # Total across all days must equal TplinkVentaMetrica amount only
    total = sum(float(r["total_ventas"]) for r in data)
    assert total == pytest.approx(3333.0)


def test_top_productos_reads_tplink_table(client, db, user_ver_t):
    """top-productos must read TplinkVentaMetrica."""
    _make_tplink_venta(db, monto_total=8888.0)
    _make_ml_venta_decoy(db)

    resp = client.get(
        "/api/dashboard-tplink/top-productos",
        headers=_bearer(user_ver_t),
    )
    assert resp.status_code == 200
    data = resp.json()
    total = sum(float(r["total_ventas"]) for r in data)
    assert total == pytest.approx(8888.0)


def test_categorias_disponibles_reads_tplink_table(client, db, user_ver_t):
    """categorias-disponibles must read TplinkVentaMetrica."""
    _make_tplink_venta(db, categoria="Access Points")

    resp = client.get(
        "/api/dashboard-tplink/categorias-disponibles",
        headers=_bearer(user_ver_t),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "Access Points" in data


# ---------------------------------------------------------------------------
# Tests — is_cancelled exclusion
# ---------------------------------------------------------------------------


def test_cancelled_rows_excluded(client, db, user_ver_t):
    """is_cancelled=True rows must be excluded from aggregation."""
    _make_tplink_venta(db, monto_total=10000.0, is_cancelled=False)
    _make_tplink_venta(db, monto_total=99999.0, is_cancelled=True)

    resp = client.get(
        "/api/dashboard-tplink/metricas-generales",
        headers=_bearer(user_ver_t),
    )
    assert resp.status_code == 200
    data = resp.json()
    # Only the non-cancelled row should be counted
    assert float(data["total_ventas_ml"]) == pytest.approx(10000.0)
    assert data["cantidad_operaciones"] == 1


# ---------------------------------------------------------------------------
# Tests — Date range filter
# ---------------------------------------------------------------------------


def test_date_range_filter_excludes_out_of_range(client, db, user_ver_t):
    """Rows outside fecha_desde/fecha_hasta must be excluded."""
    # Inside range: June 15 2026 UTC — well within "2026-06-14" to "2026-06-16"
    _make_tplink_venta(
        db,
        monto_total=1111.0,
        fecha_venta=datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc),
    )
    # Outside range: June 20 2026
    _make_tplink_venta(
        db,
        monto_total=9999.0,
        fecha_venta=datetime(2026, 6, 20, 12, 0, 0, tzinfo=timezone.utc),
    )

    resp = client.get(
        "/api/dashboard-tplink/metricas-generales",
        params={"fecha_desde": "2026-06-14", "fecha_hasta": "2026-06-16"},
        headers=_bearer(user_ver_t),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert float(data["total_ventas_ml"]) == pytest.approx(1111.0)
    assert data["cantidad_operaciones"] == 1


# ---------------------------------------------------------------------------
# Tests — Category filter
# ---------------------------------------------------------------------------


def test_category_filter(client, db, user_ver_t):
    """categoria= query param must filter TplinkVentaMetrica rows."""
    _make_tplink_venta(db, categoria="Cameras", monto_total=2000.0)
    _make_tplink_venta(db, categoria="Networking", monto_total=3000.0)

    resp = client.get(
        "/api/dashboard-tplink/metricas-generales",
        params={"categorias": "Cameras"},
        headers=_bearer(user_ver_t),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert float(data["total_ventas_ml"]) == pytest.approx(2000.0)


# ---------------------------------------------------------------------------
# Tests — Margin masking
# ---------------------------------------------------------------------------


def test_margin_fields_absent_without_ver_ganancia(client, db, user_ver_t):
    """Margin fields must be absent (not zero) when .ver_ganancia is missing."""
    _make_tplink_venta(db)

    resp = client.get(
        "/api/dashboard-tplink/metricas-generales",
        headers=_bearer(user_ver_t),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "total_ganancia" not in data
    assert "total_costo" not in data
    assert "markup_porcentaje" not in data
    assert "total_comisiones" not in data


def test_margin_fields_present_with_ver_ganancia(client, db, user_ver_ganancia_t):
    """Margin fields must appear when caller has .ver_ganancia."""
    _make_tplink_venta(db, ganancia=2000.0, costo_total_sin_iva=6000.0)

    resp = client.get(
        "/api/dashboard-tplink/metricas-generales",
        headers=_bearer(user_ver_ganancia_t),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "total_ganancia" in data
    assert "total_costo" in data
    assert float(data["total_ganancia"]) == pytest.approx(2000.0)
    assert float(data["total_costo"]) == pytest.approx(6000.0)
