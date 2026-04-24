"""
Integration tests del módulo compras — endpoints F5 (design §9).

Cubre los routers de:
  - /pedidos (CRUD + transiciones + etiqueta + eventos)
  - /ordenes-pago (CRUD + pagar + anular + distribuir + 409 dup + 422 moneda)
  - /imputaciones (listado + desimputar + reimputar)
  - /cc-proveedor (detalle + por-pedido)
  - /reconciliacion (listar + forzar + metricas)
  - /sale-documents (listado)
  - /health (smoke gate)

Patrón por endpoint: 401 sin auth, 403 sin permiso, happy path con user
autorizado. Los permisos se mockean a nivel `PermisosService.tiene_permiso`
(misma estrategia que `test_administracion_compras_router.py`) para no
depender del seed que corre en Postgres via Alembic.

La DB subyacente es SQLite in-memory (conftest.py). Los servicios de
compras + caja + CC funcionan bajo SQLite porque:
  - `_patch_pg_types_for_sqlite` hace el downgrade BigInteger PK → Integer.
  - `detectar_duplicado_erp` tiene graceful fallback (tb_commercial_transactions
    no existe en SQLite de tests, retorna []).

Total esperado: ~35 tests. Cada clase agrupa un recurso/verb.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch

import pytest

from app.models.caja import Caja, CajaTipoDocumento
from app.models.empresa import Empresa
from app.models.proveedor import Proveedor
from app.models.proveedor_direccion import ProveedorDireccion
from app.models.tb_sale_document import SaleDocument
from app.services import ordenes_pago_service, pedidos_service
from app.services.ordenes_pago_service import CODIGO_ERROR_DUPLICADO_ERP


# ==========================================================================
# Fixtures
# ==========================================================================


@pytest.fixture
def con_todos_los_permisos():
    """Forza `PermisosService.tiene_permiso → True` y cache vacía en el user."""
    with (
        patch("app.services.permisos_service.PermisosService.tiene_permiso", return_value=True),
        patch("app.services.permisos_service.PermisosService.obtener_permisos_usuario", return_value=set()),
    ):
        yield


@pytest.fixture
def sin_permisos():
    """Forza `PermisosService.tiene_permiso → False`."""
    with (
        patch("app.services.permisos_service.PermisosService.tiene_permiso", return_value=False),
        patch("app.services.permisos_service.PermisosService.obtener_permisos_usuario", return_value=set()),
    ):
        yield


@pytest.fixture
def empresa(db) -> Empresa:
    e = Empresa(nombre="TestEmpresa", activo=True, orden=1)
    db.add(e)
    db.flush()
    return e


@pytest.fixture
def proveedor(db) -> Proveedor:
    p = Proveedor(nombre="TestProveedor", activo=True, origen="manual")
    db.add(p)
    db.flush()
    return p


@pytest.fixture
def caja_ars(db, empresa) -> Caja:
    c = Caja(
        nombre="Caja ARS Test",
        empresa_id=empresa.id,
        moneda="ARS",
        saldo_inicial=Decimal("100000"),
        saldo_actual=Decimal("100000"),
        activo=True,
    )
    db.add(c)
    db.flush()
    return c


@pytest.fixture
def caja_usd(db, empresa) -> Caja:
    c = Caja(
        nombre="Caja USD Test",
        empresa_id=empresa.id,
        moneda="USD",
        saldo_inicial=Decimal("10000"),
        saldo_actual=Decimal("10000"),
        activo=True,
    )
    db.add(c)
    db.flush()
    return c


@pytest.fixture
def seed_caja_tipos(db):
    """Seed de `caja_tipo_documentos` requerido por ejecutar_pago/anular."""
    for nombre in ["Orden de Pago", "Orden de Pago Anulada"]:
        if not db.query(CajaTipoDocumento).filter_by(nombre=nombre).first():
            db.add(CajaTipoDocumento(nombre=nombre, activo=True))
    db.flush()


@pytest.fixture
def seed_contador_numeracion(db):
    """Setea contadores mínimos para que numeracion_service no falle.

    El service hace SELECT FOR UPDATE sobre `numeracion_contadores` por
    (tipo, empresa_id, año). En SQLite la tabla existe pero vacía — el
    service auto-inicializa la fila en 0 si no existe. No hace falta
    seed explícito para happy path.
    """
    yield


@pytest.fixture
def pedido_borrador(db, empresa, proveedor, active_user):
    """Pedido en borrador listo para transiciones."""
    return pedidos_service.crear_pedido(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto=Decimal("5000"),
        creado_por_id=active_user.id,
    )


@pytest.fixture
def pedido_aprobado(db, empresa, proveedor, active_user):
    """Pedido ya aprobado (aprobado_por_id = active_user)."""
    p = pedidos_service.crear_pedido(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto=Decimal("5000"),
        creado_por_id=active_user.id,
    )
    pedidos_service.transicionar(db, pedido_id=p.id, accion="enviar_aprobacion", user_id=active_user.id)
    pedidos_service.transicionar(db, pedido_id=p.id, accion="aprobar", user_id=active_user.id)
    db.flush()
    return p


@pytest.fixture
def direccion_proveedor(db, proveedor) -> ProveedorDireccion:
    d = ProveedorDireccion(
        proveedor_id=proveedor.id,
        etiqueta="Depósito principal",
        direccion="Calle Falsa 123",
        cp="1234",
        ciudad="CABA",
        provincia="CABA",
        contacto_nombre="Juan Perez",
        contacto_telefono="11-0000-0000",
        origen="manual",
        activo=True,
    )
    db.add(d)
    db.flush()
    return d


@pytest.fixture
def sale_documents_seed(db):
    """Mini-seed de tb_sale_document para que el endpoint /sale-documents
    y /health retornen count > 0 bajo SQLite de tests."""
    if not db.query(SaleDocument).first():
        db.add_all(
            [
                SaleDocument(sd_id=101, sd_desc="Factura", sd_ispurchase=True, sd_plusorminus=1),
                SaleDocument(sd_id=103, sd_desc="Nota de Credito", sd_iscreditnote=True, sd_plusorminus=-1),
                SaleDocument(sd_id=106, sd_desc="Orden de Pago", sd_plusorminus=-1),
            ]
        )
        db.flush()


BASE = "/api/administracion/compras"


# ==========================================================================
# Auth / permisos básicos
# ==========================================================================


class TestAuthYPermisos:
    def test_sin_token_pedidos_401(self, client):
        r = client.get(f"{BASE}/pedidos")
        assert r.status_code in (401, 403)

    def test_sin_token_ordenes_pago_401(self, client):
        r = client.get(f"{BASE}/ordenes-pago")
        assert r.status_code in (401, 403)

    def test_sin_permiso_crear_pedido_403(self, client, auth_headers, sin_permisos):
        r = client.post(
            f"{BASE}/pedidos",
            headers=auth_headers,
            json={
                "empresa_id": 1,
                "proveedor_id": 1,
                "moneda": "ARS",
                "monto": "100",
            },
        )
        assert r.status_code == 403


# ==========================================================================
# Pedidos — CRUD
# ==========================================================================


class TestPedidosCRUD:
    def test_crear_pedido_happy_201(self, client, auth_headers, empresa, proveedor, con_todos_los_permisos):
        r = client.post(
            f"{BASE}/pedidos",
            headers=auth_headers,
            json={
                "empresa_id": empresa.id,
                "proveedor_id": proveedor.id,
                "moneda": "ARS",
                "monto": "1500.00",
                "requiere_envio": False,
            },
        )
        assert r.status_code == 201, r.text
        data = r.json()
        assert data["estado"] == "borrador"
        assert data["numero"].startswith("P-")
        assert Decimal(data["monto"]) == Decimal("1500.00")

    def test_crear_pedido_monto_invalido_422(self, client, auth_headers, empresa, proveedor, con_todos_los_permisos):
        r = client.post(
            f"{BASE}/pedidos",
            headers=auth_headers,
            json={
                "empresa_id": empresa.id,
                "proveedor_id": proveedor.id,
                "moneda": "ARS",
                "monto": "0",
            },
        )
        # Pydantic validator `gt=0` devuelve 422
        assert r.status_code == 422

    def test_listar_pedidos_ok(self, client, auth_headers, pedido_borrador, con_todos_los_permisos):
        r = client.get(f"{BASE}/pedidos", headers=auth_headers)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["total"] >= 1
        encontrado = next((p for p in data["items"] if p["id"] == pedido_borrador.id), None)
        assert encontrado is not None
        # Batch A.1: el listado incluye nombres derivados vía joinedload.
        assert encontrado["empresa_nombre"] == "TestEmpresa"
        assert encontrado["proveedor_nombre"] == "TestProveedor"

    def test_obtener_pedido_detalle(self, client, auth_headers, pedido_borrador, con_todos_los_permisos):
        r = client.get(f"{BASE}/pedidos/{pedido_borrador.id}", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert data["id"] == pedido_borrador.id
        assert "eventos" in data
        assert "imputaciones" in data
        # Batch A.1: detalle también incluye nombres derivados.
        assert data["empresa_nombre"] == "TestEmpresa"
        assert data["proveedor_nombre"] == "TestProveedor"
        # El evento 'creado' debe aparecer
        tipos_ev = {e["tipo"] for e in data["eventos"]}
        assert "creado" in tipos_ev

    def test_obtener_pedido_inexistente_404(self, client, auth_headers, con_todos_los_permisos):
        r = client.get(f"{BASE}/pedidos/999999", headers=auth_headers)
        assert r.status_code == 404

    def test_editar_pedido_borrador_happy(self, client, auth_headers, pedido_borrador, con_todos_los_permisos):
        r = client.put(
            f"{BASE}/pedidos/{pedido_borrador.id}",
            headers=auth_headers,
            json={"monto": "7500.00"},
        )
        assert r.status_code == 200, r.text
        assert Decimal(r.json()["monto"]) == Decimal("7500.00")


# ==========================================================================
# Pedidos — transiciones
# ==========================================================================


class TestPedidosTransiciones:
    def test_enviar_a_aprobacion(self, client, auth_headers, pedido_borrador, con_todos_los_permisos):
        r = client.post(
            f"{BASE}/pedidos/{pedido_borrador.id}/enviar-aprobacion",
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text
        assert r.json()["estado"] == "pendiente_aprobacion"

    def test_aprobar_pedido_happy(self, client, auth_headers, pedido_borrador, con_todos_los_permisos):
        # Primero enviar a aprobación
        client.post(f"{BASE}/pedidos/{pedido_borrador.id}/enviar-aprobacion", headers=auth_headers)
        r = client.post(
            f"{BASE}/pedidos/{pedido_borrador.id}/aprobar",
            headers=auth_headers,
            json={},
        )
        assert r.status_code == 200, r.text
        assert r.json()["estado"] == "aprobado"

    def test_aprobar_en_estado_invalido_400(self, client, auth_headers, pedido_borrador, con_todos_los_permisos):
        # Sin enviar a aprobación → borrador no puede aprobar directo
        r = client.post(
            f"{BASE}/pedidos/{pedido_borrador.id}/aprobar",
            headers=auth_headers,
            json={},
        )
        assert r.status_code == 400

    def test_aprobar_sin_permiso_403(self, client, auth_headers, pedido_borrador, sin_permisos):
        r = client.post(
            f"{BASE}/pedidos/{pedido_borrador.id}/aprobar",
            headers=auth_headers,
            json={},
        )
        assert r.status_code == 403

    def test_rechazar_sin_accion_400(self, client, auth_headers, pedido_borrador, con_todos_los_permisos):
        client.post(f"{BASE}/pedidos/{pedido_borrador.id}/enviar-aprobacion", headers=auth_headers)
        r = client.post(
            f"{BASE}/pedidos/{pedido_borrador.id}/rechazar",
            headers=auth_headers,
            json={"motivo": "sin accion"},
        )
        assert r.status_code == 400
        body = r.json()
        # El exception handler del proyecto envuelve el detail en `error.message`
        msg = body.get("detail") or body.get("error", {}).get("message", "")
        assert "accion" in str(msg).lower()

    def test_rechazar_devolver_happy(self, client, auth_headers, pedido_borrador, con_todos_los_permisos):
        """accion='devolver_a_borrador' → rechazar_devolver → estado=rechazado
        (el pedido luego puede reabrirse con POST /reabrir para volver a borrador)."""
        client.post(f"{BASE}/pedidos/{pedido_borrador.id}/enviar-aprobacion", headers=auth_headers)
        r = client.post(
            f"{BASE}/pedidos/{pedido_borrador.id}/rechazar",
            headers=auth_headers,
            json={"accion": "devolver_a_borrador", "motivo": "faltan datos"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["estado"] == "rechazado"

        # Luego se puede reabrir → borrador
        r2 = client.post(
            f"{BASE}/pedidos/{pedido_borrador.id}/reabrir",
            headers=auth_headers,
        )
        assert r2.status_code == 200
        assert r2.json()["estado"] == "borrador"

    def test_cancelar_borrador(self, client, auth_headers, pedido_borrador, con_todos_los_permisos):
        r = client.post(
            f"{BASE}/pedidos/{pedido_borrador.id}/cancelar",
            headers=auth_headers,
            json={},
        )
        assert r.status_code == 200
        assert r.json()["estado"] == "cancelado"


# ==========================================================================
# Pedidos — etiqueta + eventos
# ==========================================================================


class TestPedidosEtiquetaYEventos:
    @pytest.fixture
    def pedido_con_envio(self, db, empresa, proveedor, active_user):
        return pedidos_service.crear_pedido(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("1000"),
            creado_por_id=active_user.id,
            requiere_envio=True,
        )

    def test_generar_etiqueta_happy(
        self, client, auth_headers, pedido_con_envio, direccion_proveedor, con_todos_los_permisos
    ):
        r = client.post(
            f"{BASE}/pedidos/{pedido_con_envio.id}/generar-etiqueta-envio",
            headers=auth_headers,
            json={"proveedor_direccion_id": direccion_proveedor.id},
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["tipo_envio"] == "retiro_proveedor"
        assert data["pedido_compra_id"] == pedido_con_envio.id
        assert data["shipping_id"].startswith("RETIRO-")

    def test_generar_etiqueta_sin_requiere_envio_400(
        self, client, auth_headers, pedido_borrador, con_todos_los_permisos
    ):
        r = client.post(
            f"{BASE}/pedidos/{pedido_borrador.id}/generar-etiqueta-envio",
            headers=auth_headers,
            json={},
        )
        assert r.status_code == 400

    def test_generar_etiqueta_ya_existe_409(
        self, client, auth_headers, pedido_con_envio, direccion_proveedor, con_todos_los_permisos
    ):
        # Primera vez OK
        r1 = client.post(
            f"{BASE}/pedidos/{pedido_con_envio.id}/generar-etiqueta-envio",
            headers=auth_headers,
            json={"proveedor_direccion_id": direccion_proveedor.id},
        )
        assert r1.status_code == 200
        # Segunda vez → 409
        r2 = client.post(
            f"{BASE}/pedidos/{pedido_con_envio.id}/generar-etiqueta-envio",
            headers=auth_headers,
            json={"proveedor_direccion_id": direccion_proveedor.id},
        )
        assert r2.status_code == 409

    def test_listar_eventos(self, client, auth_headers, pedido_borrador, con_todos_los_permisos):
        r = client.get(f"{BASE}/pedidos/{pedido_borrador.id}/eventos", headers=auth_headers)
        assert r.status_code == 200
        eventos = r.json()
        assert any(e["tipo"] == "creado" for e in eventos)


# ==========================================================================
# Órdenes de Pago — CRUD + create con 409 duplicado
# ==========================================================================


class TestOrdenesPagoCRUD:
    def test_crear_op_happy_201(
        self, client, auth_headers, empresa, proveedor, pedido_aprobado, con_todos_los_permisos
    ):
        r = client.post(
            f"{BASE}/ordenes-pago",
            headers=auth_headers,
            json={
                "empresa_id": empresa.id,
                "proveedor_id": proveedor.id,
                "moneda": "ARS",
                "monto_total": "5000",
                "modo_imputacion": "especifica",
                "items": [{"tipo": "pedido_compra", "id": pedido_aprobado.id, "monto": "5000"}],
            },
        )
        assert r.status_code == 201, r.text
        data = r.json()
        assert data["estado"] == "pendiente"
        assert data["numero"].startswith("OP-")

    def test_crear_op_monto_invalido_422(self, client, auth_headers, empresa, proveedor, con_todos_los_permisos):
        r = client.post(
            f"{BASE}/ordenes-pago",
            headers=auth_headers,
            json={
                "empresa_id": empresa.id,
                "proveedor_id": proveedor.id,
                "moneda": "ARS",
                "monto_total": "0",
                "modo_imputacion": "a_cuenta",
                "items": [],
            },
        )
        assert r.status_code == 422  # pydantic gt=0

    def test_crear_op_duplicado_sin_confirmar_409(
        self, client, auth_headers, db, empresa, proveedor, pedido_aprobado, con_todos_los_permisos
    ):
        """Con duplicado detectado y `confirmar_duplicado=False` → 409 POSIBLE_DUPLICADO_OP_ERP.

        Forzamos el mock de `detectar_duplicado_erp` porque SQLite de tests
        no tiene la tabla `tb_commercial_transactions` con filas reales.
        """
        empresa_id = empresa.id
        proveedor_id = proveedor.id
        pedido_id = pedido_aprobado.id

        with patch(
            "app.services.ordenes_pago_service.detectar_duplicado_erp",
            return_value=[
                {
                    "ct_transaction": 12345,
                    "ct_date": datetime.now(),
                    "ct_docnumber": "F-00001",
                    "ct_total": "5000",
                }
            ],
        ):
            r = client.post(
                f"{BASE}/ordenes-pago",
                headers=auth_headers,
                json={
                    "empresa_id": empresa_id,
                    "proveedor_id": proveedor_id,
                    "moneda": "ARS",
                    "monto_total": "5000",
                    "modo_imputacion": "especifica",
                    "items": [
                        {
                            "tipo": "pedido_compra",
                            "id": pedido_id,
                            "monto": "5000",
                            "numero_factura": "F-00001",
                        }
                    ],
                    "confirmar_duplicado": False,
                },
            )
            assert r.status_code == 409, r.text
            body = r.json()
            # COMPRAS-7.2: el exception_handler ahora preserva el dict
            # estructurado del service (clave `codigo` en castellano) como
            # raíz del body, en vez de stringificarlo vía el fallback.
            # Validamos el contrato COMPLETO que consume el frontend.
            assert isinstance(body, dict), f"Expected dict body, got: {body!r}"
            assert body["codigo"] == CODIGO_ERROR_DUPLICADO_ERP
            assert "mensaje" in body and isinstance(body["mensaje"], str)
            assert body["flag_confirmacion"] == "confirmar_duplicado"
            assert "duplicados_detectados" in body
            assert isinstance(body["duplicados_detectados"], list)
            assert len(body["duplicados_detectados"]) == 1

    def test_crear_op_duplicado_confirmado_201(
        self, client, auth_headers, db, empresa, proveedor, pedido_aprobado, con_todos_los_permisos
    ):
        """Con `confirmar_duplicado=True` la OP se crea aunque haya match en ERP.

        Usamos ct_date como string ISO para evitar el issue de
        JSON-no-serializable de datetime bajo SQLite (el payload se persiste
        como JSONB en Postgres real — el datetime ahí se serializa).
        """
        empresa_id = empresa.id
        proveedor_id = proveedor.id
        pedido_id = pedido_aprobado.id

        with patch(
            "app.services.ordenes_pago_service.detectar_duplicado_erp",
            return_value=[
                {
                    "ct_transaction": 12345,
                    "ct_date": datetime.now().isoformat(),
                    "ct_docnumber": "F-00001",
                    "ct_total": "5000",
                }
            ],
        ):
            r = client.post(
                f"{BASE}/ordenes-pago",
                headers=auth_headers,
                json={
                    "empresa_id": empresa_id,
                    "proveedor_id": proveedor_id,
                    "moneda": "ARS",
                    "monto_total": "5000",
                    "modo_imputacion": "especifica",
                    "items": [
                        {
                            "tipo": "pedido_compra",
                            "id": pedido_id,
                            "monto": "5000",
                            "numero_factura": "F-00001",
                        }
                    ],
                    "confirmar_duplicado": True,
                },
            )
            assert r.status_code == 201, r.text

    def test_listar_ops(self, client, auth_headers, db, empresa, proveedor, active_user, con_todos_los_permisos):
        # Crear una OP directamente via service (sin HTTP) para independencia
        op = ordenes_pago_service.crear(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            moneda="ARS",
            monto_total=Decimal("1000"),
            modo_imputacion="a_cuenta",
            items=[],
            creado_por_id=active_user.id,
        )
        db.commit()
        r = client.get(f"{BASE}/ordenes-pago", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert data["total"] >= 1
        encontrado = next((o for o in data["items"] if o["id"] == op.id), None)
        assert encontrado is not None
        # Batch A.1: el listado de OPs incluye nombres derivados.
        assert encontrado["empresa_nombre"] == "TestEmpresa"
        assert encontrado["proveedor_nombre"] == "TestProveedor"

    def test_obtener_op_detalle(
        self, client, auth_headers, db, empresa, proveedor, active_user, con_todos_los_permisos
    ):
        op = ordenes_pago_service.crear(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            moneda="ARS",
            monto_total=Decimal("1000"),
            modo_imputacion="a_cuenta",
            items=[],
            creado_por_id=active_user.id,
        )
        db.commit()
        r = client.get(f"{BASE}/ordenes-pago/{op.id}", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert data["id"] == op.id
        assert "imputaciones" in data
        assert "eventos" in data
        # Batch A.1: detalle de OP también incluye nombres derivados.
        assert data["empresa_nombre"] == "TestEmpresa"
        assert data["proveedor_nombre"] == "TestProveedor"

    def test_obtener_op_detalle_pendiente_sin_caja_movimiento_resumen(
        self, client, auth_headers, db, empresa, proveedor, active_user, con_todos_los_permisos
    ):
        """Batch F.1: OP pendiente → `caja_movimiento_resumen` debe ser None."""
        op = ordenes_pago_service.crear(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            moneda="ARS",
            monto_total=Decimal("1000"),
            modo_imputacion="a_cuenta",
            items=[],
            creado_por_id=active_user.id,
        )
        db.commit()

        r = client.get(f"{BASE}/ordenes-pago/{op.id}", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert data["estado"] == "pendiente"
        assert "caja_movimiento_resumen" in data
        assert data["caja_movimiento_resumen"] is None

    def test_obtener_op_detalle_pagada_incluye_caja_movimiento_resumen(
        self,
        client,
        auth_headers,
        db,
        empresa,
        proveedor,
        caja_ars,
        seed_caja_tipos,
        active_user,
        pedido_aprobado,
        con_todos_los_permisos,
    ):
        """Batch F.1: OP pagada → `caja_movimiento_resumen` con caja+monto+fecha.

        Garantiza que tesorería ve quién pagó/cuánto/cuándo/en qué caja sin
        hacer un segundo request al módulo de caja.
        """
        op = ordenes_pago_service.crear(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            moneda="ARS",
            monto_total=Decimal("1000"),
            modo_imputacion="especifica",
            items=[{"tipo": "pedido_compra", "id": pedido_aprobado.id, "monto": Decimal("1000")}],
            creado_por_id=active_user.id,
        )
        ordenes_pago_service.ejecutar_pago(
            db,
            orden_pago_id=op.id,
            caja_id=caja_ars.id,
            fecha_pago_real=date.today(),
            user_id=active_user.id,
        )
        db.commit()

        r = client.get(f"{BASE}/ordenes-pago/{op.id}", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert data["estado"] == "pagado"
        resumen = data["caja_movimiento_resumen"]
        assert resumen is not None
        assert resumen["caja_id"] == caja_ars.id
        assert resumen["caja_nombre"] == "Caja ARS Test"
        assert resumen["tipo"] == "egreso"
        assert Decimal(resumen["monto"]) == Decimal("1000")
        assert resumen["fecha"] == date.today().isoformat()


# ==========================================================================
# Órdenes de Pago — pagar + anular + distribuir
# ==========================================================================


class TestOrdenesPagoPagar:
    def test_pagar_caja_moneda_distinta_422(
        self,
        client,
        auth_headers,
        db,
        empresa,
        proveedor,
        caja_usd,
        seed_caja_tipos,
        active_user,
        pedido_aprobado,
        con_todos_los_permisos,
    ):
        """OP ARS + caja USD → 422 OP_CAJA_MONEDA_MISMATCH."""
        op = ordenes_pago_service.crear(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            moneda="ARS",
            monto_total=Decimal("1000"),
            modo_imputacion="especifica",
            items=[{"tipo": "pedido_compra", "id": pedido_aprobado.id, "monto": Decimal("1000")}],
            creado_por_id=active_user.id,
        )
        db.commit()

        r = client.post(
            f"{BASE}/ordenes-pago/{op.id}/pagar",
            headers=auth_headers,
            json={"caja_id": caja_usd.id, "fecha_pago_real": date.today().isoformat()},
        )
        assert r.status_code == 422, r.text
        body = r.json()
        # COMPRAS-7.2: payload estructurado preservado (no stringificado).
        assert isinstance(body, dict), f"Expected dict body, got: {body!r}"
        assert body["codigo"] == "OP_CAJA_MONEDA_MISMATCH"
        assert "mensaje" in body and isinstance(body["mensaje"], str)

    def test_pagar_happy(
        self,
        client,
        auth_headers,
        db,
        empresa,
        proveedor,
        caja_ars,
        seed_caja_tipos,
        active_user,
        pedido_aprobado,
        con_todos_los_permisos,
    ):
        """Pago exitoso: estado pagado + caja_movimiento_id seteado."""
        op = ordenes_pago_service.crear(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            moneda="ARS",
            monto_total=Decimal("1000"),
            modo_imputacion="especifica",
            items=[{"tipo": "pedido_compra", "id": pedido_aprobado.id, "monto": Decimal("1000")}],
            creado_por_id=active_user.id,
        )
        db.commit()

        r = client.post(
            f"{BASE}/ordenes-pago/{op.id}/pagar",
            headers=auth_headers,
            json={"caja_id": caja_ars.id, "fecha_pago_real": date.today().isoformat()},
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["estado"] == "pagado"
        assert data["caja_movimiento_id"] is not None
        assert data["caja_documento_id"] is not None

    def test_pagar_sin_permiso_403(self, client, auth_headers, sin_permisos):
        r = client.post(
            f"{BASE}/ordenes-pago/1/pagar",
            headers=auth_headers,
            json={"caja_id": 1, "fecha_pago_real": date.today().isoformat()},
        )
        assert r.status_code == 403

    def test_anular_op_pagada(
        self,
        client,
        auth_headers,
        db,
        empresa,
        proveedor,
        caja_ars,
        seed_caja_tipos,
        active_user,
        pedido_aprobado,
        con_todos_los_permisos,
    ):
        """OP pagada se puede anular → 200, estado=anulado."""
        op = ordenes_pago_service.crear(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            moneda="ARS",
            monto_total=Decimal("1000"),
            modo_imputacion="especifica",
            items=[{"tipo": "pedido_compra", "id": pedido_aprobado.id, "monto": Decimal("1000")}],
            creado_por_id=active_user.id,
        )
        ordenes_pago_service.ejecutar_pago(
            db,
            orden_pago_id=op.id,
            caja_id=caja_ars.id,
            fecha_pago_real=date.today(),
            user_id=active_user.id,
        )
        db.commit()

        r = client.post(
            f"{BASE}/ordenes-pago/{op.id}/anular",
            headers=auth_headers,
            json={"motivo": "error de carga"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["estado"] == "anulado"

    def test_anular_sin_motivo_400(self, client, auth_headers, con_todos_los_permisos):
        r = client.post(f"{BASE}/ordenes-pago/1/anular", headers=auth_headers, json={})
        assert r.status_code == 400


# ==========================================================================
# Imputaciones
# ==========================================================================


class TestImputaciones:
    @pytest.fixture
    def op_con_imputacion(self, db, empresa, proveedor, caja_ars, seed_caja_tipos, active_user, pedido_aprobado):
        """Crea OP pagada con una imputación viva → devuelve (op, imp_id)."""
        op = ordenes_pago_service.crear(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            moneda="ARS",
            monto_total=Decimal("2000"),
            modo_imputacion="mixta",
            items=[{"tipo": "pedido_compra", "id": pedido_aprobado.id, "monto": Decimal("1000")}],
            creado_por_id=active_user.id,
        )
        ordenes_pago_service.ejecutar_pago(
            db,
            orden_pago_id=op.id,
            caja_id=caja_ars.id,
            fecha_pago_real=date.today(),
            user_id=active_user.id,
        )
        db.commit()

        from app.models.imputacion import Imputacion
        from sqlalchemy import select

        imp = db.execute(
            select(Imputacion).where(
                Imputacion.origen_id == op.id,
                Imputacion.destino_tipo == "pedido_compra",
                Imputacion.es_reversal.is_(False),
            )
        ).scalar_one()
        return op, imp

    def test_listar_imputaciones(self, client, auth_headers, op_con_imputacion, con_todos_los_permisos):
        r = client.get(f"{BASE}/imputaciones", headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["total"] >= 1

    def test_listar_imputaciones_incluye_nombres_derivados(
        self, client, auth_headers, op_con_imputacion, con_todos_los_permisos
    ):
        """REQ-UX: listado devuelve proveedor_nombre + empresa_nombre no nulos."""
        op, _imp = op_con_imputacion
        r = client.get(f"{BASE}/imputaciones", headers=auth_headers, params={"proveedor_id": op.proveedor_id})
        assert r.status_code == 200
        items = r.json()["items"]
        assert len(items) >= 1
        primero = items[0]
        assert primero["proveedor_nombre"] == "TestProveedor"
        assert primero["empresa_nombre"] == "TestEmpresa"

    def test_listar_imputaciones_descripcion_origen_op_destino_pedido(
        self, client, auth_headers, op_con_imputacion, pedido_aprobado, con_todos_los_permisos
    ):
        """REQ-UX: origen_descripcion='OP {numero}', destino_descripcion='Pedido {numero}'."""
        op, _imp = op_con_imputacion
        r = client.get(f"{BASE}/imputaciones", headers=auth_headers, params={"proveedor_id": op.proveedor_id})
        assert r.status_code == 200
        items = r.json()["items"]
        imp_pedido = next(
            (i for i in items if i["destino_tipo"] == "pedido_compra" and not i["es_reversal"]),
            None,
        )
        assert imp_pedido is not None
        assert imp_pedido["origen_descripcion"] == f"OP {op.numero}"
        assert imp_pedido["destino_descripcion"] == f"Pedido {pedido_aprobado.numero}"

    def test_listar_imputaciones_descripcion_destino_saldo(
        self, client, auth_headers, db, op_con_imputacion, active_user, con_todos_los_permisos
    ):
        """REQ-UX: destino_tipo=saldo → destino_descripcion='Saldo a cuenta'."""
        from app.services import imputaciones_service

        _op, imp = op_con_imputacion
        # Reimputar al saldo a cuenta (destino_tipo='saldo', destino_id=None)
        _reversal, nueva = imputaciones_service.reimputar(
            db,
            imputacion_id=imp.id,
            nuevo_destino_tipo="saldo",
            nuevo_destino_id=None,
            user_id=active_user.id,
        )
        db.commit()

        r = client.get(f"{BASE}/imputaciones", headers=auth_headers, params={"proveedor_id": imp.proveedor_id})
        assert r.status_code == 200
        items = r.json()["items"]
        imp_saldo = next((i for i in items if i["id"] == nueva.id), None)
        assert imp_saldo is not None
        assert imp_saldo["destino_tipo"] == "saldo"
        assert imp_saldo["destino_descripcion"] == "Saldo a cuenta"

    def test_desimputar_happy(self, client, auth_headers, op_con_imputacion, con_todos_los_permisos):
        _op, imp = op_con_imputacion
        r = client.post(
            f"{BASE}/imputaciones/{imp.id}/desimputar",
            headers=auth_headers,
            json={"motivo": "error de asignacion"},
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["es_reversal"] is True
        assert data["reimputada_desde_id"] == imp.id

    def test_reimputar_happy(self, client, auth_headers, op_con_imputacion, con_todos_los_permisos):
        _op, imp = op_con_imputacion
        r = client.post(
            f"{BASE}/imputaciones/{imp.id}/reimputar",
            headers=auth_headers,
            json={"destino_tipo": "saldo", "motivo": "mover a saldo"},
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert isinstance(data, list)
        assert len(data) == 2
        reversal, nueva = data
        assert reversal["es_reversal"] is True
        assert nueva["es_reversal"] is False
        assert nueva["destino_tipo"] == "saldo"


# ==========================================================================
# CC Proveedor
# ==========================================================================


class TestCCProveedor:
    def test_cc_proveedor_detalle(self, client, auth_headers, db, proveedor, pedido_aprobado, con_todos_los_permisos):
        # pedido_aprobado ya generó DEBE en CC vía `aprobar`
        r = client.get(f"{BASE}/cc-proveedor/{proveedor.id}", headers=auth_headers)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["proveedor_id"] == proveedor.id
        assert len(data["saldos"]) >= 1
        assert data["saldos"][0]["moneda"] in ("ARS", "USD")

    def test_cc_proveedor_inexistente_404(self, client, auth_headers, con_todos_los_permisos):
        r = client.get(f"{BASE}/cc-proveedor/999999", headers=auth_headers)
        assert r.status_code == 404

    def test_cc_por_pedido(self, client, auth_headers, proveedor, pedido_aprobado, con_todos_los_permisos):
        r = client.get(f"{BASE}/cc-proveedor/{proveedor.id}/por-pedido", headers=auth_headers)
        assert r.status_code == 200
        grupos = r.json()
        # Debería haber al menos el grupo del pedido_aprobado
        assert any(g["pedido_compra_id"] == pedido_aprobado.id for g in grupos)


# ==========================================================================
# Reconciliación
# ==========================================================================


class TestReconciliacion:
    def test_listar_reconciliaciones_vacio(self, client, auth_headers, con_todos_los_permisos):
        r = client.get(f"{BASE}/reconciliacion", headers=auth_headers)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_listar_reconciliaciones_incluye_proveedor_nombre(
        self, client, auth_headers, db, proveedor, con_todos_los_permisos
    ):
        """REQ-UX: los logs devuelven proveedor_nombre no nulo (batch enrichment)."""
        from app.models.cc_reconciliacion_log import CCReconciliacionLog

        log = CCReconciliacionLog(
            fecha_corrida=date.today(),
            proveedor_id=proveedor.id,
            moneda="ARS",
            saldo_libro_mayor=Decimal("1000.00"),
            saldo_snapshot=Decimal("1000.00"),
            diferencia=Decimal("0.00"),
            tolerancia_aplicada=Decimal("100.00"),
            estado="ok",
        )
        db.add(log)
        db.commit()

        r = client.get(f"{BASE}/reconciliacion", headers=auth_headers)
        assert r.status_code == 200
        items = r.json()
        assert len(items) >= 1
        encontrado = next((i for i in items if i["id"] == log.id), None)
        assert encontrado is not None
        assert encontrado["proveedor_nombre"] == "TestProveedor"

    def test_forzar_reconciliacion_happy(self, client, auth_headers, con_todos_los_permisos):
        r = client.post(
            f"{BASE}/reconciliacion/forzar",
            headers=auth_headers,
            json={"fecha": date.today().isoformat()},
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert "proveedores_procesados" in data
        assert "divergencias" in data

    def test_metricas_shape(self, client, auth_headers, con_todos_los_permisos):
        r = client.get(f"{BASE}/reconciliacion/metricas", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert "dias_consecutivos_sin_divergencia" in data
        assert "cobertura_porcentaje" in data
        assert "criterio_deprecacion" in data


# ==========================================================================
# Sale Documents + Health
# ==========================================================================


class TestSaleDocumentsYHealth:
    def test_listar_sale_documents(self, client, auth_headers, sale_documents_seed):
        r = client.get(f"{BASE}/sale-documents", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        assert len(data) >= 3
        # Todos deben traer `clasificacion` (puede ser None si falla)
        for sd in data:
            assert "clasificacion" in sd

    def test_health_sin_auth(self, client, sale_documents_seed):
        """El health NO requiere auth (smoke/readiness)."""
        r = client.get(f"{BASE}/health")
        assert r.status_code == 200
        data = r.json()
        assert data["module"] == "compras"
        assert data["catalogos"]["tb_sale_document"] >= 3
        assert data["status"] == "ok"


# ==========================================================================
# Batch A.3 — N+1 guard sobre listados
# ==========================================================================


class TestListadosNoN1:
    """Valida que los listados de pedidos/OPs usan joinedload y NO disparan
    un SELECT adicional por fila para resolver empresa_nombre/proveedor_nombre.

    Contamos las queries con `sqlalchemy.event.listens_for("before_cursor_execute")`.
    En SQLite la métrica es menos precisa que en Postgres (y tests aislados),
    pero suficiente para detectar regresión: si alguien borra el joinedload,
    veremos ~2*N selects extra (uno por empresa + uno por proveedor).
    """

    def test_listar_pedidos_sin_n1(
        self, client, auth_headers, db, empresa, proveedor, active_user, con_todos_los_permisos
    ):
        """Crear 10 pedidos y listar — el nro de SELECT no debe escalar con N."""
        from sqlalchemy import event

        # Crear 10 pedidos
        for i in range(10):
            pedidos_service.crear_pedido(
                db,
                empresa_id=empresa.id,
                proveedor_id=proveedor.id,
                moneda="ARS",
                monto=Decimal("100") * (i + 1),
                creado_por_id=active_user.id,
            )
        db.commit()

        contador: list[int] = [0]
        engine = db.get_bind()

        def _on_execute(conn, cursor, statement, parameters, context, executemany):
            # Solo contamos SELECTs a las tablas de interés; ignoramos BEGIN/COMMIT
            # y queries del framework (ej. session info).
            s = statement.lstrip().upper()
            if s.startswith("SELECT") and (
                "PEDIDOS_COMPRA" in statement.upper()
                or "EMPRESAS" in statement.upper()
                or "PROVEEDORES" in statement.upper()
            ):
                contador[0] += 1

        event.listen(engine, "before_cursor_execute", _on_execute)
        try:
            r = client.get(f"{BASE}/pedidos?page=1&page_size=50", headers=auth_headers)
        finally:
            event.remove(engine, "before_cursor_execute", _on_execute)

        assert r.status_code == 200
        data = r.json()
        assert data["total"] >= 10
        # Con joinedload esperamos: 1 COUNT + 1 SELECT con LEFT JOIN empresas + proveedores.
        # Sin joinedload serían ~1 + 1 + 10 (empresa) + 10 (proveedor) ≈ 22.
        # Cota conservadora: <= 5 cubre margen para N+1 de CT o eventos colaterales.
        assert contador[0] <= 5, f"posible N+1: {contador[0]} selects disparados (esperado <= 5)"

    def test_listar_ops_sin_n1(self, client, auth_headers, db, empresa, proveedor, active_user, con_todos_los_permisos):
        """Idem para OPs: 10 OPs y contar queries."""
        from sqlalchemy import event

        for i in range(10):
            ordenes_pago_service.crear(
                db,
                proveedor_id=proveedor.id,
                empresa_id=empresa.id,
                moneda="ARS",
                monto_total=Decimal("100") * (i + 1),
                modo_imputacion="a_cuenta",
                items=[],
                creado_por_id=active_user.id,
            )
        db.commit()

        contador: list[int] = [0]
        engine = db.get_bind()

        def _on_execute(conn, cursor, statement, parameters, context, executemany):
            s = statement.lstrip().upper()
            if s.startswith("SELECT") and (
                "ORDENES_PAGO" in statement.upper()
                or "EMPRESAS" in statement.upper()
                or "PROVEEDORES" in statement.upper()
            ):
                contador[0] += 1

        event.listen(engine, "before_cursor_execute", _on_execute)
        try:
            r = client.get(f"{BASE}/ordenes-pago?page=1&page_size=50", headers=auth_headers)
        finally:
            event.remove(engine, "before_cursor_execute", _on_execute)

        assert r.status_code == 200
        data = r.json()
        assert data["total"] >= 10
        assert contador[0] <= 5, f"posible N+1 en OPs: {contador[0]} selects (esperado <= 5)"
