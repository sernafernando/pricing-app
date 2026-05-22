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

from app.models.empresa import Empresa
from app.models.proveedor import Proveedor
from app.models.cc_proveedor_movimiento import CCProveedorMovimiento
from app.models.compras_papelera import ComprasPapelera


BASE = "/api/administracion/compras"


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
