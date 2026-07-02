"""
T1.2 — Tests para el endpoint POST /api/administracion/compras/testing/wipe-compras.

Cubre:
  - test_wipe_requires_auth: sin token → 401
  - test_wipe_requires_permiso: con token pero sin permiso → 403
  - test_wipe_requires_confirmation_string: body con confirmacion wrong → 422
  - test_wipe_clears_all_tables: user con permiso + body correcto → 200, filas seedeadas
    realmente eliminadas (cc_proveedor_movimientos, compras_papelera) + tablas nuevas presentes.
"""

from __future__ import annotations

import datetime
from unittest.mock import patch

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.models.dinero_a_cuenta import DineroACuenta
from app.models.empresa import Empresa
from app.models.etiqueta_envio import EtiquetaEnvio
from app.models.orden_pago import OrdenPago
from app.models.pedido_compra import PedidoCompra
from app.models.proveedor import Proveedor
from app.models.cc_proveedor_movimiento import CCProveedorMovimiento
from app.models.compras_papelera import ComprasPapelera


BASE = "/api/administracion/compras"

# ──────────────────────────────────────────────────────────────────────────
# Env decision (Work Unit 1.1 / design §10.2):
#
# The test process default `settings.ENVIRONMENT` is "development"
# (backend/.env:16 sets ENVIRONMENT=development, and pydantic-settings loads
# .env by default — see config.py `model_config = SettingsConfigDict(env_file=".env", ...)`).
# This is Option (b): existing tests below are unaffected by the new
# route-level 404 gate (they run with the gate open) — only the new
# `test_wipe_returns_404_outside_development` test overrides `ENVIRONMENT`
# to "production" via monkeypatch.
# ──────────────────────────────────────────────────────────────────────────


# ──────────────────────────────────────────────────────────────────────────
# Permission fixtures
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture
def con_permiso_wipe():
    """Fuerza PermisosService.tiene_permiso → True para este test."""
    with (
        patch(
            "app.services.permisos_service.PermisosService.tiene_permiso",
            return_value=True,
        ),
        patch(
            "app.services.permisos_service.PermisosService.obtener_permisos_usuario",
            return_value=set(),
        ),
    ):
        yield


@pytest.fixture
def sin_permiso_wipe():
    """Fuerza PermisosService.tiene_permiso → False para este test."""
    with (
        patch(
            "app.services.permisos_service.PermisosService.tiene_permiso",
            return_value=False,
        ),
        patch(
            "app.services.permisos_service.PermisosService.obtener_permisos_usuario",
            return_value=set(),
        ),
    ):
        yield


# ──────────────────────────────────────────────────────────────────────────
# Seed fixture: inserta filas reales en tablas que el wipe debe limpiar
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture
def wipe_seed(db, admin_user):
    """
    Inserta filas reales en tablas del módulo compras para verificar
    que el wipe las elimina efectivamente.

    Retorna un dict con los conteos pre-wipe por tabla de interés.
    """
    # Crear empresa y proveedor (dependencias FK de los movimientos)
    empresa = Empresa(nombre="Empresa Wipe Test", activo=True)
    db.add(empresa)
    db.flush()

    proveedor = Proveedor(nombre="Proveedor Wipe Test", origen="manual", activo=True)
    db.add(proveedor)
    db.flush()

    # Seedear cc_proveedor_movimientos (tabla core del módulo)
    mov = CCProveedorMovimiento(
        proveedor_id=proveedor.id,
        empresa_id=empresa.id,
        fecha_movimiento=datetime.date.today(),
        tipo="debe",
        monto=100,
        moneda="ARS",
        origen_tipo="ajuste_manual",
    )
    db.add(mov)
    db.flush()

    # Seedear compras_papelera (tabla que el wipe antes omitía — WARNING 4)
    papelera = ComprasPapelera(
        entidad_tipo="pedido_compra",
        entidad_id_original=9999,
        numero="PC-0001",
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        snapshot={"id": 9999, "estado": "aprobado"},
        eliminado_por_id=admin_user.id,
        motivo="test wipe",
        estado_original="aprobado",
    )
    db.add(papelera)
    db.flush()

    # Verificar que las filas están en la DB antes del wipe
    count_movs = db.execute(text("SELECT COUNT(*) FROM cc_proveedor_movimientos")).scalar()
    count_papelera = db.execute(text("SELECT COUNT(*) FROM compras_papelera")).scalar()
    assert count_movs >= 1, "Precondición: debe haber al menos 1 movimiento antes del wipe"
    assert count_papelera >= 1, "Precondición: debe haber al menos 1 fila en compras_papelera antes del wipe"

    yield {"cc_proveedor_movimientos": count_movs, "compras_papelera": count_papelera}


# ──────────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────────


def test_wipe_requires_auth(client) -> None:
    """Sin token JWT → 401 o 403 (el JWT no llega al validator)."""
    response = client.post(
        f"{BASE}/testing/wipe-compras",
        json={"confirmacion": "WIPE", "incluir_caja_banco": True},
    )
    assert response.status_code in (401, 403)


