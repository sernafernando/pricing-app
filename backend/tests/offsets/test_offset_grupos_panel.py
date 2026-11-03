"""The Sell in / Sell out "Grupos" panel over the offsets API groups (sell-in-sell-out T30).

- `PATCH /api/offset-grupos/{id}` renames / describes a group (same permission as create);
- `GET /api/offset-grupos-alcance` tells, per group, how many products it reaches (the sell-out
  campaign rule, `alcance.filtro_alcanza`) and which campaigns use it, in a constant number of queries;
- `DELETE /api/offset-grupos/{id}` with an ACTIVE campaign names the campaigns; a voided campaign or a
  legacy offset keeps the refusal it already had.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from app.models.offset_ganancia import OffsetGanancia
from app.models.offset_grupo import OffsetGrupo
from app.models.offset_grupo_consumo import OffsetGrupoConsumo, OffsetGrupoResumen
from app.models.offset_grupo_filtro import OffsetGrupoFiltro
from app.models.producto import ProductoERP
from app.models.sell_out import SellOutCampana, SellOutCampanaGrupo

PERMISO = "config.editar_constantes"


@pytest.fixture()
def editor(rol_admin, admin_auth_headers, grant_permiso):
    grant_permiso(rol_admin, PERMISO)
    return admin_auth_headers


@pytest.fixture()
def catalogo(db):
    for item_id, marca, categoria, sub in [
        (2964, "TP-LINK", "Routers", 11),
        (2270, "TP-LINK", "Switches", 12),
        (950, "MERCUSYS", "Routers", 11),
    ]:
        db.add(
            ProductoERP(
                item_id=item_id,
                codigo=f"C{item_id}",
                descripcion=f"Producto {item_id}",
                marca=marca,
                categoria=categoria,
                subcategoria_id=sub,
            )
        )
    db.flush()


def _grupo(db, nombre: str, filtros=(), descripcion=None) -> int:
    grupo = OffsetGrupo(nombre=nombre, descripcion=descripcion)
    db.add(grupo)
    db.flush()
    for filtro in filtros:
        db.add(OffsetGrupoFiltro(grupo_id=grupo.id, **filtro))
    db.flush()
    return grupo.id


def _campana(db, admin_user, grupo_id: int, nombre: str, estado: str = "activa") -> int:
    campana = SellOutCampana(
        nombre=nombre,
        fecha_desde=date(2026, 11, 1),
        fecha_hasta=date(2026, 11, 30),
        tipo="por_unidad",
        monto_unit=3,
        moneda="ARS",
        usuario_id=admin_user.id,
        estado=estado,
    )
    db.add(campana)
    db.flush()
    db.add(SellOutCampanaGrupo(campana_id=campana.id, grupo_id=grupo_id))
    db.flush()
    return campana.id


class TestRename:
    def test_renames_and_describes_a_group(self, client, db, editor) -> None:
        gid = _grupo(db, "Routers", descripcion="vieja")

        resp = client.patch(
            f"/api/offset-grupos/{gid}", json={"nombre": "  Routers TP-Link ", "descripcion": "Nueva"}, headers=editor
        )

        assert resp.status_code == 200, resp.text
        assert resp.json()["nombre"] == "Routers TP-Link"
        assert resp.json()["descripcion"] == "Nueva"
        db.expire_all()
        grupo = db.get(OffsetGrupo, gid)
        assert (grupo.nombre, grupo.descripcion) == ("Routers TP-Link", "Nueva")

    def test_only_the_fields_sent_change_and_an_empty_description_clears_it(self, client, db, editor) -> None:
        gid = _grupo(db, "Routers", descripcion="Algo")

        assert client.patch(f"/api/offset-grupos/{gid}", json={"descripcion": ""}, headers=editor).status_code == 200

        db.expire_all()
        grupo = db.get(OffsetGrupo, gid)
        assert (grupo.nombre, grupo.descripcion) == ("Routers", None)

    def test_an_empty_name_is_refused(self, client, db, editor) -> None:
        gid = _grupo(db, "Routers")

        resp = client.patch(f"/api/offset-grupos/{gid}", json={"nombre": "   "}, headers=editor)

        assert resp.status_code == 422, resp.text
        assert "nombre" in resp.json()["error"]["message"].lower()
        db.expire_all()
        assert db.get(OffsetGrupo, gid).nombre == "Routers"

    def test_an_unknown_group_is_404(self, client, editor) -> None:
        assert client.patch("/api/offset-grupos/999999", json={"nombre": "X"}, headers=editor).status_code == 404

    def test_without_the_permission_it_is_403_and_nothing_changes(self, client, db, auth_headers) -> None:
        gid = _grupo(db, "Routers")

        assert (
            client.patch(f"/api/offset-grupos/{gid}", json={"nombre": "Otro"}, headers=auth_headers).status_code == 403
        )
        db.expire_all()
        assert db.get(OffsetGrupo, gid).nombre == "Routers"


class TestReach:
    def test_counts_the_products_each_group_reaches_and_the_campaigns_using_it(
        self, client, db, editor, catalogo, admin_user
    ) -> None:
        tplink = _grupo(db, "TP-Link", [{"marca": "TP-LINK"}])
        mixto = _grupo(
            db, "Routers + 950", [{"marca": "TP-LINK", "categoria": "Routers"}, {"item_id": 950}, {"item_id": 2964}]
        )
        vacio = _grupo(db, "Vacío", [{"marca": ""}])  # a row with nothing set reaches nothing
        sin_filtros = _grupo(db, "Sin filtros")
        activa = _campana(db, admin_user, tplink, "Noviembre TP-Link")
        anulada = _campana(db, admin_user, tplink, "Octubre TP-Link", estado="anulada")

        resp = client.get("/api/offset-grupos-alcance", headers=editor)

        assert resp.status_code == 200, resp.text
        por_grupo = {row["grupo_id"]: row for row in resp.json()}
        assert por_grupo[tplink]["productos"] == 2
        assert por_grupo[mixto]["productos"] == 2  # 2964 twice counts once
        assert por_grupo[vacio]["productos"] == 0
        assert por_grupo[sin_filtros]["productos"] == 0
        assert por_grupo[tplink]["campanas"] == [
            {"id": activa, "nombre": "Noviembre TP-Link", "estado": "activa"},
            {"id": anulada, "nombre": "Octubre TP-Link", "estado": "anulada"},
        ]
        assert por_grupo[mixto]["campanas"] == []

    def test_the_number_of_queries_does_not_grow_with_the_groups(
        self, client, db, editor, catalogo, query_counter
    ) -> None:
        _grupo(db, "Uno", [{"marca": "TP-LINK"}])
        with query_counter() as uno:
            assert client.get("/api/offset-grupos-alcance", headers=editor).status_code == 200
        for n in range(5):
            _grupo(db, f"Otro {n}", [{"item_id": 950}, {"categoria": "Routers"}])
        with query_counter() as seis:
            assert client.get("/api/offset-grupos-alcance", headers=editor).status_code == 200

        assert seis.matching("offset_grupo_filtros") == uno.matching("offset_grupo_filtros") == 1
        assert seis.total == uno.total

    def test_without_the_permission_it_is_403(self, client, auth_headers) -> None:
        assert client.get("/api/offset-grupos-alcance", headers=auth_headers).status_code == 403


class TestDelete:
    def test_one_active_campaign_is_named_in_the_singular(self, client, db, editor, admin_user) -> None:
        gid = _grupo(db, "TP-Link")
        _campana(db, admin_user, gid, "Noviembre TP-Link")

        resp = client.delete(f"/api/offset-grupos/{gid}", headers=editor)

        assert resp.status_code == 400, resp.text
        assert resp.json()["error"]["message"] == (
            "El grupo está asignado a la campaña de sell out activa «Noviembre TP-Link». "
            "Quite el grupo de la campaña antes de eliminarlo."
        )

    def test_an_active_campaign_refuses_naming_the_active_campaigns(self, client, db, editor, admin_user) -> None:
        gid = _grupo(db, "TP-Link", [{"marca": "TP-LINK"}])
        _campana(db, admin_user, gid, "Noviembre TP-Link")
        _campana(db, admin_user, gid, "Diciembre TP-Link")
        _campana(db, admin_user, gid, "Octubre anulada", estado="anulada")

        resp = client.delete(f"/api/offset-grupos/{gid}", headers=editor)

        assert resp.status_code == 400, resp.text
        mensaje = resp.json()["error"]["message"]
        assert mensaje.startswith("El grupo está asignado a las campañas de sell out activas")
        assert "Noviembre TP-Link" in mensaje and "Diciembre TP-Link" in mensaje
        assert "Octubre anulada" not in mensaje
        assert mensaje.endswith("Quite el grupo de las campañas antes de eliminarlo.")
        assert db.get(OffsetGrupo, gid) is not None

    def test_voided_campaigns_alone_are_named_and_the_group_stays(self, client, db, editor, admin_user) -> None:
        gid = _grupo(db, "TP-Link")
        _campana(db, admin_user, gid, "Octubre anulada", estado="anulada")
        _campana(db, admin_user, gid, "Septiembre anulada", estado="anulada")

        resp = client.delete(f"/api/offset-grupos/{gid}", headers=editor)

        assert resp.status_code == 400, resp.text
        assert resp.json()["error"]["message"] == (
            "El grupo está vinculado a las campañas de sell out anuladas «Octubre anulada», «Septiembre anulada». "
            "Queda guardado porque es parte de su historial: no se puede eliminar."
        )
        assert db.get(OffsetGrupo, gid) is not None
        assert db.query(SellOutCampanaGrupo).filter_by(grupo_id=gid).count() == 2

    def test_one_voided_campaign_is_named_in_the_singular(self, client, db, editor, admin_user) -> None:
        gid = _grupo(db, "TP-Link")
        _campana(db, admin_user, gid, "Octubre anulada", estado="anulada")

        resp = client.delete(f"/api/offset-grupos/{gid}", headers=editor)

        assert resp.status_code == 400, resp.text
        assert resp.json()["error"]["message"] == (
            "El grupo está vinculado a la campaña de sell out anulada «Octubre anulada». "
            "Queda guardado porque es parte de su historial: no se puede eliminar."
        )

    @pytest.mark.parametrize("con_resumen", [False, True])
    def test_recorded_offset_consumption_refuses_with_a_clear_400(self, client, db, editor, con_resumen) -> None:
        gid = _grupo(db, "Legacy consumido")
        otro = OffsetGanancia(tipo_offset="monto_fijo", monto=1, fecha_desde=date(2026, 1, 1))
        db.add(otro)
        db.flush()
        db.add(
            OffsetGrupoConsumo(
                grupo_id=gid,
                tipo_venta="ml",
                fecha_venta=datetime(2026, 2, 1, tzinfo=timezone.utc),
                item_id=2964,
                cantidad=1,
                offset_id=otro.id,
                monto_offset_aplicado=10,
            )
        )
        if con_resumen:
            db.add(OffsetGrupoResumen(grupo_id=gid))
        db.flush()

        resp = client.delete(f"/api/offset-grupos/{gid}", headers=editor)

        assert resp.status_code == 400, resp.text
        assert resp.json()["error"]["message"] == (
            "No se puede eliminar el grupo: tiene consumo de offsets registrado "
            "(el historial de lo que ya se aplicó en ventas)."
        )
        assert db.get(OffsetGrupo, gid) is not None

    def test_a_consumption_summary_alone_also_refuses(self, client, db, editor) -> None:
        gid = _grupo(db, "Solo resumen")
        db.add(OffsetGrupoResumen(grupo_id=gid))
        db.flush()

        resp = client.delete(f"/api/offset-grupos/{gid}", headers=editor)

        assert resp.status_code == 400, resp.text
        assert db.get(OffsetGrupo, gid) is not None

    def test_a_legacy_offset_keeps_the_existing_refusal(self, client, db, editor) -> None:
        gid = _grupo(db, "Legacy")
        db.add(OffsetGanancia(grupo_id=gid, tipo_offset="monto_fijo", monto=1, fecha_desde=date(2026, 1, 1)))
        db.flush()

        resp = client.delete(f"/api/offset-grupos/{gid}", headers=editor)

        assert resp.status_code == 400, resp.text
        assert resp.json()["error"]["message"] == "No se puede eliminar el grupo, tiene 1 offsets asociados"


class TestPreviewReach:
    """`POST /api/offset-grupos/{id}/alcance-previo`: products reached before -> after adding or removing one filter
    row, with the campaign rule and WITHOUT saving (the panel asks before re-queuing active campaigns)."""

    def test_adding_a_row_counts_the_union(self, client, db, editor, catalogo) -> None:
        gid = _grupo(db, "TP-Link routers", [{"marca": "TP-LINK", "categoria": "Routers"}])

        resp = client.post(
            f"/api/offset-grupos/{gid}/alcance-previo", headers=editor, json={"agregar": {"marca": "MERCUSYS"}}
        )

        assert resp.status_code == 200, resp.text
        assert resp.json() == {"antes": 1, "despues": 2}
        assert db.query(OffsetGrupoFiltro).filter_by(grupo_id=gid).count() == 1

    def test_removing_a_row_drops_what_only_it_reached(self, client, db, editor, catalogo) -> None:
        gid = _grupo(db, "TP-Link", [{"marca": "TP-LINK"}, {"item_id": 950}])
        fid = db.query(OffsetGrupoFiltro.id).filter_by(grupo_id=gid, item_id=950).scalar()

        resp = client.post(f"/api/offset-grupos/{gid}/alcance-previo", headers=editor, json={"quitar_filtro_id": fid})

        assert resp.status_code == 200, resp.text
        assert resp.json() == {"antes": 3, "despues": 2}
        assert db.get(OffsetGrupoFiltro, fid) is not None

    def test_an_empty_row_reaches_nothing_like_the_campaigns(self, client, db, editor, catalogo) -> None:
        gid = _grupo(db, "TP-Link", [{"marca": "TP-LINK"}])

        resp = client.post(f"/api/offset-grupos/{gid}/alcance-previo", headers=editor, json={"agregar": {}})

        assert resp.json() == {"antes": 2, "despues": 2}

    def test_an_unknown_group_is_404(self, client, editor) -> None:
        assert client.post("/api/offset-grupos/999999/alcance-previo", headers=editor, json={}).status_code == 404

    def test_without_the_permission_it_is_403(self, client, db, auth_headers) -> None:
        gid = _grupo(db, "TP-Link")
        assert client.post(f"/api/offset-grupos/{gid}/alcance-previo", headers=auth_headers, json={}).status_code == 403
