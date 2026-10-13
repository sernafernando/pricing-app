"""ODD `ml-billing-balance` PR 7a: the "Restar publicidad" toggle of the Métricas ML board.

T1 (characterization): with the toggle OFF the board answers exactly what it
answered before the toggle existed. `golden/board_off_responses.json` was
generated on UNMODIFIED main (the RED commit of this PR), for `solo_con_ventas`
true AND false in the product, publication and group views. Later slices may
only add `kpis.ads` and `rows[].ads` to the response: `_without_ads` strips
them before comparing. Regenerate it only deliberately, with
`UPDATE_ADS_GOLDEN=1`, and review the diff: a change there is a change to
Métricas ML.
"""

# ruff: noqa: F811 -- the imported fixtures are re-named by the tests that use them
from __future__ import annotations

import dataclasses
import json
import os
from pathlib import Path
from typing import Any, Dict

import pytest

from app.services.ml_daily_metrics import board
from tests.integration.test_ml_metricas_board_router import (  # noqa: F401 -- fixtures
    URL,
    _day,
    _frozen_clock,
    _grant,
    _producto,
    _pub,
    bg_sessions,
    board_data,
)
from datetime import date

GOLDEN = Path(__file__).parent / "golden" / "board_off_responses.json"

VIEWS = {
    "product": {"group_by": "product"},
    "publication": {"group_by": "publication"},
    "group": {"group_by": "group", "dimension": "marca"},
}


def _without_ads(body: Dict[str, Any]) -> Dict[str, Any]:
    """The response minus the fields later slices add (`kpis.ads`, `rows[].ads`)."""
    kept = {**body, "kpis": {k: v for k, v in body["kpis"].items() if k != "ads"}}
    kept["rows"] = [{k: v for k, v in row.items() if k != "ads"} for row in body["rows"]]
    return kept


def _scenarios() -> Dict[str, Dict[str, str]]:
    return {
        f"{view}-solo_{flag}": {**params, "solo_con_ventas": flag}
        for view, params in VIEWS.items()
        for flag in ("true", "false")
    }


def _off_responses(client, headers, **extra: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for name, params in _scenarios().items():
        resp = client.get(URL, params={**params, **extra}, headers=headers)
        assert resp.status_code == 200, resp.text
        out[name] = _without_ads(resp.json())
    return out


def test_off_responses_are_pinned_to_main(client, admin_auth_headers, board_data) -> None:
    captured = _off_responses(client, admin_auth_headers)
    if os.environ.get("UPDATE_ADS_GOLDEN") == "1":
        GOLDEN.write_text(json.dumps(captured, indent=1, sort_keys=True) + "\n")
    pinned = json.loads(GOLDEN.read_text())
    assert set(captured) == set(pinned)
    for name in pinned:
        assert captured[name] == pinned[name], f"OFF board response changed for {name!r}"
        assert captured[name]["rows"], f"scenario {name!r} returned no rows"


# ── T2: the parameter, its gate and the field classification ─────────────────


def test_explicit_false_equals_absent_and_both_equal_main(client, admin_auth_headers, board_data) -> None:
    pinned = json.loads(GOLDEN.read_text())
    explicit = _off_responses(client, admin_auth_headers, restar_publicidad="false")
    assert explicit == pinned


ENDPOINTS = {
    "board": URL,
    "publications": f"{URL}/products/11/publications",
    "group-nodes": f"{URL}/group-nodes",
    "export": f"{URL}/export",
}


@pytest.fixture()
def only_ver(db, rol_admin):
    """A user with `ml_metricas.ver` but NOT `ml_metricas.ver_ganancia`."""
    _grant(db, rol_admin, "ml_metricas.ver")
    _producto(db, 11, "Impresora", "Epson")
    _pub(db, 1, "MLA1", 11, 57997)
    _day(db, 11, "MLA1", date(2026, 9, 30), 2, "200", "30", "100")
    db.commit()


@pytest.mark.parametrize("name", sorted(ENDPOINTS))
def test_restar_publicidad_without_ver_ganancia_is_403(name, client, admin_auth_headers, only_ver) -> None:
    params = {"restar_publicidad": "true"}
    if name == "group-nodes":
        params["path"] = json.dumps(["EPSON"])
    resp = client.get(ENDPOINTS[name], params=params, headers=admin_auth_headers)
    assert resp.status_code == 403, resp.text
    assert "ver_ganancia" in resp.text


def test_restar_publicidad_false_without_ver_ganancia_is_not_gated(client, admin_auth_headers, only_ver) -> None:
    resp = client.get(URL, params={"restar_publicidad": "false"}, headers=admin_auth_headers)
    assert resp.status_code == 200, resp.text


def test_restar_publicidad_with_ver_ganancia_is_accepted(client, admin_auth_headers, board_data) -> None:
    resp = client.get(URL, params={"restar_publicidad": "true"}, headers=admin_auth_headers)
    assert resp.status_code == 200, resp.text


def test_the_board_reads_the_toggle_from_the_filter(db) -> None:
    day = date(2026, 9, 30)
    off = board.BoardFilter(date_from=day, date_to=day)
    on = dataclasses.replace(off, restar_publicidad=True)
    assert off.restar_publicidad is False
    assert board.Board(db, off, scope_pairs=None).ads is False
    assert board.Board(db, on, scope_pairs=None).ads is True


def test_every_board_filter_field_is_classified() -> None:
    """A new `BoardFilter` field must be classified: a FILTER narrows the
    universe (an unfiltered view is the only one that may show account-level
    ads), NAVIGATION only picks how the same universe is read. Unclassified
    fails here instead of silently counting as navigation."""
    fields = {f.name for f in dataclasses.fields(board.BoardFilter)}
    assert board.FILTER_FIELDS.isdisjoint(board.NAVIGATION_FIELDS)
    assert fields == board.FILTER_FIELDS | board.NAVIGATION_FIELDS


def test_solo_con_ventas_is_navigation_not_a_filter() -> None:
    """Owner decision (#2281 Q9): hiding rows without sales does not narrow the universe."""
    assert {"solo_con_ventas", "group_by", "dimension", "sort", "sort_desc"} <= board.NAVIGATION_FIELDS
    assert {"stores", "marcas", "pms", "q", "mla_source"} <= board.FILTER_FIELDS