def test_wipe_requires_permiso(client, admin_auth_headers, sin_permiso_wipe) -> None:
    """Con token pero sin permiso → 403."""
    response = client.post(
        f"{BASE}/testing/wipe-compras",
        json={"confirmacion": "WIPE", "incluir_caja_banco": True},
        headers=admin_auth_headers,
    )
    assert response.status_code == 403


def test_wipe_requires_confirmation_string(client, admin_auth_headers, con_permiso_wipe) -> None:
    """Body con confirmacion incorrecta → 422."""
    response = client.post(
        f"{BASE}/testing/wipe-compras",
        json={"confirmacion": "wrong", "incluir_caja_banco": True},
        headers=admin_auth_headers,
    )
    assert response.status_code == 422


def test_wipe_clears_all_tables(client, db, admin_auth_headers, con_permiso_wipe, wipe_seed) -> None:
    """Wipe real: seedea filas, ejecuta wipe, verifica que las tablas quedan vacías.

    Verifica:
    - Endpoint retorna 200 con estructura correcta.
    - cc_proveedor_movimientos queda vacía (tabla core seedeada).
    - compras_papelera queda vacía (tabla añadida en WARNING 4).
    - Respuesta incluye ambas tablas en tablas_limpiadas con conteo > 0.
    """
    response = client.post(
        f"{BASE}/testing/wipe-compras",
        json={"confirmacion": "WIPE", "incluir_caja_banco": False},
        headers=admin_auth_headers,
    )

    assert response.status_code == 200
    data = response.json()

    # Estructura de respuesta
    assert "tablas_limpiadas" in data
    assert isinstance(data["tablas_limpiadas"], dict)
    assert data["confirmado"] is True

    tablas = data["tablas_limpiadas"]

    # Tablas base siempre presentes
    assert "pedidos_compra" in tablas
    assert "imputaciones" in tablas
    assert "ordenes_pago" in tablas

    # cc_proveedor_movimientos: seedeada → debe reportar ≥1 fila eliminada
    assert "cc_proveedor_movimientos" in tablas
    assert tablas["cc_proveedor_movimientos"] >= 1, "El wipe debió eliminar al menos 1 movimiento seedeado"

    # compras_papelera: tabla añadida por WARNING 4 → debe estar en la respuesta
    # con al menos 1 fila eliminada (la seedeada en wipe_seed)
    assert "compras_papelera" in tablas, "compras_papelera debe estar en tablas_limpiadas (WARNING 4 fix)"
    assert tablas["compras_papelera"] >= 1, "El wipe debió eliminar al menos 1 fila de compras_papelera (seedeada)"

    # Confirmar en DB que las tablas quedan realmente vacías
    count_movs_post = db.execute(text("SELECT COUNT(*) FROM cc_proveedor_movimientos")).scalar()
    count_papelera_post = db.execute(text("SELECT COUNT(*) FROM compras_papelera")).scalar()
    assert count_movs_post == 0, "cc_proveedor_movimientos debe quedar vacía tras el wipe"
    assert count_papelera_post == 0, "compras_papelera debe quedar vacía tras el wipe"


# ──────────────────────────────────────────────────────────────────────────
# Regression: dinero_a_cuenta FK + etiquetas_envio non-destructive unlink
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture()
def wipe_fk_state(db, admin_user):
    """
    Recrea el estado exacto que causó el 500 en producción.

    Árbol de FK:
      pedido_compra ← etiqueta_envio.pedido_compra_id (RESTRICT, nullable)
      orden_pago    ← dinero_a_cuenta.origen_op_id    (RESTRICT)

    dinero_a_cuenta es leaf (nada apunta a ella).
    etiquetas_envio es shared (NO debe borrarse — solo desvincularse).

    Nota: SQLite con PRAGMA foreign_keys=ON sí enforcea estas FKs
    porque la tabla se crea con la constraint definida en el modelo.
    Si un futuro refactor cambia esto, el test sigue siendo válido como
    test comportamental (wipe éxito + fila etiqueta sobrevive con NULL).
    """
    empresa = Empresa(nombre="Empresa FK Test", activo=True)
    db.add(empresa)
    db.flush()

    proveedor = Proveedor(nombre="Proveedor FK Test", origen="manual", activo=True)
    db.add(proveedor)
    db.flush()

    pedido = PedidoCompra(
        numero="PC-REG-001",
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto=1000,
        estado="aprobado",
        creado_por_id=admin_user.id,
    )
    db.add(pedido)
    db.flush()

    op = OrdenPago(
        numero="OP-REG-001",
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto_total=500,
        modo_imputacion="a_cuenta",
        estado="pagado",
        actualizar_tc_pedido=False,
        creado_por_id=admin_user.id,
    )
    db.add(op)
    db.flush()

    # Fila que causó el FK violation: origen_op_id → ordenes_pago.id (RESTRICT)
    dac = DineroACuenta(
        proveedor_id=proveedor.id,
        empresa_id=empresa.id,
        monto=500,
        moneda="ARS",
        estado="disponible",
        origen_op_id=op.id,
        creado_por_id=admin_user.id,
    )
    db.add(dac)
    db.flush()

    # Etiqueta shared: pedido_compra_id → pedidos_compra.id (RESTRICT, nullable).
    # tipo_envio='retiro_proveedor' es el único tipo que permite pedido_compra_id IS NOT NULL
    # (ver chk_etiqueta_envio_tipo_coherencia). El wipe debe limpiar proveedor_id,
    # proveedor_direccion_id y pedido_compra_id y cambiar tipo_envio a 'cliente'
    # para satisfacer la constraint tras la desvinculación.
    etiqueta = EtiquetaEnvio(
        shipping_id=f"REG-TEST-{pedido.id}",
        fecha_envio=datetime.date.today(),
        tipo_envio="retiro_proveedor",
        proveedor_id=proveedor.id,
        pedido_compra_id=pedido.id,
    )
    db.add(etiqueta)
    db.flush()

    return {
        "empresa_id": empresa.id,
        "proveedor_id": proveedor.id,
        "pedido_id": pedido.id,
        "op_id": op.id,
        "dac_id": dac.id,
        "etiqueta_id": etiqueta.id,
    }


