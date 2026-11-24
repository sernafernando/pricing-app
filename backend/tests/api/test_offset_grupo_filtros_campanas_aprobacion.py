# ruff: noqa: F811 - the fixtures imported from the neighbour test modules are taken as parameters
"""A group's filters are the scope of every campaign using it, and scope is money (tacticals approval S14, L31/Q5):
adding, removing or replacing a filter of a group sends its approved sell-out campaigns back to `pendiente`, one
audit row each; a tactical's campaign takes its whole tactical back. A pending campaign stays pending; replacing the
filters with the same ones changes nothing. `GET /offset-grupos/{id}/aprobadas-afectadas` tells the edit screen how
many approved campaigns and offsets would go back, behind the filter endpoints' permission. SQLite."""

from __future__ import annotations

from datetime import date

import pytest

from app.models.auditoria import Auditoria, TipoAccion
from app.models.offset_ganancia import OffsetGanancia
from app.models.offset_grupo import OffsetGrupo
from app.models.offset_grupo_filtro import OffsetGrupoFiltro
from app.models.sell_out import SellOutCampana, SellOutCampanaGrupo
from app.models.tactical import Tactical
from tests.api.test_offsets_ganancia_crud import _grant_editar_constantes  # noqa: F401 - autouse fixture
from tests.routers.test_sell_out_campanas import BASE as CAMPANAS, _crear as _crear_campana
from tests.routers.test_tacticals import BASE as TACTICALS, _body as _body_tactical, productos  # noqa: F401

APROBAR = "tacticals.aprobar"


@pytest.fixture()
def aprobador(rol_admin, admin_auth_headers, grant_permiso):
    for codigo in ("sell_out.ver", "sell_out.gestionar", APROBAR):
        grant_permiso(rol_admin, codigo)
    return admin_auth_headers


@pytest.fixture()
def grupo(db) -> OffsetGrupo:
    g = OffsetGrupo(nombre="TP-Link redes")
    db.add(g)
    db.flush()
    db.add(OffsetGrupoFiltro(grupo_id=g.id, marca="TP-LINK"))
    db.commit()
    return g


def _campana(client, headers, grupo_id: int, aprobar: bool = True) -> int:
    campana = _crear_campana(client, headers, [grupo_id])
    if aprobar:
        assert client.post(f"{CAMPANAS}/{campana['id']}/aprobar", headers=headers).status_code == 200
    return campana["id"]


def _estado(db, campana_id: int) -> str:
    db.expire_all()
    return db.get(SellOutCampana, campana_id).estado


def _audit_campana(db, campana_id: int) -> list[Auditoria]:
    filas = db.query(Auditoria).filter(Auditoria.tipo_accion == TipoAccion.TACTICAL_A_PENDIENTE).all()
    return [a for a in filas if (a.valores_nuevos or {}).get("campana_id") == campana_id]


def _filtro_id(db, grupo_id: int) -> int:
    return db.query(OffsetGrupoFiltro.id).filter(OffsetGrupoFiltro.grupo_id == grupo_id).scalar()


# --- the filter edit -----------------------------------------------------------------------------------------------


def test_adding_a_filter_sends_an_approved_campaign_back_with_an_audit_row(client, db, aprobador, grupo) -> None:
    campana_id = _campana(client, aprobador, grupo.id)
    db.autoflush = False  # as SessionLocal in production

    resp = client.post(f"/api/offset-grupos/{grupo.id}/filtros", json={"marca": "EPSON"}, headers=aprobador)

    assert (resp.status_code, resp.json()["marca"]) == (200, "EPSON")  # the answer as before
    assert _estado(db, campana_id) == "pendiente"
    [audit] = _audit_campana(db, campana_id)
    assert audit.comentario == f"Se editaron los filtros del grupo {grupo.id}"
    assert db.query(OffsetGrupoFiltro).filter(OffsetGrupoFiltro.grupo_id == grupo.id).count() == 2  # stored


def test_removing_a_filter_sends_an_approved_campaign_back(client, db, aprobador, grupo) -> None:
    campana_id = _campana(client, aprobador, grupo.id)
    db.autoflush = False

    resp = client.delete(f"/api/offset-grupos/{grupo.id}/filtros/{_filtro_id(db, grupo.id)}", headers=aprobador)

    assert resp.json() == {"mensaje": "Filtro eliminado"}
    assert _estado(db, campana_id) == "pendiente"
    assert len(_audit_campana(db, campana_id)) == 1


def test_replacing_the_filters_sends_it_back_and_the_same_filters_do_not(client, db, aprobador, grupo) -> None:
    campana_id = _campana(client, aprobador, grupo.id)
    db.autoflush = False

    mismos = client.put(f"/api/offset-grupos/{grupo.id}/filtros", json=[{"marca": "TP-LINK"}], headers=aprobador)
    assert mismos.json()["mensaje"] == "Se actualizaron 1 filtros"
    assert _estado(db, campana_id) == "activa"
    assert _audit_campana(db, campana_id) == []

    otros = client.put(f"/api/offset-grupos/{grupo.id}/filtros", json=[{"marca": "EPSON"}], headers=aprobador)

    assert otros.json()["mensaje"] == "Se actualizaron 1 filtros"
    assert _estado(db, campana_id) == "pendiente"
    assert len(_audit_campana(db, campana_id)) == 1


def test_a_pending_campaign_stays_pending_with_no_audit_row(client, db, aprobador, grupo) -> None:
    campana_id = _campana(client, aprobador, grupo.id, aprobar=False)

    resp = client.post(f"/api/offset-grupos/{grupo.id}/filtros", json={"marca": "EPSON"}, headers=aprobador)

    assert resp.status_code == 200
    assert _estado(db, campana_id) == "pendiente"
    assert _audit_campana(db, campana_id) == []


