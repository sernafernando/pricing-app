"""PR2 — in-app factura / faltantes alerts (D-PERM, D-BANNER, D-SNOOZE).

Covers:
  - copy is Pricing P-number + proveedor + factura nº (never pedidos_documento)
  - fan-out holders of administracion.ver_alertas_factura; ADMIN without code out
  - SUPERADMIN matches via PermisosService resolver, not hardcoded roles
  - empty factura nº creates no alert
  - per-user OK (DESCARTADA) does not clear others
  - undo ≤5m retracts those notifs to DESCARTADA
  - faltantes → responsable_id; empty texto 422; snooze hide until mark+1h
  - factura permiso does not change faltantes recipients
  - resolve → G31 deposito.recibir_mercaderia (D3 excluded)
  - no email / Slack
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.core.security import get_password_hash
from app.models.empresa import Empresa
from app.models.marca_pm import MarcaPM
from app.models.marca_sub_pm import MarcaSubPM
from app.models.notificacion import EstadoNotificacion, Notificacion
from app.models.pedido_compra import PedidoCompra
from app.models.permiso import Permiso, RolPermisoBase, UsuarioPermisoOverride
from app.models.proveedor import OrigenProveedor, Proveedor
from app.models.rol import Rol
from app.models.usuario import AuthProvider, RolUsuario, Usuario
from app.services import compras_alertas_service, pedidos_service


MARK = datetime(2026, 3, 10, 10, 0, tzinfo=timezone.utc)
SNOOZE_AT = datetime(2026, 3, 10, 10, 20, tzinfo=timezone.utc)
BEFORE_REOPEN = datetime(2026, 3, 10, 10, 59, tzinfo=timezone.utc)
AT_REOPEN = datetime(2026, 3, 10, 11, 0, tzinfo=timezone.utc)

PERMISO_DEPOSITO = "deposito.recibir_mercaderia"
PERMISO_FACTURA = "administracion.ver_alertas_factura"


@pytest.fixture
def empresa(db) -> Empresa:
    emp = Empresa(id=1, nombre="Empresa Alertas", activo=True, orden=0)
    db.add(emp)
    db.flush()
    return emp


@pytest.fixture
def proveedor(db) -> Proveedor:
    prov = Proveedor(
        id=1,
        nombre="Acme",
        activo=True,
        origen=OrigenProveedor.ERP.value,
        supp_id=200,
    )
    db.add(prov)
    db.flush()
    return prov


def _rol(db, codigo: str, *, orden: int) -> Rol:
    existing = db.query(Rol).filter(Rol.codigo == codigo).first()
    if existing:
        return existing
    rol = Rol(codigo=codigo, nombre=codigo.title(), es_sistema=True, orden=orden, activo=True)
    db.add(rol)
    db.flush()
    return rol


def _usuario(
    db,
    *,
    username: str,
    rol: Rol,
    rol_enum: RolUsuario,
    activo: bool = True,
) -> Usuario:
    user = Usuario(
        username=username,
        email=f"{username}@example.com",
        nombre=username.replace("_", " ").title(),
        password_hash=get_password_hash("TestPass123!"),
        rol=rol_enum,
        rol_id=rol.id,
        auth_provider=AuthProvider.LOCAL,
        activo=activo,
    )
    db.add(user)
    db.flush()
    return user


@pytest.fixture
def roles_pipeline(db) -> dict[str, Rol]:
    return {
        "ADMIN": _rol(db, "ADMIN", orden=1),
        "GERENTE": _rol(db, "GERENTE", orden=2),
        "SUPERADMIN": _rol(db, "SUPERADMIN", orden=0),
        "VENTAS": _rol(db, "VENTAS", orden=10),
    }


@pytest.fixture
def permiso_factura(db) -> Permiso:
    permiso = Permiso(
        codigo=PERMISO_FACTURA,
        nombre="Ver alertas de factura cargada",
        categoria="administracion_sector",
        orden=176,
        es_critico=False,
    )
    db.add(permiso)
    db.flush()
    return permiso


@pytest.fixture
def fanout_users(db, roles_pipeline, permiso_factura) -> dict[str, Usuario]:
    titular = _usuario(db, username="titular_t", rol=roles_pipeline["VENTAS"], rol_enum=RolUsuario.VENTAS)
    sub_pm = _usuario(db, username="subpm_s", rol=roles_pipeline["VENTAS"], rol_enum=RolUsuario.VENTAS)
    holder_h1 = _usuario(db, username="holder_h1", rol=roles_pipeline["VENTAS"], rol_enum=RolUsuario.VENTAS)
    holder_h2 = _usuario(db, username="holder_h2", rol=roles_pipeline["VENTAS"], rol_enum=RolUsuario.VENTAS)
    admin = _usuario(db, username="admin_a", rol=roles_pipeline["ADMIN"], rol_enum=RolUsuario.ADMIN)
    gerente = _usuario(db, username="gerente_g", rol=roles_pipeline["GERENTE"], rol_enum=RolUsuario.GERENTE)
    superadmin = _usuario(db, username="super_sa", rol=roles_pipeline["SUPERADMIN"], rol_enum=RolUsuario.SUPERADMIN)
    outsider = _usuario(db, username="outsider_o", rol=roles_pipeline["VENTAS"], rol_enum=RolUsuario.VENTAS)
    inactive = _usuario(
        db, username="inactive_titular", rol=roles_pipeline["VENTAS"], rol_enum=RolUsuario.VENTAS, activo=False
    )
    db.add(MarcaPM(marca="AcmeBrand", categoria="General", usuario_id=titular.id))
    db.add(MarcaPM(marca="OldBrand", categoria="General", usuario_id=inactive.id))
    db.add(MarcaSubPM(marca="AcmeBrand", categoria="General", usuario_id=sub_pm.id, creado_por=titular.id))
    db.add(UsuarioPermisoOverride(usuario_id=holder_h1.id, permiso_id=permiso_factura.id, concedido=True))
    db.add(UsuarioPermisoOverride(usuario_id=holder_h2.id, permiso_id=permiso_factura.id, concedido=True))
    db.flush()
    return {
        "titular": titular,
        "sub_pm": sub_pm,
        "holder_h1": holder_h1,
        "holder_h2": holder_h2,
        "admin": admin,
        "gerente": gerente,
        "superadmin": superadmin,
        "outsider": outsider,
        "inactive": inactive,
    }


def _pedido(
    db,
    empresa: Empresa,
    proveedor: Proveedor,
    user: Usuario,
    *,
    numero: str = "P-01-2026-00012",
    responsable_id: int | None = None,
    pedidos_documento: str | None = "DOC-ERP-NO-USAR",
) -> PedidoCompra:
    pedido = PedidoCompra(
        numero=numero,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto=Decimal("1000.00"),
        estado="recibido",
        creado_por_id=user.id,
        responsable_id=responsable_id or user.id,
        pedidos_documento=pedidos_documento,
    )
    db.add(pedido)
    db.flush()
    return pedido


def _auth_headers(user: Usuario) -> dict[str, str]:
    from app.core.security import create_access_token

    return {"Authorization": f"Bearer {create_access_token(data={'sub': user.username})}"}


def _notif_ids(db, *, tipo: str) -> set[int]:
    return {n.user_id for n in db.query(Notificacion).filter(Notificacion.tipo == tipo).all()}


class TestCopyFactura:
    def test_copy_contains_p_proveedor_factura_not_pedidos_documento(
        self, db, empresa, proveedor, fanout_users
    ) -> None:
        pedido = _pedido(db, empresa, proveedor, fanout_users["titular"], pedidos_documento="DOC-ERP-NO-USAR")
        row = pedidos_service.agregar_factura_documento(
            db, pedido_id=pedido.id, numero="FA-99", user_id=fanout_users["titular"].id
        )
        db.flush()
        notifs = db.query(Notificacion).filter(Notificacion.tipo == "compras.factura_cargada").all()
        assert notifs
        for notif in notifs:
            assert "P-01-2026-00012" in notif.mensaje
            assert "Acme" in notif.mensaje
            assert "FA-99" in notif.mensaje
            assert "pedidos_documento" not in notif.mensaje
            assert "DOC-ERP-NO-USAR" not in notif.mensaje
        assert row.numero == "FA-99"


class TestFanoutFactura:
    def test_fanout_holders_only_and_admin_without_code_excluded(self, db, empresa, proveedor, fanout_users) -> None:
        pedido = _pedido(db, empresa, proveedor, fanout_users["titular"])
        pedidos_service.agregar_factura_documento(
            db, pedido_id=pedido.id, numero="FA-99", user_id=fanout_users["titular"].id
        )
        db.flush()
        ids = _notif_ids(db, tipo="compras.factura_cargada")
        assert fanout_users["holder_h1"].id in ids
        assert fanout_users["holder_h2"].id in ids
        assert fanout_users["superadmin"].id in ids
        assert fanout_users["titular"].id not in ids
        assert fanout_users["sub_pm"].id not in ids
        assert fanout_users["admin"].id not in ids
        assert fanout_users["gerente"].id not in ids
        assert fanout_users["outsider"].id not in ids
        assert fanout_users["inactive"].id not in ids
        assert ids == {
            fanout_users["holder_h1"].id,
            fanout_users["holder_h2"].id,
            fanout_users["superadmin"].id,
        }

    def test_superadmin_matches_via_resolver(self, db, empresa, proveedor, fanout_users) -> None:
        recipients = compras_alertas_service.destinatarios_factura(db)
        ids = {u.id for u in recipients}
        assert fanout_users["superadmin"].id in ids
        assert fanout_users["admin"].id not in ids

    def test_empty_numero_creates_no_alert(self, db, empresa, proveedor, fanout_users) -> None:
        pedido = _pedido(db, empresa, proveedor, fanout_users["titular"])
        with pytest.raises(HTTPException) as exc_info:
            pedidos_service.agregar_factura_documento(
                db, pedido_id=pedido.id, numero="   ", user_id=fanout_users["titular"].id
            )
        assert exc_info.value.status_code == 422
        assert db.query(Notificacion).count() == 0


class TestPerUserOkAndUndo:
    def test_ok_clears_only_that_user(self, db, empresa, proveedor, fanout_users) -> None:
        pedido = _pedido(db, empresa, proveedor, fanout_users["titular"])
        pedidos_service.agregar_factura_documento(
            db, pedido_id=pedido.id, numero="FA-99", user_id=fanout_users["titular"].id
        )
        db.flush()
        t_notif = (
            db.query(Notificacion)
            .filter(
                Notificacion.user_id == fanout_users["holder_h1"].id,
                Notificacion.tipo == "compras.factura_cargada",
            )
            .one()
        )
        s_notif = (
            db.query(Notificacion)
            .filter(
                Notificacion.user_id == fanout_users["holder_h2"].id,
                Notificacion.tipo == "compras.factura_cargada",
            )
            .one()
        )
        compras_alertas_service.marcar_ok(db, t_notif)
        db.flush()
        db.refresh(t_notif)
        db.refresh(s_notif)
        assert t_notif.estado == EstadoNotificacion.DESCARTADA
        assert s_notif.estado == EstadoNotificacion.PENDIENTE

    def test_undo_retracts_factura_notifs(self, db, empresa, proveedor, fanout_users) -> None:
        pedido = _pedido(db, empresa, proveedor, fanout_users["titular"])
        row = pedidos_service.agregar_factura_documento(
            db, pedido_id=pedido.id, numero="FA-99", user_id=fanout_users["titular"].id
        )
        db.flush()
        assert db.query(Notificacion).filter(Notificacion.tipo == "compras.factura_cargada").count() == 3
        pedidos_service.deshacer_factura_documento(db, pedido_id=pedido.id, row_id=row.id)
        db.flush()
        leftovers = db.query(Notificacion).filter(Notificacion.tipo == "compras.factura_cargada").all()
        assert leftovers
        assert all(n.estado == EstadoNotificacion.DESCARTADA for n in leftovers)


class TestFaltantes:
    def test_responsable_notified_with_free_text(self, db, empresa, proveedor, fanout_users) -> None:
        responsable = fanout_users["titular"]
        pedido = _pedido(db, empresa, proveedor, fanout_users["admin"], responsable_id=responsable.id)
        creadas = compras_alertas_service.notificar_faltantes(db, pedido=pedido, texto="Faltan 2 cajas", ahora=MARK)
        db.flush()
        assert len(creadas) == 1
        notif = creadas[0]
        assert notif.user_id == responsable.id
        assert notif.tipo == "compras.faltantes"
        assert "Faltan 2 cajas" in notif.mensaje
        assert "P-01-2026-00012" in notif.mensaje
        assert "focus=observaciones" in (notif.mensaje + (notif.codigo_producto or ""))
        assert notif.item_id == pedido.id

    def test_empty_texto_422_no_alert(self, db, empresa, proveedor, fanout_users) -> None:
        pedido = _pedido(db, empresa, proveedor, fanout_users["titular"])
        with pytest.raises(HTTPException) as exc_info:
            compras_alertas_service.notificar_faltantes(db, pedido=pedido, texto="   ")
        assert exc_info.value.status_code == 422
        assert db.query(Notificacion).filter(Notificacion.tipo == "compras.faltantes").count() == 0

    def test_factura_permiso_does_not_change_faltantes_recipients(self, db, empresa, proveedor, fanout_users) -> None:
        responsable = fanout_users["titular"]
        holder = fanout_users["holder_h1"]
        pedido = _pedido(db, empresa, proveedor, fanout_users["admin"], responsable_id=responsable.id)
        creadas = compras_alertas_service.notificar_faltantes(db, pedido=pedido, texto="Faltan 2 cajas", ahora=MARK)
        db.flush()
        ids = {n.user_id for n in creadas}
        assert ids == {responsable.id}
        assert holder.id not in ids


class TestSnoozeClock:
    def test_hide_until_mark_plus_one_hour(self, db, empresa, proveedor, fanout_users, client) -> None:
        responsable = fanout_users["titular"]
        pedido = _pedido(db, empresa, proveedor, responsable, responsable_id=responsable.id)
        [notif] = compras_alertas_service.notificar_faltantes(db, pedido=pedido, texto="Faltan 2 cajas", ahora=MARK)
        db.flush()
        compras_alertas_service.snooze_faltantes(db, notif, ahora=SNOOZE_AT)
        db.flush()
        db.refresh(notif)
        assert notif.estado == EstadoNotificacion.REVISADA
        assert compras_alertas_service.SNOOZE_MARKER in (notif.notas_revision or "")
        assert compras_alertas_service.esta_oculta_por_snooze(notif, ahora=SNOOZE_AT) is True
        assert compras_alertas_service.esta_oculta_por_snooze(notif, ahora=BEFORE_REOPEN) is True
        assert compras_alertas_service.esta_oculta_por_snooze(notif, ahora=AT_REOPEN) is False

        with patch("app.api.endpoints.notificaciones._ahora_listado", return_value=SNOOZE_AT):
            hidden = client.get("/api/notificaciones", headers=_auth_headers(responsable))
        assert hidden.status_code == 200
        assert all(item["id"] != notif.id for item in hidden.json())

        with patch("app.api.endpoints.notificaciones._ahora_listado", return_value=AT_REOPEN):
            shown = client.get("/api/notificaciones", headers=_auth_headers(responsable))
        assert shown.status_code == 200
        assert any(item["id"] == notif.id for item in shown.json())


class TestResolucionG31:
    def test_deposito_receivers_only(self, db, empresa, proveedor, fanout_users, roles_pipeline) -> None:
        permiso = Permiso(
            codigo=PERMISO_DEPOSITO,
            nombre="Recibir mercadería",
            categoria="deposito",
            orden=1,
        )
        db.add(permiso)
        db.flush()
        rol_dep = Rol(codigo="DEPOSITO", nombre="Depósito", es_sistema=False, orden=20, activo=True)
        db.add(rol_dep)
        db.flush()
        db.add(RolPermisoBase(rol_id=rol_dep.id, permiso_id=permiso.id))
        d1 = _usuario(db, username="dep_d1", rol=rol_dep, rol_enum=RolUsuario.VENTAS)
        d2 = _usuario(db, username="dep_d2", rol=rol_dep, rol_enum=RolUsuario.VENTAS)
        d3 = _usuario(db, username="dep_d3", rol=roles_pipeline["VENTAS"], rol_enum=RolUsuario.VENTAS)
        db.flush()

        pedido = _pedido(db, empresa, proveedor, fanout_users["titular"])
        creadas = compras_alertas_service.notificar_faltantes_resuelto(db, pedido=pedido)
        db.flush()
        ids = {n.user_id for n in creadas}
        assert d1.id in ids
        assert d2.id in ids
        assert d3.id not in ids
        assert all(n.tipo == "compras.faltantes_resuelto" for n in creadas)
        assert all("P-01-2026-00012" in n.mensaje for n in creadas)

    def test_no_email_or_slack_on_factura(self, db, empresa, proveedor, fanout_users) -> None:
        pedido = _pedido(db, empresa, proveedor, fanout_users["titular"])
        with (
            patch("smtplib.SMTP") as smtp,
            patch("smtplib.SMTP_SSL") as smtp_ssl,
        ):
            pedidos_service.agregar_factura_documento(
                db, pedido_id=pedido.id, numero="FA-99", user_id=fanout_users["titular"].id
            )
            db.flush()
            smtp.assert_not_called()
            smtp_ssl.assert_not_called()
        assert db.query(Notificacion).filter(Notificacion.tipo == "compras.factura_cargada").count() == 3


class TestOkSnoozeRoutes:
    def test_patch_ok_and_snooze(self, db, empresa, proveedor, fanout_users, client) -> None:
        responsable = fanout_users["titular"]
        pedido = _pedido(db, empresa, proveedor, responsable, responsable_id=responsable.id)
        [notif] = compras_alertas_service.notificar_faltantes(db, pedido=pedido, texto="Faltan 2 cajas", ahora=MARK)
        db.commit()
        headers = _auth_headers(responsable)

        snooze = client.patch(f"/api/notificaciones/{notif.id}/snooze", headers=headers)
        assert snooze.status_code == 200
        db.refresh(notif)
        assert notif.estado == EstadoNotificacion.REVISADA
        assert compras_alertas_service.SNOOZE_MARKER in (notif.notas_revision or "")

        ok = client.patch(f"/api/notificaciones/{notif.id}/ok", headers=headers)
        assert ok.status_code == 200
        db.refresh(notif)
        assert notif.estado == EstadoNotificacion.DESCARTADA
