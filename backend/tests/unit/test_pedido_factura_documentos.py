"""PR1 — factura rows (option A), tipo/responsable gates, 5-minute undo.

Covers:
  - empty / whitespace numero → HTTP 422, no row, no alert
  - seed `A-1; A-2; ;A-3` → 3 rows; raw `facturas_documento` kept
  - ERP `ct_transaction_id` alone is NOT factura cargada
  - default tipo=mercaderia; responsable_id = creado_por_id
  - PM PATCH tipo after create → 403; admin succeeds
  - POST 201; undo ≤5m → 204; >5m → 409
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from sqlalchemy import func

from app.models.empresa import Empresa
from app.models.notificacion import Notificacion
from app.models.pedido_compra import PedidoCompra
from app.models.pedido_factura_documento import PedidoFacturaDocumento
from app.models.proveedor import OrigenProveedor, Proveedor
from app.models.usuario import RolUsuario, Usuario
from app.services import pedidos_service


BASE = "/api/administracion/compras"


@pytest.fixture
def empresa(db) -> Empresa:
    emp = Empresa(id=1, nombre="Empresa Factura Docs", activo=True, orden=0)
    db.add(emp)
    db.flush()
    return emp


@pytest.fixture
def proveedor(db) -> Proveedor:
    prov = Proveedor(
        id=1,
        nombre="Proveedor Factura Docs",
        activo=True,
        origen=OrigenProveedor.ERP.value,
        supp_id=100,
    )
    db.add(prov)
    db.flush()
    return prov


def _pedido(
    db,
    empresa: Empresa,
    proveedor: Proveedor,
    user: Usuario,
    *,
    numero: str = "P-01-2026-00001",
    ct_transaction_id: int | None = None,
    facturas_documento: str | None = None,
) -> PedidoCompra:
    pedido = PedidoCompra(
        numero=numero,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto=Decimal("1000.00"),
        estado="borrador",
        creado_por_id=user.id,
        ct_transaction_id=ct_transaction_id,
        facturas_documento=facturas_documento,
    )
    db.add(pedido)
    db.flush()
    return pedido


@pytest.fixture
def con_permiso_gestionar_oc():
    def _fake(self, user, codigo):
        return codigo == "administracion.gestionar_ordenes_compra"

    with (
        patch(
            "app.services.permisos_service.PermisosService.tiene_permiso",
            new=_fake,
        ),
        patch(
            "app.services.permisos_service.PermisosService.obtener_permisos_usuario",
            return_value={"administracion.gestionar_ordenes_compra"},
        ),
    ):
        yield


# ──────────────────────────────────────────────────────────────────────────
# 1.1 Seed + cargada vs ERP + empty 422
# ──────────────────────────────────────────────────────────────────────────


class TestSeedFacturasDocumento:
    def test_semicolon_tokens_become_three_rows(self, db, empresa, proveedor, active_user) -> None:
        raw = "A-1; A-2; ;A-3"
        pedido = _pedido(
            db,
            empresa,
            proveedor,
            active_user,
            facturas_documento=raw,
        )
        rows = pedidos_service.seed_factura_documentos(db, pedido)
        db.flush()
        assert [row.numero for row in rows] == ["A-1", "A-2", "A-3"]
        persisted = (
            db.query(PedidoFacturaDocumento)
            .filter(PedidoFacturaDocumento.pedido_id == pedido.id)
            .order_by(PedidoFacturaDocumento.id)
            .all()
        )
        assert [row.numero for row in persisted] == ["A-1", "A-2", "A-3"]
        assert pedido.facturas_documento == raw

    def test_empty_or_separator_only_seeds_nothing(self, db, empresa, proveedor, active_user) -> None:
        pedido = _pedido(
            db,
            empresa,
            proveedor,
            active_user,
            facturas_documento=" ; ; ",
        )
        rows = pedidos_service.seed_factura_documentos(db, pedido)
        db.flush()
        assert rows == []
        assert (
            db.query(PedidoFacturaDocumento)
            .filter(PedidoFacturaDocumento.pedido_id == pedido.id)
            .count()
            == 0
        )


class TestFacturaCargadaVsErp:
    def test_erp_link_without_rows_is_not_cargada(self, db, empresa, proveedor, active_user) -> None:
        pedido = _pedido(
            db,
            empresa,
            proveedor,
            active_user,
            ct_transaction_id=999001,
        )
        assert pedidos_service.es_factura_cargada(db, pedido.id) is False

    def test_row_makes_factura_cargada(self, db, empresa, proveedor, active_user) -> None:
        pedido = _pedido(db, empresa, proveedor, active_user, ct_transaction_id=None)
        pedidos_service.agregar_factura_documento(
            db,
            pedido_id=pedido.id,
            numero="FA-100",
            user_id=active_user.id,
        )
        db.flush()
        assert pedidos_service.es_factura_cargada(db, pedido.id) is True


class TestEmptyNumeroRejected:
    @pytest.mark.parametrize("numero", ["", "   ", "\t"])
    def test_empty_number_422_no_row_no_alert(
        self,
        db,
        empresa,
        proveedor,
        active_user,
        numero: str,
    ) -> None:
        pedido = _pedido(db, empresa, proveedor, active_user)
        with pytest.raises(HTTPException) as exc_info:
            pedidos_service.agregar_factura_documento(
                db,
                pedido_id=pedido.id,
                numero=numero,
                user_id=active_user.id,
            )
        assert exc_info.value.status_code == 422
        assert (
            db.query(PedidoFacturaDocumento)
            .filter(PedidoFacturaDocumento.pedido_id == pedido.id)
            .count()
            == 0
        )
        assert db.query(func.count(Notificacion.id)).scalar() == 0


# ──────────────────────────────────────────────────────────────────────────
# 1.3 tipo / responsable
# ──────────────────────────────────────────────────────────────────────────


class TestTipoYResponsable:
    def test_crear_pedido_defaults_tipo_mercaderia_and_responsable(
        self, db, empresa, proveedor, active_user
    ) -> None:
        pedido = pedidos_service.crear_pedido(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("2500.00"),
            creado_por_id=active_user.id,
        )
        assert pedido.tipo == "mercaderia"
        assert pedido.responsable_id == active_user.id

    def test_pm_cannot_patch_tipo_after_create(
        self, db, empresa, proveedor, active_user
    ) -> None:
        pedido = pedidos_service.crear_pedido(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("2500.00"),
            creado_por_id=active_user.id,
        )
        with pytest.raises(HTTPException) as exc_info:
            pedidos_service.editar_pedido(
                db,
                pedido_id=pedido.id,
                user_id=active_user.id,
                actor=active_user,
                tipo="servicio",
            )
        assert exc_info.value.status_code == 403
        db.refresh(pedido)
        assert pedido.tipo == "mercaderia"

    def test_admin_can_patch_tipo_after_create(
        self, db, empresa, proveedor, active_user, admin_user
    ) -> None:
        pedido = pedidos_service.crear_pedido(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("2500.00"),
            creado_por_id=active_user.id,
        )
        updated = pedidos_service.editar_pedido(
            db,
            pedido_id=pedido.id,
            user_id=admin_user.id,
            actor=admin_user,
            tipo="servicio",
        )
        assert updated.tipo == "servicio"

    def test_non_editor_cannot_change_responsable(
        self, db, empresa, proveedor, active_user, admin_user
    ) -> None:
        pedido = pedidos_service.crear_pedido(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("2500.00"),
            creado_por_id=admin_user.id,
        )
        assert active_user.rol == RolUsuario.VENTAS
        with pytest.raises(HTTPException) as exc_info:
            pedidos_service.editar_pedido(
                db,
                pedido_id=pedido.id,
                user_id=active_user.id,
                actor=active_user,
                responsable_id=active_user.id,
            )
        assert exc_info.value.status_code == 403


# ──────────────────────────────────────────────────────────────────────────
# 1.4 POST / DELETE routes
# ──────────────────────────────────────────────────────────────────────────


class TestFacturaDocumentoRoutes:
    def test_post_factura_201(
        self,
        client,
        db,
        empresa,
        proveedor,
        admin_user,
        admin_auth_headers,
        con_permiso_gestionar_oc,
    ) -> None:
        pedido = _pedido(db, empresa, proveedor, admin_user, numero="P-01-2026-00011")
        response = client.post(
            f"{BASE}/pedidos/{pedido.id}/factura-documentos",
            json={"numero": "FA-201"},
            headers=admin_auth_headers,
        )
        assert response.status_code == 201
        body = response.json()
        assert body["numero"] == "FA-201"
        assert body["pedido_id"] == pedido.id
        assert pedidos_service.es_factura_cargada(db, pedido.id) is True

    def test_undo_inside_five_minutes_204(
        self,
        client,
        db,
        empresa,
        proveedor,
        admin_user,
        admin_auth_headers,
        con_permiso_gestionar_oc,
    ) -> None:
        pedido = _pedido(db, empresa, proveedor, admin_user, numero="P-01-2026-00012")
        row = pedidos_service.agregar_factura_documento(
            db,
            pedido_id=pedido.id,
            numero="FA-204",
            user_id=admin_user.id,
        )
        row.created_at = datetime.now(timezone.utc) - timedelta(minutes=2)
        db.commit()
        db.refresh(row)
        response = client.delete(
            f"{BASE}/pedidos/{pedido.id}/factura-documentos/{row.id}",
            headers=admin_auth_headers,
        )
        assert response.status_code == 204
        assert db.get(PedidoFacturaDocumento, row.id) is None
        assert pedidos_service.es_factura_cargada(db, pedido.id) is False

    def test_undo_after_five_minutes_409(
        self,
        client,
        db,
        empresa,
        proveedor,
        admin_user,
        admin_auth_headers,
        con_permiso_gestionar_oc,
    ) -> None:
        pedido = _pedido(db, empresa, proveedor, admin_user, numero="P-01-2026-00013")
        row = pedidos_service.agregar_factura_documento(
            db,
            pedido_id=pedido.id,
            numero="FA-409",
            user_id=admin_user.id,
        )
        row.created_at = datetime.now(timezone.utc) - timedelta(minutes=6)
        db.commit()
        db.refresh(row)
        response = client.delete(
            f"{BASE}/pedidos/{pedido.id}/factura-documentos/{row.id}",
            headers=admin_auth_headers,
        )
        assert response.status_code == 409
        assert db.get(PedidoFacturaDocumento, row.id) is not None
        assert pedidos_service.es_factura_cargada(db, pedido.id) is True