def test_wipe_fk_regression_dinero_a_cuenta_y_etiqueta(
    client, db, admin_auth_headers, con_permiso_wipe, wipe_fk_state
) -> None:
    """
    Regression test para el bug de producción:
      - DELETE FROM ordenes_pago fallaba con ForeignKeyViolation porque
        dinero_a_cuenta.origen_op_id → ordenes_pago.id (RESTRICT) y
        dinero_a_cuenta no estaba en TABLAS_COMPRAS_SIEMPRE.
      - DELETE FROM pedidos_compra fallaría con ForeignKeyViolation porque
        etiquetas_envio.pedido_compra_id → pedidos_compra.id (RESTRICT) y
        etiquetas_envio es una tabla shared que NO debe borrarse.

    POST-FIX assertions:
      1. Endpoint retorna 200 (el wipe completa sin FK error).
      2. ordenes_pago queda vacía.
      3. dinero_a_cuenta queda vacía.
      4. pedidos_compra queda vacía.
      5. La fila etiqueta_envio AÚN EXISTE (no fue borrada — tabla shared).
      6. etiqueta_envio.pedido_compra_id es NULL (desvinculada, RMA-safe).
    """
    ids = wipe_fk_state

    response = client.post(
        f"{BASE}/testing/wipe-compras",
        json={"confirmacion": "WIPE", "incluir_caja_banco": False},
        headers=admin_auth_headers,
    )

    assert response.status_code == 200, f"Wipe debe completar sin FK error. Got {response.status_code}: {response.text}"

    # Tablas compras → vacías
    count_op = db.execute(text("SELECT COUNT(*) FROM ordenes_pago")).scalar()
    count_dac = db.execute(text("SELECT COUNT(*) FROM dinero_a_cuenta")).scalar()
    count_pc = db.execute(text("SELECT COUNT(*) FROM pedidos_compra")).scalar()
    assert count_op == 0, "ordenes_pago debe quedar vacía"
    assert count_dac == 0, "dinero_a_cuenta debe quedar vacía"
    assert count_pc == 0, "pedidos_compra debe quedar vacía"

    # etiquetas_envio → fila sobrevive pero desvinculada
    etiqueta_row = db.execute(
        text("SELECT pedido_compra_id FROM etiquetas_envio WHERE id = :eid"),
        {"eid": ids["etiqueta_id"]},
    ).fetchone()
    assert etiqueta_row is not None, "La fila etiqueta_envio debe sobrevivir (tabla shared, no se borra)"
    assert etiqueta_row[0] is None, (
        "etiqueta_envio.pedido_compra_id debe ser NULL tras el wipe (desvinculación no destructiva)"
    )

    # Verificar también que tipo_envio quedó como 'cliente' (required by check constraint
    # chk_etiqueta_envio_tipo_coherencia: cliente → pedido_compra_id IS NULL).
    tipo_row = db.execute(
        text("SELECT tipo_envio FROM etiquetas_envio WHERE id = :eid"),
        {"eid": ids["etiqueta_id"]},
    ).fetchone()
    assert tipo_row is not None
    assert tipo_row[0] == "cliente", "etiqueta_envio.tipo_envio debe ser 'cliente' tras el wipe (constraint coherencia)"


def test_wipe_returns_404_outside_development(client, admin_auth_headers, con_permiso_wipe, monkeypatch) -> None:
    """Fuera de development el endpoint debe ser indistinguible de una ruta inexistente (404)."""
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")

    response = client.post(
        f"{BASE}/testing/wipe-compras",
        json={"confirmacion": "WIPE", "incluir_caja_banco": False},
        headers=admin_auth_headers,
    )

    assert response.status_code == 404

    # Indistinguishability: byte-equal to a genuinely unknown route.
    control = client.post("/api/this-route-does-not-exist-xyz", json={})
    assert response.status_code == control.status_code
    assert response.json() == control.json()
    assert response.headers.get("content-type") == control.headers.get("content-type")
