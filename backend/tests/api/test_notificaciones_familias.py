"""
Notification families (Compras / Markup / Técnicas / Otras), server-side paging,
and the product lookup that must not apply to compras notifications.

Owner report (2026-11-16): the SUPERADMIN could not find a compras.factura_cargada
alert because the 100 newest notifications were all markup_bajo / ml_bot.llm_failover,
and the grouped view showed an unrelated product looked up by the pedido id.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.api.endpoints import notificaciones as notificaciones_endpoint
from app.models.notificacion import EstadoNotificacion, Notificacion, SeveridadNotificacion
from app.models.producto import ProductoERP
from app.models.usuario import Usuario
from app.services.compras_alertas_service import SNOOZE_MARKER

BASE = datetime(2026, 11, 13, 9, 0, tzinfo=timezone.utc)


def _notif(db, user: Usuario, *, tipo: str, minutos: int, **kwargs: object) -> Notificacion:
    notif = Notificacion(
        user_id=user.id,
        tipo=tipo,
        mensaje=kwargs.pop("mensaje", f"{tipo} #{minutos}"),
        fecha_creacion=BASE + timedelta(minutes=minutos),
        severidad=kwargs.pop("severidad", SeveridadNotificacion.INFO),
        **kwargs,
    )
    db.add(notif)
    db.flush()
    return notif


@pytest.fixture()
def buzon_tapado(db, active_user: Usuario) -> Notificacion:
    """One older compras.factura_cargada buried under 150 newer markup_bajo alerts."""
    factura = _notif(
        db,
        active_user,
        tipo="compras.factura_cargada",
        minutos=0,
        item_id=321,
        mensaje="Factura cargada en ERP: P-321 · Proveedor SA · 00002-00006138",
    )
    for i in range(150):
        _notif(
            db,
            active_user,
            tipo="markup_bajo",
            minutos=60 + i,
            item_id=9000 + i,
            severidad=SeveridadNotificacion.WARNING,
        )
    _notif(db, active_user, tipo="ml_bot.llm_failover", minutos=500)
    _notif(db, active_user, tipo="item_sin_mla", minutos=501, item_id=77)
    return factura


class TestFamiliaFilter:
    def test_compras_family_returns_the_buried_invoice(self, client, auth_headers, buzon_tapado) -> None:
        r = client.get("/api/notificaciones", params={"familia": "compras"}, headers=auth_headers)

        assert r.status_code == 200
        assert [n["id"] for n in r.json()] == [buzon_tapado.id]

    def test_without_family_the_first_page_does_not_reach_the_invoice(self, client, auth_headers, buzon_tapado) -> None:
        r = client.get("/api/notificaciones", params={"limit": 100}, headers=auth_headers)

        assert r.status_code == 200
        assert buzon_tapado.id not in [n["id"] for n in r.json()]

    def test_markup_tecnicas_and_otras_families(self, client, auth_headers, buzon_tapado) -> None:
        def tipos(familia: str) -> set[str]:
            r = client.get(
                "/api/notificaciones",
                params={"familia": familia, "limit": 500},
                headers=auth_headers,
            )
            assert r.status_code == 200
            return {n["tipo"] for n in r.json()}

        assert tipos("markup") == {"markup_bajo"}
        assert tipos("tecnicas") == {"ml_bot.llm_failover"}
        assert tipos("otras") == {"item_sin_mla"}

    def test_grouped_view_filters_by_family(self, client, auth_headers, buzon_tapado) -> None:
        r = client.get("/api/notificaciones/agrupadas", params={"familia": "compras"}, headers=auth_headers)

        assert r.status_code == 200
        assert [g["tipo"] for g in r.json()] == ["compras.factura_cargada"]

    def test_unknown_family_is_rejected(self, client, auth_headers, buzon_tapado) -> None:
        r = client.get("/api/notificaciones", params={"familia": "inexistente"}, headers=auth_headers)

        assert r.status_code == 422

    def test_stats_counts_unread_per_family(self, client, auth_headers, buzon_tapado) -> None:
        r = client.get("/api/notificaciones/stats", headers=auth_headers)

        assert r.status_code == 200
        body = r.json()
        assert body["no_leidas_por_familia"] == {"compras": 1, "markup": 150, "tecnicas": 1, "otras": 1}
        assert body["no_leidas"] == 153
        assert body["por_tipo"]["markup_bajo"] == 150

    def test_mark_all_read_by_family_only_touches_that_family(self, client, db, auth_headers, buzon_tapado) -> None:
        r = client.post("/api/notificaciones/marcar-todas-leidas", params={"familia": "compras"}, headers=auth_headers)

        assert r.status_code == 200
        db.expire_all()
        assert db.get(Notificacion, buzon_tapado.id).leida is True
        assert db.query(Notificacion).filter(Notificacion.leida == False).count() == 152  # noqa: E712

    def test_mark_all_read_without_family_still_marks_everything(self, client, db, auth_headers, buzon_tapado) -> None:
        r = client.post("/api/notificaciones/marcar-todas-leidas", headers=auth_headers)

        assert r.status_code == 200
        db.expire_all()
        assert db.query(Notificacion).filter(Notificacion.leida == False).count() == 0  # noqa: E712


class TestServerPaging:
    def test_offset_reaches_rows_past_the_first_hundred(self, client, auth_headers, buzon_tapado) -> None:
        r = client.get(
            "/api/notificaciones",
            params={"limit": 20, "offset": 140, "orden": "fecha_desc"},
            headers=auth_headers,
        )

        assert r.status_code == 200
        ids = [n["id"] for n in r.json()]
        assert len(ids) == 13
        assert ids[-1] == buzon_tapado.id

    def test_total_matches_the_same_filters(self, client, auth_headers, buzon_tapado) -> None:
        def total(**params: object) -> int:
            r = client.get("/api/notificaciones/total", params=params, headers=auth_headers)
            assert r.status_code == 200
            return r.json()["total"]

        assert total() == 153
        assert total(familia="compras") == 1
        assert total(familia="markup", severidad="WARNING") == 150
        assert total(solo_no_leidas=True, familia="tecnicas") == 1

    def test_default_order_is_still_severity_first(self, client, auth_headers, buzon_tapado) -> None:
        r = client.get("/api/notificaciones", params={"limit": 1}, headers=auth_headers)

        assert r.status_code == 200
        assert r.json()[0]["severidad"] == "WARNING"

    def test_fecha_asc_puts_the_oldest_first(self, client, auth_headers, buzon_tapado) -> None:
        r = client.get("/api/notificaciones", params={"limit": 1, "orden": "fecha_asc"}, headers=auth_headers)

        assert r.status_code == 200
        assert r.json()[0]["id"] == buzon_tapado.id

    def test_pm_filter_is_server_side(self, client, db, auth_headers, active_user, buzon_tapado) -> None:
        objetivo = _notif(db, active_user, tipo="markup_bajo", minutos=-10, pm="Gabriel")

        r = client.get("/api/notificaciones", params={"pm": "Gabriel"}, headers=auth_headers)

        assert r.status_code == 200
        assert [n["id"] for n in r.json()] == [objetivo.id]


class TestHiddenFaltantesInPaging:
    """Snoozed or obsolete compras.faltantes are hidden before paging, so the
    total and every page agree (no short or empty pages)."""

    @pytest.fixture()
    def con_faltantes_ocultas(self, db, active_user: Usuario) -> list[Notificacion]:
        visibles = [_notif(db, active_user, tipo="markup_bajo", minutos=i) for i in range(3)]
        # Obsolete: its pedido does not exist any more.
        _notif(db, active_user, tipo="compras.faltantes", minutos=10, item_id=999999)
        # Snoozed for the next hour.
        _notif(
            db,
            active_user,
            tipo="compras.faltantes",
            minutos=11,
            item_id=999998,
            estado=EstadoNotificacion.REVISADA,
            notas_revision=SNOOZE_MARKER,
        )
        return visibles

    def test_total_skips_hidden_faltantes(self, client, auth_headers, con_faltantes_ocultas, monkeypatch) -> None:
        monkeypatch.setattr(notificaciones_endpoint, "_ahora_listado", lambda: BASE + timedelta(minutes=20))

        r = client.get("/api/notificaciones/total", headers=auth_headers)

        assert r.status_code == 200
        assert r.json()["total"] == 3

    def test_pages_are_full_when_faltantes_are_hidden(
        self, client, auth_headers, con_faltantes_ocultas, monkeypatch
    ) -> None:
        monkeypatch.setattr(notificaciones_endpoint, "_ahora_listado", lambda: BASE + timedelta(minutes=20))

        r = client.get(
            "/api/notificaciones",
            params={"limit": 2, "offset": 0, "orden": "fecha_desc"},
            headers=auth_headers,
        )

        assert r.status_code == 200
        assert [n["id"] for n in r.json()] == [con_faltantes_ocultas[2].id, con_faltantes_ocultas[1].id]


class TestPmOptions:
    def test_total_lists_every_pm_of_the_filter_not_just_one_page(
        self, client, db, auth_headers, active_user, buzon_tapado
    ) -> None:
        _notif(db, active_user, tipo="markup_bajo", minutos=-20, pm="Gabriel")
        _notif(db, active_user, tipo="markup_bajo", minutos=-21, pm="Ana")
        _notif(db, active_user, tipo="compras.faltantes_resuelto", minutos=-22, pm="Compras PM")

        r = client.get(
            "/api/notificaciones/total",
            params={"familia": "markup", "pm": "Gabriel"},
            headers=auth_headers,
        )

        assert r.status_code == 200
        assert r.json() == {"total": 1, "pms": ["Ana", "Gabriel"]}


class TestComprasNoProductLookup:
    def test_compras_group_never_shows_the_product_with_the_pedido_id(
        self, client, db, auth_headers, buzon_tapado
    ) -> None:
        db.add(ProductoERP(item_id=321, codigo="AK-OCTANE", descripcion="SILLA AK RACING OCTANE BLACK"))
        db.flush()

        r = client.get("/api/notificaciones/agrupadas", params={"familia": "compras"}, headers=auth_headers)

        assert r.status_code == 200
        grupo = r.json()[0]
        assert grupo["codigo_producto"] is None
        assert grupo["descripcion_producto"] is None
        assert "00002-00006138" in grupo["notificacion_reciente"]["mensaje"]

    def test_markup_group_still_fills_the_product(self, client, db, auth_headers, buzon_tapado) -> None:
        db.add(ProductoERP(item_id=9000, codigo="COD-9000", descripcion="Producto 9000"))
        db.flush()

        r = client.get("/api/notificaciones/agrupadas", params={"familia": "markup"}, headers=auth_headers)

        assert r.status_code == 200
        grupo = next(g for g in r.json() if g["item_id"] == 9000)
        assert grupo["codigo_producto"] == "COD-9000"
        assert grupo["descripcion_producto"] == "Producto 9000"
