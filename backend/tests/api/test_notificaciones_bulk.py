"""
Bulk notification actions in ONE request, and no transaction held across an await.

Prod incident 2026-11-18: the owner ignored a group of 1411 notifications and the
frontend sent 1411 concurrent PATCH /marcar-leida requests. Requests that kept a
transaction open while suspended at an await stayed "idle in transaction", the
event loop blocked waiting on the exhausted pool, and pricing-api stopped
answering until a restart.
"""

from __future__ import annotations

import asyncio

from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import HTTPException

from app.api.endpoints import notificaciones as notificaciones_endpoint
from app.models.notificacion import EstadoNotificacion, Notificacion, SeveridadNotificacion
from app.models.notificacion_ignorada import NotificacionIgnorada
from app.models.usuario import Usuario
from app.services import compras_alertas_service

BASE = datetime(2026, 11, 18, 9, 0, tzinfo=UTC)


def _notif(db, user: Usuario, *, tipo: str = "ml_bot.llm_failover", **kwargs: Any) -> Notificacion:
    notif = Notificacion(
        user_id=user.id,
        tipo=tipo,
        mensaje=kwargs.pop("mensaje", tipo),
        fecha_creacion=kwargs.pop("fecha_creacion", BASE),
        severidad=kwargs.pop("severidad", SeveridadNotificacion.INFO),
        **kwargs,
    )
    db.add(notif)
    db.flush()
    return notif


@pytest.fixture()
def otro_usuario(db, rol_ventas) -> Usuario:
    user = Usuario(
        username="otro",
        email="otro@example.com",
        nombre="Otro",
        password_hash="x",
        activo=True,
        rol_id=rol_ventas.id,
    )
    db.add(user)
    db.flush()
    return user


@pytest.fixture()
def sse_calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []

    async def _fake(channel: str, data: dict | None = None) -> None:
        calls.append(channel)

    monkeypatch.setattr(notificaciones_endpoint, "sse_publish", _fake)
    return calls


def _bulk(client, headers: dict, ids: list[int], accion: str):
    return client.post("/api/notificaciones/bulk", json={"ids": ids, "accion": accion}, headers=headers)


