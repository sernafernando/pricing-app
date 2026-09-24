"""Phase 1 — resolver faltantes: required texto, writer, stamp, no new estado."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models.empresa import Empresa
from app.models.notificacion import EstadoNotificacion, Notificacion
from app.models.pedido_compra import PedidoCompra
from app.models.proveedor import OrigenProveedor, Proveedor
from app.models.usuario import Usuario
from app.schemas.recepcion import ResolverFaltantesRequest
from app.services import compras_alertas_service, recepcion_service


STAMP = datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def empresa(db) -> Empresa:
    emp = Empresa(id=1, nombre="Empresa Resolver", activo=True, orden=0)
    db.add(emp)
    db.flush()
    return emp


@pytest.fixture
def proveedor(db) -> Proveedor:
    prov = Proveedor(
        id=1,
        nombre="Acme Resolver",
        activo=True,
        origen=OrigenProveedor.ERP.value,
        supp_id=210,
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
    estado: str = "con_faltantes",
    responsable_id: int | None = None,
    faltantes_resuelto_en: datetime | None = None,
) -> PedidoCompra:
    pedido = PedidoCompra(
        numero="P-01-2026-00077",
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto=Decimal("1000.00"),
        estado=estado,
        creado_por_id=user.id,
        responsable_id=responsable_id or user.id,
        faltantes_resuelto_en=faltantes_resuelto_en,
    )
    db.add(pedido)
    db.flush()
    return pedido


class TestResolverFaltantesRequest:
    def test_texto_required_nonempty_strip(self) -> None:
        parsed = ResolverFaltantesRequest(texto="  Comprar 2 cajas  ")
        assert parsed.texto == "Comprar 2 cajas"
        with pytest.raises(ValidationError):
            ResolverFaltantesRequest(texto="   ")
        with pytest.raises(ValidationError):
            ResolverFaltantesRequest(texto="")


class TestResolverFaltantesService:
    def test_empty_texto_422_no_stamp(self, db, empresa, proveedor, active_user) -> None:
        pedido = _pedido(db, empresa, proveedor, active_user)
        with pytest.raises(HTTPException) as exc:
            recepcion_service.resolver_faltantes(db, pedido, active_user, texto="   ", ahora=STAMP)
        assert exc.value.status_code == 422
        assert pedido.faltantes_resuelto_en is None
        assert pedido.estado == "con_faltantes"

    def test_deposito_only_not_responsable_403(self, db, empresa, proveedor, active_user, admin_user) -> None:
        pedido = _pedido(db, empresa, proveedor, admin_user, responsable_id=admin_user.id)

        def _solo_deposito(_self, _user, codigo: str) -> bool:
            return codigo == "deposito.recibir_mercaderia"

        with patch(
            "app.services.permisos_service.PermisosService.tiene_permiso",
            new=_solo_deposito,
        ):
            with pytest.raises(HTTPException) as exc:
                recepcion_service.resolver_faltantes(db, pedido, active_user, texto="Comprar 2 cajas", ahora=STAMP)
        assert exc.value.status_code == 403
        assert pedido.faltantes_resuelto_en is None
        assert pedido.estado == "con_faltantes"

    def test_responsable_stamps_keeps_estado(self, db, empresa, proveedor, active_user) -> None:
        pedido = _pedido(db, empresa, proveedor, active_user, responsable_id=active_user.id)
        result = recepcion_service.resolver_faltantes(db, pedido, active_user, texto="Comprar 2 cajas", ahora=STAMP)
        db.flush()
        assert result.pedido_id == pedido.id
        assert result.faltantes_resuelto_en == STAMP
        assert pedido.faltantes_resuelto_en == STAMP
        assert pedido.estado == "con_faltantes"

    def test_gestionar_oc_not_responsable_ok(self, db, empresa, proveedor, active_user, admin_user) -> None:
        pedido = _pedido(db, empresa, proveedor, admin_user, responsable_id=admin_user.id)

        def _gestionar(_self, _user, codigo: str) -> bool:
            return codigo == "administracion.gestionar_ordenes_compra"

        with patch(
            "app.services.permisos_service.PermisosService.tiene_permiso",
            new=_gestionar,
        ):
            result = recepcion_service.resolver_faltantes(db, pedido, active_user, texto="Comprar 2 cajas", ahora=STAMP)
        assert result.faltantes_resuelto_en == STAMP
        assert pedido.estado == "con_faltantes"

    def test_reresolve_409(self, db, empresa, proveedor, active_user) -> None:
        pedido = _pedido(
            db,
            empresa,
            proveedor,
            active_user,
            faltantes_resuelto_en=STAMP,
        )
        with pytest.raises(HTTPException) as exc:
            recepcion_service.resolver_faltantes(db, pedido, active_user, texto="Otro intento", ahora=STAMP)
        assert exc.value.status_code == 409

    def test_wrong_estado_409(self, db, empresa, proveedor, active_user) -> None:
        pedido = _pedido(db, empresa, proveedor, active_user, estado="recibido")
        with pytest.raises(HTTPException) as exc:
            recepcion_service.resolver_faltantes(db, pedido, active_user, texto="Comprar 2 cajas", ahora=STAMP)
        assert exc.value.status_code == 409

    def test_resolve_retracts_faltantes_alert(self, db, empresa, proveedor, active_user) -> None:
        pedido = _pedido(db, empresa, proveedor, active_user, responsable_id=active_user.id)
        [notif] = compras_alertas_service.notificar_faltantes(db, pedido=pedido, texto="Faltan 2 cajas", ahora=STAMP)
        db.flush()
        recepcion_service.resolver_faltantes(db, pedido, active_user, texto="Comprar 2 cajas", ahora=STAMP)
        db.flush()
        db.refresh(notif)
        assert notif.estado == EstadoNotificacion.DESCARTADA
        leftover = (
            db.query(Notificacion)
            .filter(
                Notificacion.tipo == "compras.faltantes",
                Notificacion.item_id == pedido.id,
                Notificacion.estado != EstadoNotificacion.DESCARTADA,
            )
            .count()
        )
        assert leftover == 0
