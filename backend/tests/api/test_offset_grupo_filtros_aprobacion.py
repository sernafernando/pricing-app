"""A group's filters are its offsets' scope, and scope is money (tacticals approval S5, S10; verifier A3): adding,
removing or replacing a filter of a group sends its approved offsets back to `pendiente`, as a money edit of the
offset itself does. A pending offset stays pending; replacing the filters with the same ones changes nothing. SQLite."""

from datetime import date

import pytest

from app.models.offset_ganancia import OffsetGanancia
from app.models.offset_grupo_filtro import OffsetGrupoFiltro
from tests.api.test_offsets_ganancia_crud import _grant_editar_constantes  # noqa: F401 - autouse fixture


@pytest.fixture()
def grupo(db, offset_grupo_factory):
    g = offset_grupo_factory()
    db.add(OffsetGrupoFiltro(grupo_id=g.id, marca="HP"))
    aprobado = OffsetGanancia(grupo_id=g.id, tipo_offset="monto_fijo", monto=10, fecha_desde=date(2026, 1, 1))
    pendiente = OffsetGanancia(
        grupo_id=g.id, tipo_offset="monto_fijo", monto=20, fecha_desde=date(2026, 1, 1), estado="pendiente"
    )
    db.add_all([aprobado, pendiente])
    db.commit()
    return g


def _estados(db, grupo_id) -> list[str]:
    db.expire_all()
    filas = db.query(OffsetGanancia).filter(OffsetGanancia.grupo_id == grupo_id).order_by(OffsetGanancia.id)
    return [o.estado for o in filas]


def _filtro_id(db, grupo_id) -> int:
    return db.query(OffsetGrupoFiltro.id).filter(OffsetGrupoFiltro.grupo_id == grupo_id).scalar()


def test_adding_a_filter_sends_the_approved_offsets_back(client, db, admin_auth_headers, grupo) -> None:
    resp = client.post(f"/api/offset-grupos/{grupo.id}/filtros", json={"marca": "EPSON"}, headers=admin_auth_headers)

    assert (resp.status_code, resp.json()["marca"]) == (200, "EPSON")  # the answer as before
    assert _estados(db, grupo.id) == ["pendiente", "pendiente"]


def test_removing_a_filter_sends_the_approved_offsets_back(client, db, admin_auth_headers, grupo) -> None:
    filtro = _filtro_id(db, grupo.id)

    resp = client.delete(f"/api/offset-grupos/{grupo.id}/filtros/{filtro}", headers=admin_auth_headers)

    assert resp.json() == {"mensaje": "Filtro eliminado"}
    assert _estados(db, grupo.id) == ["pendiente", "pendiente"]


def test_replacing_the_filters_sends_them_back_and_the_same_filters_do_not(
    client, db, admin_auth_headers, grupo
) -> None:
    mismos = client.put(f"/api/offset-grupos/{grupo.id}/filtros", json=[{"marca": "HP"}], headers=admin_auth_headers)
    assert mismos.json()["mensaje"] == "Se actualizaron 1 filtros"
    assert _estados(db, grupo.id) == ["activa", "pendiente"]

    otros = client.put(f"/api/offset-grupos/{grupo.id}/filtros", json=[{"marca": "EPSON"}], headers=admin_auth_headers)

    assert otros.json()["mensaje"] == "Se actualizaron 1 filtros"
    assert _estados(db, grupo.id) == ["pendiente", "pendiente"]


def test_a_group_with_only_pending_offsets_keeps_them_pending(client, db, admin_auth_headers, offset_grupo_factory):
    g = offset_grupo_factory()
    db.add(
        OffsetGanancia(
            grupo_id=g.id, tipo_offset="monto_fijo", monto=5, fecha_desde=date(2026, 1, 1), estado="pendiente"
        )
    )
    db.commit()

    resp = client.post(f"/api/offset-grupos/{g.id}/filtros", json={"marca": "HP"}, headers=admin_auth_headers)

    assert resp.status_code == 200
    assert _estados(db, g.id) == ["pendiente"]
