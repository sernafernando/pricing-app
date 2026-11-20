"""Parity of the MCP tools with the app (L6): one source of truth, drift fails here.

1. Every GET endpoint under the Publicaciones ML / Métricas ML / promos prefixes is a tool, a companion of a
   tool, or excluded with a reason (an endpoint added to those screens must be exposed or justified).
2. Each tool's arguments are exactly its endpoint's path + query parameters (a new filter shows up as a new
   argument; a tool never hides one).
3. Each tool returns every top-level field of its endpoint's response model (only product costs are dropped,
   for users without productos.ver_costos). Endpoints without an object model (and `ventas_ml`, merged with its
   KPIs) are compared key by key, at every depth, on seeded data in test_mcp_parity_seeded.py.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from app.main import app
from app.mcp import loopback, tools, ui_filters

OPENAPI = app.openapi()
SAMPLE_PATH_VALUES = {"item_id": "MLA1", "mla_id": "MLA1"}


def _get_paths() -> set[str]:
    return {path for path, ops in OPENAPI["paths"].items() if "get" in ops}


def test_every_screen_endpoint_is_a_tool_or_excluded_with_a_reason():
    exposed = {spec.path for spec in tools.CATALOG} | {
        path for spec in tools.CATALOG for path in spec.companions.values()
    }
    screen = {p for p in _get_paths() if p.startswith(tools.PARITY_PREFIXES)}
    missing = sorted(screen - exposed - set(tools.EXCLUDED_ROUTES))
    assert missing == [], f"endpoints without an MCP tool (add one or exclude with a reason): {missing}"


def test_exclusions_and_tools_point_to_real_endpoints():
    paths = _get_paths()
    assert sorted(set(tools.EXCLUDED_ROUTES) - paths) == []
    assert sorted(spec.path for spec in tools.CATALOG if spec.path not in paths) == []
    assert all(reason.strip() for reason in tools.EXCLUDED_ROUTES.values())


@pytest.mark.parametrize("spec", tools.CATALOG, ids=lambda s: s.name)
def test_tool_arguments_are_exactly_the_endpoint_parameters(spec):
    params = {
        p["name"] for p in tools.operation(OPENAPI, spec.path).get("parameters", []) if p["in"] in ("path", "query")
    }
    built = tools.build_tool(OPENAPI, spec)
    assert set(built.input_schema["properties"]) == params | set(spec.extra_properties)
    assert built.input_schema["additionalProperties"] is False


def _response_fields(path: str) -> set[str]:
    schema = tools.operation(OPENAPI, path).get("responses", {}).get("200", {})
    schema = schema.get("content", {}).get("application/json", {}).get("schema", {})
    schema = tools._resolve(schema, OPENAPI.get("components", {}).get("schemas", {}))
    return set(schema.get("properties", {})) if schema.get("type") == "object" or "properties" in schema else set()


def _sample(prop: dict, name: str):
    """A value the schema accepts (enough to reach the endpoint call)."""
    for option in prop.get("anyOf", []):
        if option.get("type") != "null":
            return _sample(option, name)
    if prop.get("enum"):
        return prop["enum"][0]
    kind = prop.get("type")
    if kind == "integer" or kind == "number":
        return max(1, prop.get("minimum", 1))
    if kind == "boolean":
        return True
    if kind == "array":
        return [_sample(prop.get("items", {}), name)]
    if prop.get("format") == "date":
        return "2026-11-01"
    return SAMPLE_PATH_VALUES.get(name, "MLA1")


def _sample_arguments(built: tools.BuiltTool) -> dict:
    required = set(built.path_params) | set(built.input_schema.get("required", []))
    return {name: _sample(built.input_schema["properties"][name], name) for name in required}


@pytest.mark.parametrize("spec", [s for s in tools.CATALOG if not s.companions], ids=lambda s: s.name)
def test_tool_returns_every_response_field(spec, monkeypatch):
    fields = _response_fields(spec.path)
    if not fields:
        # No object model to read the fields from: covered field by field on seeded data instead.
        from tests.mcp.test_mcp_parity_seeded import UNTYPED

        assert spec.name in UNTYPED, "untyped endpoint without a seeded parity test (test_mcp_parity_seeded.py)"
        return
    payload = {field: 1 for field in fields}

    async def fake_send(path, params, headers):
        return 200, json.dumps(payload).encode()

    monkeypatch.setattr(loopback, "send_request", fake_send)
    built = tools.build_tool(OPENAPI, spec)
    result = asyncio.run(tools.run_tool(built, _sample_arguments(built), "someone", can_see_costs=True))
    assert set(result) >= fields


def test_publicaciones_ml_exposes_the_pm_filter():
    built = tools.build_tool(OPENAPI, next(s for s in tools.CATALOG if s.name == "pubml_items"))
    assert {"pms", "pm_grupo"} <= set(built.input_schema["properties"])


def test_promos_publicaciones_takes_every_publicaciones_filter_plus_pm_by_name():
    catalog = tools.build_catalog(OPENAPI)
    items = set(catalog["pubml_items"].input_schema["properties"])
    assert set(catalog["promos_publicaciones"].input_schema["properties"]) == items | {"pm"}


# ---------------------------------------------------------------- L10: every filter of every screen, by UI name

CATALOG_BUILT = tools.build_catalog(OPENAPI)


def test_every_tool_has_its_screen_filter_checklist():
    assert sorted(set(CATALOG_BUILT) ^ set(ui_filters.UI_FILTERS)) == []


@pytest.mark.parametrize("name", sorted(ui_filters.UI_FILTERS))
def test_every_screen_filter_is_an_argument_of_its_tool(name):
    arguments = set(CATALOG_BUILT[name].input_schema["properties"])
    listed = [param for _, param in ui_filters.UI_FILTERS[name].filters]
    assert sorted(set(listed) - arguments) == [], "screen filters the MCP does not take"
    assert len(listed) == len(set(listed)), "a filter listed twice"


@pytest.mark.parametrize("name", sorted(ui_filters.UI_FILTERS))
def test_every_argument_is_a_mapped_filter_or_a_justified_non_filter(name):
    entry = ui_filters.UI_FILTERS[name]
    arguments = set(CATALOG_BUILT[name].input_schema["properties"])
    mapped = {param for _, param in entry.filters} | set(entry.other) | set(ui_filters.NOT_FILTERS)
    assert sorted(arguments - mapped) == [], "endpoint filters missing from the UI checklist (map them)"
    assert all(reason.strip() for reason in entry.other.values())


@pytest.mark.parametrize("name", sorted(ui_filters.UI_FILTERS))
def test_tienda_is_on_every_tool_whose_screen_has_it(name):
    entry = ui_filters.UI_FILTERS[name]
    arguments = set(CATALOG_BUILT[name].input_schema["properties"])
    takes_store = bool(arguments & {"tiendas", "stores"})
    assert entry.has_tienda == takes_store
    if entry.has_tienda:
        assert any(label.startswith("Tienda") for label, _ in entry.filters)
        param = "tiendas" if "tiendas" in arguments else "stores"
        description = CATALOG_BUILT[name].input_schema["properties"][param].get("description", "")
        assert ("none" if param == "tiendas" else "sin_tienda") in description, "how to ask for Sin tienda"


def test_tienda_screens_named_by_the_owner_all_take_it():
    for name in (
        "pubml_items",
        "pubml_kpis",
        "pubml_groups",
        "pubml_products",
        "pubml_stock_audit",
        "metricas_board",
        "metricas_board_envios",
        "metricas_board_group_nodes",
        "metricas_board_publications",
        "ventas_ml",
        "promos_publicaciones",
    ):
        assert ui_filters.UI_FILTERS[name].has_tienda, name


def test_the_checklist_table_lists_every_filter():
    table = ui_filters.checklist_markdown(sorted(ui_filters.UI_FILTERS))
    rows = sum(max(1, len(entry.filters)) for entry in ui_filters.UI_FILTERS.values())
    assert table.count("✅") == rows


def _schema_fields(name: str) -> set[str]:
    return set(OPENAPI["components"]["schemas"][name]["properties"])


def test_the_markup_with_sell_in_out_reaches_the_publicaciones_ml_tools():
    """pubml-markup-siso S5: the tools return their endpoint's body as is, so the markup c/ SISO fields of every
    view are in the tools' answers exactly when the endpoints' schemas declare them (nested fields: the top-level
    check above does not see them), and the sort keys are in the `orden` arguments' descriptions."""
    catalog = {spec.name: spec.path for spec in tools.CATALOG}
    assert catalog["pubml_items"] == "/api/ml-publications/view/items"
    assert "markup_siso" in _schema_fields("ItemRowOut")
    assert {"min", "max", "worst", "pending", "applies"} == _schema_fields("SisoMarkupOut")
    assert "markup_sell_30d" in _schema_fields("MetricsOut")  # the Publicaciones and Producto rows' metrics
    assert {"markup_siso_min", "markup_siso_max"} <= _schema_fields("GroupNodeOut")
    assert "markup_siso" in _schema_fields("StockAuditRowOut") and "markup_siso" in _schema_fields(
        "StockAuditVariantOut"
    )
    orden = {
        name: built.input_schema["properties"]["orden"]["description"]
        for name, built in CATALOG_BUILT.items()
        if "orden" in built.input_schema["properties"]
    }
    assert "markup_siso" in orden["pubml_items"] and "markup_sell_30d" in orden["pubml_items"]
    assert "markup_sell_30d" in orden["pubml_products"]
    assert "markup_siso" in orden["pubml_stock_audit"]
