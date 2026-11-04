"""The Grupos tab for those who only read it, and deleting several groups at once (sell-in-out tactical T3, S9).

Owner: "hoy no existe un permiso para que se vean los grupos, así que solo yo los veo, no tengo una forma de borrar
los grupos de manera masiva".

- `grupos.ver` reads what each group reaches (`GET /api/offset-grupos-alcance`); `config.editar_constantes` still
  does too, as before.
- `POST /api/offset-grupos/eliminar` deletes the groups the single delete would delete and, for each other one,
  answers why it stays, with the single delete's own message. Same permission as the single delete.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.offset_ganancia import OffsetGanancia
from app.models.offset_grupo import OffsetGrupo
from app.models.offset_grupo_consumo import OffsetGrupoConsumo
from app.models.offset_grupo_filtro import OffsetGrupoFiltro
from app.models.sell_out import FK_SELL_OUT_CAMPANA_GRUPOS_GRUPO_ID, SellOutCampana, SellOutCampanaGrupo

EDITAR = "config.editar_constantes"
VER = "grupos.ver"
URL = "/api/offset-grupos/eliminar"


@pytest.fixture()
def editor(rol_admin, admin_auth_headers, grant_permiso):
    grant_permiso(rol_admin, EDITAR)
    return admin_auth_headers


@pytest.fixture()
def lector(rol_admin, admin_auth_headers, grant_permiso):
    grant_permiso(rol_admin, VER)
    return admin_auth_headers


def _grupo(db, nombre: str, filtros=()) -> int:
    grupo = OffsetGrupo(nombre=nombre)
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


def _ids_que_quedan(db, ids) -> list:
    db.expire_all()
    return sorted(gid for gid in ids if db.get(OffsetGrupo, gid) is not None)


class TestVer:
    def test_grupos_ver_reads_the_reach(self, client, db, lector) -> None:
        gid = _grupo(db, "TP-Link")
        resp = client.get("/api/offset-grupos-alcance", headers=lector)
        assert resp.status_code == 200, resp.text
        assert [row["grupo_id"] for row in resp.json()] == [gid]

    def test_editar_constantes_still_reads_it(self, client, db, editor) -> None:
        _grupo(db, "TP-Link")
        assert client.get("/api/offset-grupos-alcance", headers=editor).status_code == 200

    def test_grupos_ver_does_not_delete_or_edit(self, client, db, lector) -> None:
        gid = _grupo(db, "TP-Link")
        assert client.post(URL, json={"ids": [gid]}, headers=lector).status_code == 403
        assert client.delete(f"/api/offset-grupos/{gid}", headers=lector).status_code == 403
        assert client.patch(f"/api/offset-grupos/{gid}", json={"nombre": "X"}, headers=lector).status_code == 403
        assert _ids_que_quedan(db, [gid]) == [gid]


class TestBorradoMasivo:
    def test_deletes_the_free_groups_and_says_why_each_other_one_stays(self, client, db, editor, admin_user) -> None:
        libre = _grupo(db, "Libre", [{"marca": "TP-LINK"}])
        otro_libre = _grupo(db, "Otro libre")
        activa = _grupo(db, "Con activa")
        _campana(db, admin_user, activa, "Noviembre TP-Link")
        anulada = _grupo(db, "Con anulada")
        _campana(db, admin_user, anulada, "Octubre anulada", estado="anulada")
        legacy = _grupo(db, "Legacy")
        db.add(OffsetGanancia(grupo_id=legacy, tipo_offset="monto_fijo", monto=1, fecha_desde=date(2026, 1, 1)))
        consumido = _grupo(db, "Consumido")
        offset = OffsetGanancia(tipo_offset="monto_fijo", monto=1, fecha_desde=date(2026, 1, 1))
        db.add(offset)
        db.flush()
        db.add(
            OffsetGrupoConsumo(
                grupo_id=consumido,
                tipo_venta="ml",
                fecha_venta=datetime(2026, 2, 1, tzinfo=timezone.utc),
                item_id=2964,
                cantidad=1,
                offset_id=offset.id,
                monto_offset_aplicado=10,
            )
        )
        db.flush()
        ids = [libre, otro_libre, activa, anulada, legacy, consumido]

        resp = client.post(URL, json={"ids": ids}, headers=editor)

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert sorted(body["eliminados"]) == sorted([libre, otro_libre])
        motivos = {r["id"]: r for r in body["rechazados"]}
        assert set(motivos) == {activa, anulada, legacy, consumido}
        assert motivos[activa]["nombre"] == "Con activa"
        assert motivos[activa]["motivo"] == (
            "El grupo está asignado a la campaña de sell out activa «Noviembre TP-Link». "
            "Quite el grupo de la campaña antes de eliminarlo."
        )
        assert motivos[anulada]["motivo"] == (
            "El grupo está vinculado a la campaña de sell out anulada «Octubre anulada». "
            "Queda guardado porque es parte de su historial: no se puede eliminar."
        )
        assert motivos[legacy]["motivo"] == "No se puede eliminar el grupo, tiene 1 offsets asociados"
        assert motivos[consumido]["motivo"].startswith("No se puede eliminar el grupo: tiene consumo de offsets")
        assert _ids_que_quedan(db, ids) == sorted([activa, anulada, legacy, consumido])
        assert db.query(OffsetGrupoFiltro).filter_by(grupo_id=libre).count() == 0  # its filters go with it

    def test_an_unknown_id_is_named_and_the_rest_still_goes(self, client, db, editor) -> None:
        gid = _grupo(db, "Libre")
        resp = client.post(URL, json={"ids": [gid, 999999]}, headers=editor)
        assert resp.status_code == 200, resp.text
        assert resp.json() == {
            "eliminados": [gid],
            "rechazados": [{"id": 999999, "nombre": None, "motivo": "Grupo no encontrado"}],
        }

    def test_a_repeated_id_counts_once(self, client, db, editor) -> None:
        gid = _grupo(db, "Libre")
        resp = client.post(URL, json={"ids": [gid, gid]}, headers=editor)
        assert resp.json() == {"eliminados": [gid], "rechazados": []}

    @pytest.mark.parametrize("ids", [[], list(range(1, 502))])
    def test_none_or_more_than_500_is_422(self, client, db, editor, ids) -> None:
        gid = _grupo(db, "Libre")
        assert client.post(URL, json={"ids": ids}, headers=editor).status_code == 422
        assert _ids_que_quedan(db, [gid]) == [gid]

    def test_without_the_permission_it_is_403_and_nothing_goes(self, client, db, auth_headers) -> None:
        gid = _grupo(db, "Libre")
        assert client.post(URL, json={"ids": [gid]}, headers=auth_headers).status_code == 403
        assert _ids_que_quedan(db, [gid]) == [gid]

    def test_a_campaign_linked_meanwhile_keeps_only_that_group(self, client, db, editor, monkeypatch) -> None:
        # Between the checks and the delete a campaign took the group: the RESTRICT FK stops that one alone.
        tomado = _grupo(db, "Tomado")
        libre = _grupo(db, "Libre")
        flush_real = db.flush

        class _PgError(Exception):
            def __init__(self) -> None:
                super().__init__("violates foreign key")
                self.diag = type("D", (), {"constraint_name": FK_SELL_OUT_CAMPANA_GRUPOS_GRUPO_ID})()

        def flush(*args, **kwargs):
            if any(isinstance(obj, OffsetGrupo) and obj.id == tomado for obj in db.deleted):
                raise IntegrityError("DELETE FROM offset_grupos", {}, _PgError())
            return flush_real(*args, **kwargs)

        monkeypatch.setattr(db, "flush", flush)

        resp = client.post(URL, json={"ids": [tomado, libre]}, headers=editor)

        assert resp.status_code == 200, resp.text
        assert resp.json()["eliminados"] == [libre]
        assert resp.json()["rechazados"] == [
            {
                "id": tomado,
                "nombre": "Tomado",
                "motivo": "El grupo está asignado a una campaña de sell out. "
                "Quite el grupo de la campaña antes de eliminarlo.",
            }
        ]
        monkeypatch.setattr(db, "flush", flush_real)
        assert _ids_que_quedan(db, [tomado, libre]) == [tomado]
