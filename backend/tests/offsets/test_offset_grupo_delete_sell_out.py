"""Legacy `DELETE /api/offset-grupos/{id}` with a group used by a sell-out campaign.

`sell_out_campana_grupos.grupo_id` points at `offset_grupos` with RESTRICT, so the
delete must answer with the same clear 400 it uses for linked offsets, not a
database error.
"""

from __future__ import annotations

from datetime import date

import pytest

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
        monto_unit=1500,
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
