"""Legacy `DELETE /api/offset-grupos/{id}` with a group used by a sell-out campaign.

`sell_out_campana_grupos.grupo_id` points at `offset_grupos` with RESTRICT, so the
delete must answer with the same clear 400 it uses for linked offsets, not a
database error.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.offset_grupo import OffsetGrupo
from app.models.sell_out import FK_SELL_OUT_CAMPANA_GRUPOS_GRUPO_ID, SellOutCampana, SellOutCampanaGrupo

PERMISO = "config.editar_constantes"


@pytest.fixture()
def editor(rol_admin, admin_auth_headers, grant_permiso):
    grant_permiso(rol_admin, PERMISO)
    return admin_auth_headers


def _grupo(db, nombre: str) -> int:
    grupo = OffsetGrupo(nombre=nombre)
    db.add(grupo)
    db.flush()
    return grupo.id


def test_group_in_a_sell_out_campaign_is_not_deleted(client, db, editor, admin_user) -> None:
    grupo_id = _grupo(db, "TP-Link redes")
    campana = SellOutCampana(
        nombre="Campaña TP-Link noviembre",
        fecha_desde=date(2026, 11, 1),
        fecha_hasta=date(2026, 11, 30),
        tipo="por_unidad",
        monto_unit=3,
        moneda="USD",
        tc_modo="al_cobro",
        usuario_id=admin_user.id,
    )
    db.add(campana)
    db.flush()
    db.add(SellOutCampanaGrupo(campana_id=campana.id, grupo_id=grupo_id))
    db.flush()

    resp = client.delete(f"/api/offset-grupos/{grupo_id}", headers=editor)

    assert resp.status_code == 400, resp.text
    assert "campaña de sell out" in resp.json()["error"]["message"]
    assert db.get(OffsetGrupo, grupo_id) is not None


def test_group_without_campaigns_is_still_deleted(client, db, editor) -> None:
    grupo_id = _grupo(db, "Sin campañas")
    assert client.delete(f"/api/offset-grupos/{grupo_id}", headers=editor).status_code == 200
    assert db.get(OffsetGrupo, grupo_id) is None


class _PgError(Exception):
    """Stand-in for a psycopg2 error: Postgres names the violated constraint in `diag.constraint_name`."""

    def __init__(self, message: str, constraint_name: str) -> None:
        super().__init__(message)
        self.diag = SimpleNamespace(constraint_name=constraint_name)


def _commit_falla_al_borrar_el_grupo(db, monkeypatch, orig: Exception) -> None:
    """Only the commit that deletes the group fails; the request's other commits run normally."""
    commit_real = db.commit

    def commit_con_integrity_error() -> None:
        if any(isinstance(obj, OffsetGrupo) for obj in db.deleted):
            raise IntegrityError("DELETE FROM offset_grupos", {}, orig)
        commit_real()

    monkeypatch.setattr(db, "commit", commit_con_integrity_error)


def test_a_campaign_linked_between_check_and_commit_still_gets_the_clear_error(client, db, editor, monkeypatch) -> None:
    """Race: the check saw no campaign, but one was linked before the commit (FK RESTRICT violation)."""
    grupo_id = _grupo(db, "Carrera")
    _commit_falla_al_borrar_el_grupo(db, monkeypatch, Exception(FK_SELL_OUT_CAMPANA_GRUPOS_GRUPO_ID))

    resp = client.delete(f"/api/offset-grupos/{grupo_id}", headers=editor)

    assert resp.status_code == 400, resp.text
    assert "campaña de sell out" in resp.json()["error"]["message"]


def test_the_race_is_recognized_by_the_postgres_constraint_name(client, db, editor, monkeypatch) -> None:
    grupo_id = _grupo(db, "Carrera Postgres")
    orig = _PgError("update or delete violates foreign key constraint", FK_SELL_OUT_CAMPANA_GRUPOS_GRUPO_ID)
    _commit_falla_al_borrar_el_grupo(db, monkeypatch, orig)

    resp = client.delete(f"/api/offset-grupos/{grupo_id}", headers=editor)

    assert resp.status_code == 400, resp.text
    assert "campaña de sell out" in resp.json()["error"]["message"]


@pytest.mark.parametrize(
    "orig",
    [
        pytest.param(Exception("fk_offset_ganancias_grupo_id"), id="message-names-another-constraint"),
        pytest.param(_PgError("violates foreign key constraint", "fk_offset_ganancias_grupo_id"), id="postgres-diag"),
        pytest.param(
            _PgError(f"mentions {FK_SELL_OUT_CAMPANA_GRUPOS_GRUPO_ID}", "fk_offset_ganancias_grupo_id"),
            id="postgres-diag-wins-over-message",
        ),
    ],
)
def test_another_integrity_error_is_not_blamed_on_a_sell_out_campaign(client, db, editor, monkeypatch, orig) -> None:
    grupo_id = _grupo(db, "Otra restricción")
    _commit_falla_al_borrar_el_grupo(db, monkeypatch, orig)

    resp = client.delete(f"/api/offset-grupos/{grupo_id}", headers=editor)

    assert resp.status_code == 500, resp.text
    assert "campaña de sell out" not in resp.text
