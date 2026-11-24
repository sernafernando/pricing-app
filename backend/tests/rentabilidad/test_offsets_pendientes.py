"""A profit offset pending approval adds nothing to rentabilidad (tacticals approval S10): on every channel (ML,
fuera de ML, Tienda Nube), by itself or in a group. The approved offsets next to it keep applying as before."""

from datetime import date

import pytest

from app.models.offset_grupo_filtro import OffsetGrupoFiltro
from tests.rentabilidad.test_offsets_negativos import CHANNELS, COMMON_PARAMS, MARCA, _find_card, _make_ml_venta


@pytest.mark.parametrize("endpoint,make_venta,aplica_field", CHANNELS)
def test_a_pending_offset_adds_nothing_and_an_approved_one_still_does(
    client, db, admin_auth_headers, offset_ganancia_factory, endpoint, make_venta, aplica_field
) -> None:
    make_venta(db)
    offset_ganancia_factory(**{"marca": MARCA, "monto": 100.0, aplica_field: True, "estado": "pendiente"})
    offset_ganancia_factory(**{"marca": MARCA, "monto": 30.0, aplica_field: True})  # approved (the default)
    db.commit()

    resp = client.get(endpoint, params=COMMON_PARAMS, headers=admin_auth_headers)

    assert resp.status_code == 200, resp.text
    assert _find_card(resp.json())["offset_total"] == pytest.approx(30.0)


def test_a_pending_group_offset_adds_nothing(
    client, db, admin_auth_headers, offset_grupo_factory, offset_ganancia_factory
) -> None:
    _make_ml_venta(db)
    grupo = offset_grupo_factory()
    db.add(OffsetGrupoFiltro(grupo_id=grupo.id, marca=MARCA))
    offset_ganancia_factory(grupo_id=grupo.id, monto=40.0, fecha_desde=date(2026, 1, 1), estado="pendiente")
    db.commit()

    resp = client.get("/api/rentabilidad", params=COMMON_PARAMS, headers=admin_auth_headers)

    assert resp.status_code == 200, resp.text
    assert _find_card(resp.json())["offset_total"] == pytest.approx(0.0)
