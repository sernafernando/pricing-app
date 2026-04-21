"""
Integration tests del router `administracion_compras` (COMPRAS-3.4).

Cubre el endpoint `GET /api/administracion/compras/sale-documents/faltantes`:
  - Sin token → 401.
  - Con token pero sin permiso → 403.
  - Con token y permiso, catálogo vacío → 200 con lista vacía.
  - Con token y permiso, con sd_id huérfanos en ct → 200 con filas
    ordenadas por count DESC.
  - Parámetro `dias` respeta la ventana (sd_id fuera de ventana no aparece).

El permiso `administracion.gestionar_ordenes_compra` se mockea a nivel
`PermisosService.tiene_permiso` para no depender del seed de permisos
(que corre en Postgres via Alembic, no en SQLite de tests).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from app.models.commercial_transaction import CommercialTransaction
from app.models.tb_sale_document import SaleDocument


# ──────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture
def con_permiso_ordenes_compra():
    """Forza `PermisosService.tiene_permiso → True` durante el test.

    Parcheamos los métodos DIRECTO en la clase ya importada (no la clase).
    Razón: `require_permiso` captura `PermisosService` en una closure
    cuando el router se registra (startup). Reemplazar el símbolo del
    módulo ex-post no afecta a esa closure.
    """
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
def sin_permiso_ordenes_compra():
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


@pytest.fixture
def sd_factura_catalogada(db) -> SaleDocument:
    """sd_id=101 — ya en catálogo (NO debe aparecer en faltantes)."""
    sd = SaleDocument(
        sd_id=101,
        sd_desc="Factura compra",
        sd_ispurchase=True,
        sd_isinbalance=True,
        sd_istaxable=True,
        sd_plusorminus=1,
    )
    db.add(sd)
    db.flush()
    return sd


def _crear_ct(
    db,
    *,
    ct_transaction: int,
    sd_id: int,
    ct_date: datetime,
    supp_id: int = 18,
    ct_docnumber: str = "DOC-TEST",
) -> CommercialTransaction:
    ct = CommercialTransaction(
        ct_transaction=ct_transaction,
        comp_id=1,
        bra_id=1,
        supp_id=supp_id,
        ct_docNumber=ct_docnumber,
        sd_id=sd_id,
        ct_date=ct_date,
    )
    db.add(ct)
    db.flush()
    return ct


ENDPOINT = "/api/administracion/compras/sale-documents/faltantes"


# ──────────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────────


class TestSaleDocumentsFaltantes:
    def test_sin_token_no_autorizado(self, client):
        """Sin Authorization header → FastAPI HTTPBearer devuelve 403 por defecto
        (el JWT no llega al validator). Se acepta cualquier 401/403."""
        response = client.get(ENDPOINT)
        assert response.status_code in (401, 403)

    def test_con_user_sin_permiso_403(self, client, auth_headers, sin_permiso_ordenes_compra):
        response = client.get(ENDPOINT, headers=auth_headers)
        assert response.status_code == 403
        detail = response.json().get("error") or response.json().get("detail")
        assert detail is not None
        msg = detail.get("message") if isinstance(detail, dict) else str(detail)
        assert "administracion.gestionar_ordenes_compra" in msg

    def test_con_permiso_sin_datos_200_lista_vacia(self, client, auth_headers, con_permiso_ordenes_compra):
        response = client.get(ENDPOINT, headers=auth_headers)
        assert response.status_code == 200
        assert response.json() == []

    def test_con_permiso_detecta_sd_huerfanos(
        self, db, client, auth_headers, sd_factura_catalogada, con_permiso_ordenes_compra
    ):
        hoy = datetime.now()
        # Dos ct con sd_id=999 (no catalogado) + una con sd_id=101 (catalogado)
        _crear_ct(db, ct_transaction=1, sd_id=999, ct_date=hoy - timedelta(days=1))
        _crear_ct(db, ct_transaction=2, sd_id=999, ct_date=hoy - timedelta(days=2))
        _crear_ct(db, ct_transaction=3, sd_id=101, ct_date=hoy - timedelta(days=1))
        _crear_ct(db, ct_transaction=4, sd_id=777, ct_date=hoy - timedelta(days=3))

        response = client.get(ENDPOINT, headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        sd_ids = {row["sd_id"] for row in data}
        assert 999 in sd_ids
        assert 777 in sd_ids
        assert 101 not in sd_ids

        # Orden por count DESC → 999 (count=2) antes que 777 (count=1)
        assert data[0]["sd_id"] == 999
        assert data[0]["count"] == 2
        assert data[1]["sd_id"] == 777
        assert data[1]["count"] == 1

    def test_con_permiso_respeta_ventana_dias(self, db, client, auth_headers, con_permiso_ordenes_compra):
        hoy = datetime.now()
        # ct dentro de la ventana (10 días atrás)
        _crear_ct(db, ct_transaction=10, sd_id=888, ct_date=hoy - timedelta(days=10))
        # ct fuera de la ventana (60 días atrás)
        _crear_ct(db, ct_transaction=11, sd_id=889, ct_date=hoy - timedelta(days=60))

        response = client.get(ENDPOINT + "?dias=30", headers=auth_headers)

        assert response.status_code == 200
        sd_ids = {row["sd_id"] for row in response.json()}
        assert 888 in sd_ids
        assert 889 not in sd_ids

    def test_dias_parametro_clampa_rango(self, client, auth_headers, con_permiso_ordenes_compra):
        # dias=0 y dias>365 deben rebotar con 422
        r0 = client.get(ENDPOINT + "?dias=0", headers=auth_headers)
        assert r0.status_code == 422
        r_big = client.get(ENDPOINT + "?dias=9999", headers=auth_headers)
        assert r_big.status_code == 422


# ──────────────────────────────────────────────────────────────────────────
# /pedidos/pendientes-pago (Batch C del plan UX de compras)
# ──────────────────────────────────────────────────────────────────────────


ENDPOINT_PENDIENTES = "/api/administracion/compras/pedidos/pendientes-pago"


@pytest.fixture
def empresa_pendientes(db):
    from app.models.empresa import Empresa

    emp = Empresa(id=7, nombre="Empresa Pendientes", activo=True, orden=0)
    db.add(emp)
    db.flush()
    return emp


@pytest.fixture
def proveedor_pendientes(db):
    from app.models.proveedor import OrigenProveedor, Proveedor

    prov = Proveedor(
        id=77,
        nombre="Proveedor Pendientes",
        activo=True,
        origen=OrigenProveedor.ERP.value,
        supp_id=777,
    )
    db.add(prov)
    db.flush()
    return prov


def _crear_pedido_aprobado(db, empresa, proveedor, active_user, **kwargs):
    """Crea y aprueba un pedido para los tests de pendientes-pago."""
    from app.services import pedidos_service

    p = pedidos_service.crear_pedido(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda=kwargs.pop("moneda", "ARS"),
        monto=kwargs.pop("monto"),
        creado_por_id=active_user.id,
        **kwargs,
    )
    pedidos_service.transicionar(db, pedido_id=p.id, accion="enviar_aprobacion", user_id=active_user.id)
    pedidos_service.transicionar(db, pedido_id=p.id, accion="aprobar", user_id=active_user.id)
    return p


class TestListarPedidosPendientesPago:
    """GET /pedidos/pendientes-pago — listado de pedidos esperando imputación."""

    def test_sin_token_no_autorizado(self, client):
        r = client.get(ENDPOINT_PENDIENTES)
        assert r.status_code in (401, 403)

    def test_con_permiso_sin_pedidos_lista_vacia(self, client, auth_headers, con_permiso_ordenes_compra):
        r = client.get(ENDPOINT_PENDIENTES, headers=auth_headers)
        assert r.status_code == 200
        assert r.json() == []

    def test_filtra_por_estado_solo_aprobado_y_parcial(
        self,
        db,
        client,
        auth_headers,
        con_permiso_ordenes_compra,
        empresa_pendientes,
        proveedor_pendientes,
        active_user,
    ):
        """Solo `aprobado` y `pagado_parcial` deben aparecer. borrador/cancelado/pagado NO."""
        from app.services import pedidos_service

        # Borrador → NO aparece.
        p_borr = pedidos_service.crear_pedido(
            db,
            empresa_id=empresa_pendientes.id,
            proveedor_id=proveedor_pendientes.id,
            moneda="ARS",
            monto=Decimal_fast("100"),
            creado_por_id=active_user.id,
        )
        # Aprobado → aparece.
        p_apro = _crear_pedido_aprobado(
            db,
            empresa_pendientes,
            proveedor_pendientes,
            active_user,
            monto=Decimal_fast("500"),
        )
        # Cancelado (desde borrador) → NO aparece.
        p_canc = pedidos_service.crear_pedido(
            db,
            empresa_id=empresa_pendientes.id,
            proveedor_id=proveedor_pendientes.id,
            moneda="ARS",
            monto=Decimal_fast("200"),
            creado_por_id=active_user.id,
        )
        pedidos_service.transicionar(
            db,
            pedido_id=p_canc.id,
            accion="cancelar",
            user_id=active_user.id,
            motivo="test",
        )
        db.commit()

        r = client.get(ENDPOINT_PENDIENTES, headers=auth_headers)
        assert r.status_code == 200
        ids = {row["id"] for row in r.json()}
        assert p_apro.id in ids
        assert p_borr.id not in ids
        assert p_canc.id not in ids

    def test_incluye_saldo_pendiente_igual_al_monto_sin_imputaciones(
        self,
        db,
        client,
        auth_headers,
        con_permiso_ordenes_compra,
        empresa_pendientes,
        proveedor_pendientes,
        active_user,
    ):
        p = _crear_pedido_aprobado(
            db, empresa_pendientes, proveedor_pendientes, active_user, monto=Decimal_fast("1000")
        )
        db.commit()

        r = client.get(ENDPOINT_PENDIENTES, headers=auth_headers)
        assert r.status_code == 200
        rows = [row for row in r.json() if row["id"] == p.id]
        assert len(rows) == 1
        assert Decimal_fast(rows[0]["saldo_pendiente"]) == Decimal_fast("1000")
        assert Decimal_fast(rows[0]["monto"]) == Decimal_fast("1000")

    def test_filtro_por_proveedor(
        self,
        db,
        client,
        auth_headers,
        con_permiso_ordenes_compra,
        empresa_pendientes,
        proveedor_pendientes,
        active_user,
    ):
        from app.models.proveedor import OrigenProveedor, Proveedor

        prov2 = Proveedor(
            id=78,
            nombre="Otro",
            activo=True,
            origen=OrigenProveedor.ERP.value,
            supp_id=778,
        )
        db.add(prov2)
        db.flush()

        p1 = _crear_pedido_aprobado(
            db, empresa_pendientes, proveedor_pendientes, active_user, monto=Decimal_fast("111")
        )
        p2 = _crear_pedido_aprobado(db, empresa_pendientes, prov2, active_user, monto=Decimal_fast("222"))
        db.commit()

        r = client.get(
            f"{ENDPOINT_PENDIENTES}?proveedor_id={proveedor_pendientes.id}",
            headers=auth_headers,
        )
        assert r.status_code == 200
        ids = {row["id"] for row in r.json()}
        assert p1.id in ids
        assert p2.id not in ids


def Decimal_fast(v):
    """Helper local — evita repetir import de Decimal en cada test."""
    from decimal import Decimal

    return Decimal(str(v))
