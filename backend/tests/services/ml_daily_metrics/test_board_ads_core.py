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

import json
import os
from pathlib import Path
from typing import Any, Dict

from tests.integration.test_ml_metricas_board_router import (  # noqa: F401 -- fixtures
    URL,
    _frozen_clock,
    bg_sessions,
    board_data,
)

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