def test_a_campaign_of_another_group_is_untouched(client, db, aprobador, grupo) -> None:
    otro = OffsetGrupo(nombre="Epson tintas")
    db.add(otro)
    db.commit()
    campana_id = _campana(client, aprobador, otro.id)

    client.post(f"/api/offset-grupos/{grupo.id}/filtros", json={"marca": "EPSON"}, headers=aprobador)

    assert _estado(db, campana_id) == "activa"


def test_a_tacticals_campaign_takes_its_whole_tactical_back(client, db, productos, aprobador, grupo) -> None:
    resp = client.post(TACTICALS, json=_body_tactical(), headers=aprobador)
    tactical_id = resp.json()["id"]
    assert client.post(f"{TACTICALS}/{tactical_id}/aprobar", headers=aprobador).status_code == 200
    campana = db.query(SellOutCampana).filter(SellOutCampana.tactical_id == tactical_id).one()
    db.add(SellOutCampanaGrupo(campana_id=campana.id, grupo_id=grupo.id))  # a visible group next to its own one
    db.commit()
    db.autoflush = False

    client.post(f"/api/offset-grupos/{grupo.id}/filtros", json={"marca": "EPSON"}, headers=aprobador)

    assert _estado(db, campana.id) == "pendiente"
    tactical = db.get(Tactical, tactical_id)
    assert (tactical.estado, tactical.aprobado_por, tactical.aprobado_at) == ("pendiente", None, None)
    audits = db.query(Auditoria).filter(Auditoria.tipo_accion == TipoAccion.TACTICAL_A_PENDIENTE).all()
    assert [a.valores_nuevos["tactical_id"] for a in audits if "tactical_id" in (a.valores_nuevos or {})] == [
        tactical_id
    ]


# --- the preview count ---------------------------------------------------------------------------------------------


def test_the_count_is_the_approved_campaigns_and_offsets_of_the_group(client, db, aprobador, grupo) -> None:
    _campana(client, aprobador, grupo.id)
    _campana(client, aprobador, grupo.id)
    _campana(client, aprobador, grupo.id, aprobar=False)
    db.add_all(
        [
            OffsetGanancia(grupo_id=grupo.id, tipo_offset="monto_fijo", monto=10, fecha_desde=date(2026, 1, 1)),
            OffsetGanancia(
                grupo_id=grupo.id, tipo_offset="monto_fijo", monto=5, fecha_desde=date(2026, 1, 1), estado="pendiente"
            ),
        ]
    )
    db.commit()

    resp = client.get(f"/api/offset-grupos/{grupo.id}/aprobadas-afectadas", headers=aprobador)

    assert (resp.status_code, resp.json()) == (200, {"campanas": 2, "offsets": 1})


def test_the_count_of_a_group_with_nothing_approved_is_zero(client, aprobador, grupo) -> None:
    resp = client.get(f"/api/offset-grupos/{grupo.id}/aprobadas-afectadas", headers=aprobador)

    assert resp.json() == {"campanas": 0, "offsets": 0}


def test_the_count_needs_the_filter_permission_and_a_visible_group(client, db, auth_headers, aprobador, grupo) -> None:
    assert client.get(f"/api/offset-grupos/{grupo.id}/aprobadas-afectadas", headers=auth_headers).status_code == 403
    assert client.get(f"/api/offset-grupos/{grupo.id}/aprobadas-afectadas").status_code in (401, 403)
    oculto = OffsetGrupo(nombre="Línea de tactical", oculto=True)
    db.add(oculto)
    db.commit()
    assert client.get(f"/api/offset-grupos/{oculto.id}/aprobadas-afectadas", headers=aprobador).status_code == 404
    assert client.get("/api/offset-grupos/999999/aprobadas-afectadas", headers=aprobador).status_code == 404


class _Deadlock(Exception):
    pgcode = "40P01"  # deadlock_detected: Postgres aborted this transaction to break a lock cycle


@pytest.mark.parametrize("motivo", ["deadlock", "recalculando"])
def test_a_busy_campaign_or_a_deadlock_is_a_409_and_nothing_is_stored(
    client, db, aprobador, grupo, monkeypatch, motivo
) -> None:
    """A campaign being rebuilt by the sell out drain, or a deadlock with another approval or edit, refuses the filter
    edit with a 409 to retry: the filter is not stored and the campaign keeps its approval."""
    from sqlalchemy.exc import DBAPIError

    from app.services.sell_in import aprobacion
    from app.services.sell_out import campanas

    campana_id = _campana(client, aprobador, grupo.id)
    filtros_antes = db.query(OffsetGrupoFiltro).filter(OffsetGrupoFiltro.grupo_id == grupo.id).count()

    def _ocupado(db_, *_args, **_kwargs):
        if motivo == "deadlock":
            raise DBAPIError("SELECT ... FOR UPDATE", {}, _Deadlock())
        db_.rollback()
        raise campanas.SellOutRecalculando(campanas.OCUPADA)

    monkeypatch.setattr(aprobacion, "a_pendiente_el_grupo", _ocupado)

    resp = client.post(f"/api/offset-grupos/{grupo.id}/filtros", json={"marca": "EPSON"}, headers=aprobador)

    assert resp.status_code == 409, resp.text
    db.expire_all()
    assert db.query(OffsetGrupoFiltro).filter(OffsetGrupoFiltro.grupo_id == grupo.id).count() == filtros_antes
    assert _estado(db, campana_id) == "activa"
