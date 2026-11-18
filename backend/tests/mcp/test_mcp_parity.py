"""Parity of the MCP tools with the app (L6): one source of truth, drift fails here.

1. Every GET endpoint under the Publicaciones ML / Métricas ML / promos prefixes is a tool, a companion of a
   tool, or excluded with a reason (an endpoint added to those screens must be exposed or justified).
2. Each tool's arguments are exactly its endpoint's path + query parameters (a new filter shows up as a new
   argument; a tool never hides one).
3. Each tool returns every top-level field of its endpoint's response model (only product costs are dropped,
   for users without productos.ver_costos).
"""

from __future__ import annotations

import asyncio
import json

import pytest

from app.main import app
from app.mcp import loopback, tools

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
    assert set(built.input_schema["properties"]) == params
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
        pytest.skip("endpoint has no declared object response model")
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