class TestBulkEndpoint:
    def test_marks_read_only_the_callers_notifications(
        self, client, auth_headers, db, active_user, otro_usuario, sse_calls
    ) -> None:
        mias = [_notif(db, active_user) for _ in range(30)]
        ajena = _notif(db, otro_usuario)

        r = _bulk(client, auth_headers, [n.id for n in mias] + [ajena.id], "leida")

        assert r.status_code == 200
        assert r.json() == {"count": 30}
        db.expire_all()
        assert all(n.leida and n.fecha_lectura is not None for n in mias)
        assert ajena.leida is False
        assert sse_calls == ["notificaciones:updated"]

    def test_read_count_only_counts_the_unread_ones(self, client, auth_headers, db, active_user, sse_calls) -> None:
        leida = _notif(db, active_user, leida=True, fecha_lectura=BASE)
        nueva = _notif(db, active_user)

        r = _bulk(client, auth_headers, [leida.id, nueva.id], "leida")

        assert r.json() == {"count": 1}
        db.expire_all()
        assert leida.fecha_lectura == BASE.replace(tzinfo=None)

    def test_unread(self, client, auth_headers, db, active_user, sse_calls) -> None:
        leida = _notif(db, active_user, leida=True, fecha_lectura=BASE)

        r = _bulk(client, auth_headers, [leida.id], "no_leida")

        assert r.json() == {"count": 1}
        db.expire_all()
        assert leida.leida is False and leida.fecha_lectura is None

    def test_discard_sets_state_and_creates_one_rule_per_product_markup(
        self, client, auth_headers, db, active_user, otro_usuario, sse_calls
    ) -> None:
        mismas = [_notif(db, active_user, tipo="markup_bajo", item_id=77, markup_real=-4.5) for _ in range(3)]
        sin_producto = _notif(db, active_user)
        ajena = _notif(db, otro_usuario, tipo="markup_bajo", item_id=88, markup_real=1)
        ids = [n.id for n in mismas] + [sin_producto.id, ajena.id]

        r = _bulk(client, auth_headers, ids, "descartada")

        assert r.json() == {"count": 4}
        db.expire_all()
        assert all(n.estado == EstadoNotificacion.DESCARTADA and n.fecha_descarte for n in mismas + [sin_producto])
        assert ajena.estado != EstadoNotificacion.DESCARTADA
        reglas = db.query(NotificacionIgnorada).all()
        assert [(r.user_id, r.item_id, r.tipo) for r in reglas] == [(active_user.id, 77, "markup_bajo")]

    def test_discard_refuses_open_faltantes_and_changes_nothing(
        self, client, auth_headers, db, active_user, sse_calls, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(compras_alertas_service, "pedido_admite_alerta_faltantes", lambda pedido: True)
        faltantes = _notif(db, active_user, tipo="compras.faltantes", item_id=5)
        otra = _notif(db, active_user)

        r = _bulk(client, auth_headers, [faltantes.id, otra.id], "descartada")

        assert r.status_code == 409
        db.expire_all()
        assert otra.estado != EstadoNotificacion.DESCARTADA
        assert sse_calls == []

    def test_review_keeps_the_first_review_date(self, client, auth_headers, db, active_user, sse_calls) -> None:
        revisada = _notif(db, active_user, estado=EstadoNotificacion.REVISADA, fecha_revision=BASE)
        nueva = _notif(db, active_user)

        r = _bulk(client, auth_headers, [revisada.id, nueva.id], "revisada")

        assert r.json() == {"count": 2}
        db.expire_all()
        assert revisada.fecha_revision == BASE.replace(tzinfo=None)
        assert nueva.estado == EstadoNotificacion.REVISADA and nueva.fecha_revision is not None

    def test_resolve(self, client, auth_headers, db, active_user, sse_calls) -> None:
        notif = _notif(db, active_user)

        r = _bulk(client, auth_headers, [notif.id], "resuelta")

        assert r.json() == {"count": 1}
        db.expire_all()
        assert notif.estado == EstadoNotificacion.RESUELTA and notif.fecha_resolucion is not None

    def test_delete_only_the_callers(self, client, auth_headers, db, active_user, otro_usuario, sse_calls) -> None:
        mia = _notif(db, active_user)
        ajena = _notif(db, otro_usuario)
        ids = [mia.id, ajena.id]

        r = _bulk(client, auth_headers, ids, "eliminar")

        assert r.json() == {"count": 1}
        db.expire_all()
        assert [n.id for n in db.query(Notificacion).filter(Notificacion.id.in_(ids))] == [ajena.id]

    def test_nothing_changed_publishes_nothing(self, client, auth_headers, db, otro_usuario, sse_calls) -> None:
        ajena = _notif(db, otro_usuario)

        r = _bulk(client, auth_headers, [ajena.id], "leida")

        assert r.json() == {"count": 0}
        assert sse_calls == []

    @pytest.mark.parametrize("body", [{"ids": [], "accion": "leida"}, {"ids": [1], "accion": "borrar"}])
    def test_invalid_body_is_422(self, client, auth_headers, body: dict) -> None:
        r = client.post("/api/notificaciones/bulk", json=body, headers=auth_headers)

        assert r.status_code == 422

    def test_requires_auth(self, client) -> None:
        r = client.post("/api/notificaciones/bulk", json={"ids": [1], "accion": "leida"})

        assert r.status_code in (401, 403)


class TestNoTransactionHeldAcrossAwait:
    """Every await (sse_publish, or FastAPI's own after the endpoint returns)
    must find the session without an open transaction."""

    def test_marking_an_already_read_notification_ends_the_transaction(self, db, active_user) -> None:
        notif = _notif(db, active_user, leida=True, fecha_lectura=BASE)
        db.commit()

        asyncio.run(notificaciones_endpoint.marcar_notificacion_leida(notif.id, db, active_user))

        assert not db.in_transaction()

    def test_marking_a_missing_notification_ends_the_transaction(self, db, active_user) -> None:
        with pytest.raises(HTTPException):
            asyncio.run(notificaciones_endpoint.marcar_notificacion_leida(999_999_999, db, active_user))

        assert not db.in_transaction()

    def test_state_change_publishes_without_an_open_transaction(
        self, db, active_user, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        notif = _notif(db, active_user)
        db.commit()
        abiertas: list[bool] = []

        async def _fake(channel: str, data: dict | None = None) -> None:
            abiertas.append(db.in_transaction())

        monkeypatch.setattr(notificaciones_endpoint, "sse_publish", _fake)

        asyncio.run(notificaciones_endpoint.revisar_notificacion(notif.id, None, db, active_user))

        assert abiertas == [False]
        assert not db.in_transaction()

    def test_bulk_publishes_without_an_open_transaction(self, db, active_user, monkeypatch: pytest.MonkeyPatch) -> None:
        notif = _notif(db, active_user, tipo="markup_bajo", item_id=77, markup_real=-4.5)
        db.commit()
        abiertas: list[bool] = []

        async def _fake(channel: str, data: dict | None = None) -> None:
            abiertas.append(db.in_transaction())

        monkeypatch.setattr(notificaciones_endpoint, "sse_publish", _fake)
        body = notificaciones_endpoint.AccionBulkRequest(ids=[notif.id], accion="descartada")

        asyncio.run(notificaciones_endpoint.accion_bulk_notificaciones(body, db, active_user))

        assert abiertas == [False]
        assert not db.in_transaction()

    def test_refused_faltantes_discard_ends_the_transaction(
        self, db, active_user, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(compras_alertas_service, "pedido_admite_alerta_faltantes", lambda pedido: True)
        notif = _notif(db, active_user, tipo="compras.faltantes", item_id=5)
        db.commit()

        with pytest.raises(HTTPException):
            asyncio.run(notificaciones_endpoint.descartar_notificacion(notif.id, None, True, db, active_user))

        assert not db.in_transaction()
