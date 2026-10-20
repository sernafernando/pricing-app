"""Legacy `DELETE /api/offset-grupos/{id}` with a group used by a sell-out campaign.

`sell_out_campana_grupos.grupo_id` points at `offset_grupos` with RESTRICT, so the
delete must answer with the same clear 400 it uses for linked offsets, not a
database error.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.offset_grupo import OffsetGrupo
from app.models.sell_out import SellOutCampana, SellOutCampanaGrupo

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


def test_a_campaign_linked_between_check_and_commit_still_gets_the_clear_error(client, db, editor, monkeypatch) -> None:
    """Race: the check saw no campaign, but one was linked before the commit (FK RESTRICT violation)."""
    grupo_id = _grupo(db, "Carrera")

    commit_real = db.commit

    def commit_con_fk_violada() -> None:
        # Only the commit that deletes the group fails; the request's other commits run normally.
        if any(isinstance(obj, OffsetGrupo) for obj in db.deleted):
            raise IntegrityError("DELETE FROM offset_grupos", {}, Exception("fk_sell_out_campana_grupos_grupo_id"))
        commit_real()

    monkeypatch.setattr(db, "commit", commit_con_fk_violada)
    resp = client.delete(f"/api/offset-grupos/{grupo_id}", headers=editor)

    assert resp.status_code == 400, resp.text
    assert "campaña de sell out" in resp.json()["error"]["message"]
