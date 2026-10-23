"""Characterization of the Métricas ML board on Postgres (perf work, "behaviour
must stay identical"): the FULL response of `build_board_response` -- rows,
totals, KPIs, facets -- plus the sub-rows and group-node readers, pinned as
digests for representative filters.

The digests in `golden_board_digests.json` were recorded on the code BEFORE
the query optimisations. A change that alters a number, a row, an ordering or
a facet count fails here, naming the scenario and the section. After an
INTENDED behaviour change regenerate with `BOARD_GOLDEN_WRITE=1`; set
`BOARD_GOLDEN_DUMP=<dir>` to write each section as readable JSON to diff.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.models.mercadolibre_item_publicado import MercadoLibreItemPublicado as Pub
from app.routers.ml_metricas import build_board_response
from app.services.ml_daily_metrics import board
from tests.services.ml_daily_metrics import test_board_volume_postgres as volume

GOLDEN = Path(__file__).with_name("golden_board_digests.json")
SCALE = volume.Scale(products=300, publications=900, groups=9000, dense=3000)
TODAY = volume.TODAY

# name -> (filter kwargs, request kwargs)
SCENARIOS: Dict[str, Dict[str, Any]] = {
    "product_default": {},
    "product_page2": {"limit": 20, "offset": 20},
    "product_30d_window": {"date_from": TODAY - timedelta(days=29)},
    "product_past_period": {"date_from": TODAY - timedelta(days=79), "date_to": TODAY - timedelta(days=50)},
    "product_year_compare_markup_asc": {"compare": "anio_anterior", "sort": "markup", "sort_desc": False},
    "product_sort_title": {"sort": "title", "sort_desc": False},
    "product_sort_last_sale": {"sort": "last_sale"},
    "publication": {"group_by": "publication"},
    "group_marca": {"group_by": "group", "dimension": "marca"},
    "group_tienda": {"group_by": "group", "dimension": "tienda"},
    "store": {"stores": ("2645",)},
    "store_and_no_store": {"stores": ("57997", "sin_tienda")},
    "marca": {"marcas": ("Samsung",)},
    "marca_categoria_subcategoria": {"marcas": ("Epson", "Sony"), "categorias": ("Cat1",), "subcategorias": (2, 3)},
    "status_and_type": {"pub_status": ("active",), "pub_type": ("premium", "full")},
    "exclusions": {"pub_status_exclude": ("paused",), "pub_type_exclude": ("catalogo",)},
    "search": {"q": "volumen 17"},
    "search_mla": {"q": "mla77000042"},
    "search_no_match": {"q": "no-existe-nada"},
    "row_filters": {"stock": ("sin_stock",), "ageing": ("up_to_30",), "solo_con_ventas": True},
    "alerts": {"alerts": ("sin_ventas_30d", "margen_cayendo")},
    "everything_at_once": {
        "stores": ("2645", "144"),
        "marcas": ("Lenovo", "Sony", "BGH"),
        "pub_status": ("active", "paused"),
        "solo_con_ventas": True,
        "sort": "units_7d",
    },
    "scope_one_pair": {"_scope_pairs": [("EPSON", "CAT0")]},
    "scope_empty": {"_scope_pairs": []},
    "mla_source": {"_mla_source": "store_2645"},
    "mla_source_publication": {"_mla_source": "store_2645", "group_by": "publication"},
    "mla_source_empty": {"_mla_source": "none"},
}


@pytest.fixture(scope="module")
def world(board_pg_engine):
    connection = board_pg_engine.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection)()
    volume._seed(session, SCALE)
    yield session
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture(autouse=True)
def _frozen_world(monkeypatch):
    monkeypatch.setattr(board, "now_utc", lambda: volume.NOW)
    monkeypatch.setattr(settings, "ML_USER_ID", 999)


def _plain(value: Any) -> Any:
    """JSON for what `json` cannot write. A timestamp is written in UTC: the driver
    returns it in the SESSION time zone of the server, which differs between
    machines (the instant is what the board reports)."""
    if isinstance(value, datetime) and value.tzinfo is not None:
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _digest(value: Any) -> str:
    text = json.dumps(value, sort_keys=True, default=_plain, ensure_ascii=True)
    return hashlib.sha256(text.encode()).hexdigest()[:20]


def _dump(name: str, section: str, value: Any) -> None:
    target = os.environ.get("BOARD_GOLDEN_DUMP")
    if target:
        Path(target).mkdir(parents=True, exist_ok=True)
        Path(target, f"{name}.{section}.json").write_text(json.dumps(value, sort_keys=True, default=_plain, indent=1))


def _mla_source(kind: str):
    if kind == "none":
        return select(Pub.mlp_publicationID).where(Pub.mlp_official_store_id == -1)
    return select(Pub.mlp_publicationID).where(Pub.mlp_official_store_id == 2645)


def _board_response(session, name: str, spec: Dict[str, Any]) -> Dict[str, Any]:
    spec = dict(spec)
    scope_pairs = spec.pop("_scope_pairs", None)
    source = spec.pop("_mla_source", None)
    limit, offset = spec.pop("limit", 20), spec.pop("offset", 0)
    spec.setdefault("date_from", TODAY - timedelta(days=29))
    spec.setdefault("date_to", TODAY)
    f = board.BoardFilter(**spec, mla_source=_mla_source(source) if source else None)
    response = build_board_response(
        session, f, limit=limit, offset=offset, can_see_margin=True, scope_pairs=scope_pairs
    )
    data = response.model_dump()
    return {
        "meta": {k: v for k, v in data.items() if k not in ("kpis", "facets", "rows")},
        # The additive `kpis.ads` and "Costos TP" fields (null with their toggles OFF) are not part of what
        # these digests pin.
        "kpis": {k: v for k, v in data["kpis"].items() if k not in ("ads", "total_tp", "sell_in_out") or v is not None},
        "facets": data["facets"],
        "rows": [_without_null_tp(row) for row in data["rows"]],
    }


TP_FIELDS = (
    "total_tp",
    "tp_incompletos",
    # sell-in-sell-out T11, null with `sell_in_out` OFF.
    "sell_in",
    "sell_out",
    "m_sell_in",
    "m_sell_out",
    "sell_out_pendientes",
    "sell_out_estimados",
    "sell_in_out",
)


def _without_null_tp(row: Dict[str, Any]) -> Dict[str, Any]:
    """A row minus the "Costos TP" and sell in / sell out fields while they are null (their toggles OFF):
    additive, not pinned here."""
    return {k: v for k, v in row.items() if k not in TP_FIELDS or v is not None}


def _compute(session) -> Dict[str, Dict[str, str]]:
    out: Dict[str, Dict[str, str]] = {}
    for name, spec in SCENARIOS.items():
        sections = _board_response(session, name, spec)
        for section, value in sections.items():
            _dump(name, section, value)
        out[name] = {section: _digest(value) for section, value in sections.items()}

    # The expandable sub-rows of products, and the nodes of the grouped tree.
    f = board.BoardFilter(date_from=TODAY - timedelta(days=29), date_to=TODAY, group_by="publication")
    sub: Dict[str, Any] = {}
    for item_id in (800001 + 7, 800001 + 42, 0):
        with board.Board(session, f, product_item_id=item_id, scope_pairs=None) as b:
            sub[str(item_id)] = [_row_json(r) for r in b.page(limit=None, apply_alerts=False)]
    _dump("sub_rows", "rows", sub)
    out["sub_rows"] = {"rows": _digest(sub)}

    g = replace(f, group_by="group", dimension="marca")
    with board.Board(session, g, scope=("Samsung",), scope_pairs=None) as b:
        node = [_row_json(r) for r in b.group_page(None, 0)]
    with board.Board(session, g, scope_pairs=None, through_leaves=True) as b:
        leaves = [_row_json(r) for r in b.group_page(None, 0)]
    _dump("group_nodes", "rows", [node, leaves])
    out["group_nodes"] = {"rows": _digest([node, leaves])}
    return out


def _row_json(row: Any) -> Dict[str, Any]:
    data = _without_null_tp(dict(row.__dict__))
    data["flags"] = sorted(data.get("flags") or ())
    return data


@pytest.mark.postgres
def test_board_responses_are_unchanged(world) -> None:
    actual = _compute(world)
    if os.environ.get("BOARD_GOLDEN_WRITE"):
        GOLDEN.write_text(json.dumps(actual, indent=1, sort_keys=True) + "\n")
    expected = json.loads(GOLDEN.read_text())

    assert sorted(actual) == sorted(expected)
    changed = {
        f"{name}.{section}": (expected[name].get(section), digest)
        for name, sections in actual.items()
        for section, digest in sections.items()
        if expected[name].get(section) != digest
    }
    assert not changed, f"board output changed (scenario.section -> (golden, actual)): {changed}"


@pytest.mark.postgres
def test_the_scenarios_are_not_vacuous(world) -> None:
    """The pinned responses must actually hold data, or the digests would pin
    an empty board."""
    full = _board_response(world, "product_default", SCENARIOS["product_default"])
    assert full["meta"]["total"] > 50 and full["rows"] and full["meta"]["with_sales_count"] > 0
    assert full["facets"]["stores"] and full["facets"]["pub_status"]
    store = _board_response(world, "store", SCENARIOS["store"])
    assert 0 < store["meta"]["total"] < full["meta"]["total"]
    assert _board_response(world, "search_no_match", SCENARIOS["search_no_match"])["rows"] == []
    assert _board_response(world, "mla_source_empty", SCENARIOS["mla_source_empty"])["rows"] == []
    assert _board_response(world, "scope_empty", SCENARIOS["scope_empty"])["rows"] == []
    assert _board_response(world, "mla_source", SCENARIOS["mla_source"])["rows"]
    assert _board_response(world, "everything_at_once", SCENARIOS["everything_at_once"])["rows"]
