"""Read tools of the MCP server: one tool per backing GET endpoint, with full parity (L6).

Single source of truth: each tool's input schema is DERIVED from its endpoint's OpenAPI parameters (names,
types, enums, patterns, defaults, descriptions). A new filter on the endpoint is a new tool argument with no
change here; `tests/mcp/test_mcp_parity.py` fails when an endpoint under the parity prefixes is neither a tool
nor excluded with a reason, or when a tool hides a parameter or response field.

The tool returns the endpoint's JSON as is, with three documented exceptions: paging is capped (MAX_PAGE),
product costs are dropped without `productos.ver_costos` (L3 Q4) on the product tools, and oversized results
are cut with `truncated: true` plus how to fetch the rest.
"""

from __future__ import annotations

import copy
from collections.abc import Awaitable, Callable
import json
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any
from urllib.parse import quote, unquote

from jsonschema import Draft202012Validator

from app.mcp import loopback

MAX_PAGE = 50
DEFAULT_PAGE = 20
MAX_RESULT_BYTES = 200_000
MAX_STRING_CHARS = 4_000

# Every GET route under these prefixes must be a tool or be excluded below (parity test).
PARITY_PREFIXES = ("/api/ml-publications", "/api/ml-metricas", "/api/promociones")

EXCLUDED_ROUTES: dict[str, str] = {
    "/api/ml-publications/view/items/export": "xlsx file; same rows as pubml_items",
    "/api/ml-publications/view/products/export": "xlsx file; same rows as pubml_products",
    "/api/ml-publications/view/stock-audit/export": "xlsx file; same rows as pubml_stock_audit",
    "/api/ml-metricas/board/export": "xlsx file; same rows as metricas_board",
    "/api/ml-publications/view/product-ids": "SPA bulk-selection helper: ids only",
    "/api/ml-publications/view/status-item-ids": "SPA bulk-selection helper: ids only",
    "/api/ml-publications/view/hay-mejores-exclusion-item-ids": "SPA bulk-selection helper: ids only",
    "/api/ml-publications/view/hay-mejores-criterios-item-ids": "SPA bulk-selection helper: ids only",
    "/api/ml-publications/layouts/{vista}": "per-user UI layout/preset preferences, not pricing data",
    "/api/ml-publications/presets": "per-user UI layout/preset preferences, not pricing data",
}

_COST_KEY = re.compile(r"(^|_)costos?(_|$)")


@dataclass(frozen=True)
class ToolSpec:
    name: str
    path: str
    title: str
    description: str
    strip_costs: bool = False
    # Extra endpoints merged into the answer: {result key: path}; each gets the arguments it accepts.
    companions: dict[str, str] = field(default_factory=dict)
    main_key: str | None = None
    # Required dates the tool fills with the last 30 days when omitted: (from param, to param).
    default_period: tuple[str, str] | None = None
    # Composite tools: arguments on top of `path`'s and the coroutine that answers instead of a plain GET.
    extra_properties: dict[str, Any] = field(default_factory=dict)
    runner: Callable[[BuiltTool, dict[str, Any], str], Awaitable[Any]] | None = None


CATALOG: tuple[ToolSpec, ...] = (
    # Publicaciones ML: views, facets, KPIs
    ToolSpec(
        "pubml_items",
        "/api/ml-publications/view/items",
        "Publicaciones ML: publicaciones",
        "Publicaciones ML, vistas Publicaciones y Precios: one row per publication with every filter, sort and "
        "column of the screen (pms = product manager user ids, see `pms`).",
    ),
    ToolSpec(
        "pubml_products",
        "/api/ml-publications/view/products",
        "Publicaciones ML: productos",
        "Publicaciones ML, vista Producto: one row per product with its publications.",
    ),
    ToolSpec(
        "pubml_groups",
        "/api/ml-publications/view/groups",
        "Publicaciones ML: agrupado",
        "Publicaciones ML, vista Agrupado: rows grouped by a dimension.",
    ),
    ToolSpec(
        "pubml_stats",
        "/api/ml-publications/view/stats",
        "Publicaciones ML: conteos",
        "Facet counts of the Publicaciones ML filters for the current filter set.",
    ),
    ToolSpec(
        "pubml_kpis",
        "/api/ml-publications/view/kpis",
        "Publicaciones ML: KPIs",
        "KPI strip of Publicaciones ML for the current filter set.",
    ),
    ToolSpec(
        "pubml_stock_audit",
        "/api/ml-publications/view/stock-audit",
        "Auditoría de stock",
        "Publicaciones ML, vista Auditoría de stock: stock ERP and Full valued in USD and ARS, rows and KPIs; rows "
        "per brand, category or product (`nivel`, drill with `grupo_marca` / `grupo_categoria`), sales, coverage "
        "and rotation split into ERP and Full.",
    ),
    ToolSpec(
        "pubml_mejores_ofertas_count",
        "/api/ml-publications/view/mejores-ofertas/count",
        "Hay mejores ofertas: total",
        "How many publications have better promotions available.",
    ),
    ToolSpec(
        "pubml_mejores_ofertas_por_pm",
        "/api/ml-publications/view/mejores-ofertas/por-pm",
        "Hay mejores ofertas por PM",
        "Publications with better promotions available, per product manager.",
    ),
    # Publication panel tabs
    ToolSpec(
        "pubml_item",
        "/api/ml-publications/view/items/{item_id}",
        "Publicación: resumen",
        "Publication panel (Resumen, Datos, Full, Precios): every stored field, stock per location, Full.",
    ),
    ToolSpec(
        "pubml_item_variations",
        "/api/ml-publications/view/items/{item_id}/variations",
        "Publicación: variantes",
        "Variations of a publication.",
    ),
    ToolSpec(
        "pubml_item_events",
        "/api/ml-publications/view/items/{item_id}/events",
        "Publicación: eventos",
        "Publication panel, tab Eventos.",
    ),
    ToolSpec(
        "pubml_item_history",
        "/api/ml-publications/view/items/{item_id}/history",
        "Publicación: historial",
        "Publication panel, tab Historial.",
    ),
    ToolSpec(
        "pubml_product_envio",
        "/api/ml-publications/view/products/{item_id}/envio",
        "Producto: envío",
        "Shipping data of a product's publications.",
    ),
    ToolSpec(
        "pubml_item_product_links",
        "/api/ml-publications/items/{item_id}/product-links",
        "Publicación: producto vinculado",
        "Publication panel, tab Producto: the ERP product links.",
    ),
    ToolSpec(
        "pubml_product_links",
        "/api/ml-publications/product-links",
        "Vínculos publicación-producto",
        "Publication to ERP product links.",
    ),
    ToolSpec(
        "pubml_product_links_coverage",
        "/api/ml-publications/product-links/coverage",
        "Cobertura de vínculos",
        "Coverage of publication to product links.",
    ),
    ToolSpec(
        "pubml_status",
        "/api/ml-publications/status",
        "Estado de la sincronización",
        "Freshness of the Publicaciones ML data.",
    ),
    ToolSpec(
        "pubml_settings",
        "/api/ml-publications/settings",
        "Configuración de Publicaciones ML",
        "Settings of Publicaciones ML.",
    ),
    # Promos and competition tabs
    ToolSpec("promos_list", "/api/promociones", "Promociones", "Seller promotions."),
    ToolSpec(
        "promos_promotion_items",
        "/api/promociones/{promotion_id}/items",
        "Promoción: publicaciones",
        "Publications of one promotion.",
    ),
    ToolSpec(
        "promos_item",
        "/api/promociones/item/{mla_id}",
        "Publicación: promos",
        "Publication panel, tab Promos: applied and candidate promotions with prices, nuestro_markup and "
        "markup_sell_in_out. `promotion_types` / `promotion_names` apply the tab's filter.",
        extra_properties={
            "promotion_types": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 20,
                "description": "Promociones tab filter: keep only these promotion types (e.g. SMART, DEAL).",
            },
            "promotion_names": {
                "type": "object",
                "additionalProperties": {"type": "array", "items": {"type": "string"}, "maxItems": 50},
                "maxProperties": 20,
                "description": "Promociones tab filter: per promotion type, keep only these promotion names.",
            },
        },
        runner=lambda tool, args, username: _promos_item_filtered(tool, args, username),
    ),
    ToolSpec(
        "promos_item_markup",
        "/api/promociones/item/{mla_id}/markup",
        "Publicación: markup a un precio",
        "Markup (with sell in/out) of a publication at a given price.",
    ),
    ToolSpec(
        "promos_item_confirmacion_ml",
        "/api/promociones/item/{mla_id}/confirmacion-ml",
        "Publicación: confirmación de ML",
        "What Mercado Libre reports for the publication's promotions.",
    ),
    ToolSpec(
        "promos_item_hay_mejores_criterios",
        "/api/promociones/item/{mla_id}/hay-mejores-criterios",
        "Publicación: criterios hay mejores",
        "Per-publication application criteria for hay_mejores (C1 markup band, C2 catalog win, Auto).",
    ),
    ToolSpec(
        "catalogo_competencia",
        "/api/promociones/catalogo-competencia/{mla_id}",
        "Competencia de catálogo",
        "Publication panel, catalog competition.",
    ),
    # Product tab
    ToolSpec(
        "producto_detalle",
        "/api/productos/{item_id}/detalle",
        "Producto: detalle",
        "Product detail (sections according to the user's permissions).",
        strip_costs=True,
    ),
    ToolSpec(
        "productos_precios_listas",
        "/api/productos/precios-listas",
        "Productos: precios por lista",
        "Products with their prices in every ML price list.",
        strip_costs=True,
    ),
    # Métricas ML
    ToolSpec(
        "metricas_board",
        "/api/ml-metricas/board",
        "Métricas ML",
        "Métricas ML board: rows, KPI strip and series, canal ml|fuera|todo, costo costo_d|costo, period, "
        "compare, group, sort and every filter of the screen.",
    ),
    ToolSpec(
        "metricas_board_publications",
        "/api/ml-metricas/board/products/{product_item_id}/publications",
        "Métricas ML: publicaciones de un producto",
        "Métricas ML drill-down: a product's publications.",
    ),
    ToolSpec(
        "metricas_board_envios",
        "/api/ml-metricas/board/envios",
        "Métricas ML: por tipo de envío",
        "Métricas ML drill-down by shipping type.",
    ),
    ToolSpec(
        "metricas_board_group_nodes",
        "/api/ml-metricas/board/group-nodes",
        "Métricas ML: nodos de grupo",
        "Métricas ML grouped view nodes.",
    ),
    # Sales
    ToolSpec(
        "ventas_ml",
        "/api/ml-ventas-ops/sales",
        "Ventas ML",
        "ML sales with their KPIs.",
        companions={"kpis": "/api/ml-ventas-ops/sales/kpis"},
        main_key="ventas",
    ),
    ToolSpec("venta_ml", "/api/ml-ventas-ops/orders/{order_id}", "Venta ML", "One ML order."),
    ToolSpec(
        "ventas_por_fuera",
        "/api/ventas-fuera-pdf/operaciones",
        "Ventas por fuera",
        "Sales outside ML (GBP). Defaults to the last 30 days.",
        default_period=("desde", "hasta"),
    ),
    ToolSpec(
        "ventas_fuera_cargas",
        "/api/ventas-fuera-pdf/cargas",
        "Ventas por fuera: cargas de PDF",
        "Uploads of GBP sales reports (who, when, salespeople, figures, whether still in force), newest first.",
    ),
    # Publicaciones ML repair runs (admin)
    ToolSpec(
        "pubml_repair_runs",
        "/api/ml-publications/repair/runs",
        "Reparaciones: corridas",
        "Runs of the Publicaciones ML data repair.",
    ),
    ToolSpec(
        "pubml_repair_run", "/api/ml-publications/repair/runs/{run_id}", "Reparaciones: corrida", "One repair run."
    ),
    ToolSpec(
        "pubml_repair_events",
        "/api/ml-publications/repair/events",
        "Reparaciones: eventos",
        "Events of the Publicaciones ML data repair.",
    ),
    # Helpers
    ToolSpec(
        "pms",
        "/api/usuarios/pms",
        "Product managers",
        "Product managers (id, nombre) to resolve a PM by name for the `pms` filters. If a name matches "
        "several PMs, ask the user which one.",
    ),
)


class ToolCallError(Exception):
    """A tool failure shown to the model; `status` goes to the audit log (denied | error | limited)."""

    def __init__(self, message: str, status: str = "error") -> None:
        super().__init__(message)
        self.status = status


@dataclass
class BuiltTool:
    spec: ToolSpec
    input_schema: dict[str, Any]
    path_params: tuple[str, ...]
    query_params: tuple[str, ...]
    paging: str | None  # "offset" | "page" | None
    companion_params: dict[str, tuple[str, ...]]
    validator: Draft202012Validator


def _resolve(schema: Any, components: dict[str, Any]) -> Any:
    """Inline `$ref`s so each tool schema stands alone."""
    if isinstance(schema, dict):
        ref = schema.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
            return _resolve(copy.deepcopy(components[ref.rsplit("/", 1)[1]]), components)
        return {k: _resolve(v, components) for k, v in schema.items()}
    if isinstance(schema, list):
        return [_resolve(v, components) for v in schema]
    return schema


def operation(openapi: dict[str, Any], path: str) -> dict[str, Any]:
    op = openapi.get("paths", {}).get(path, {}).get("get")
    if op is None:
        raise KeyError(f"no GET {path} in the app")
    return op


def _parameters(openapi: dict[str, Any], path: str) -> list[dict[str, Any]]:
    components = openapi.get("components", {}).get("schemas", {})
    return [_resolve(p, components) for p in operation(openapi, path).get("parameters", [])]


def _cap(prop: dict[str, Any]) -> dict[str, Any]:
    prop = dict(prop)
    prop["maximum"] = min(prop.get("maximum", MAX_PAGE), MAX_PAGE)
    prop["default"] = min(prop.get("default", DEFAULT_PAGE), DEFAULT_PAGE)
    return prop


def build_tool(openapi: dict[str, Any], spec: ToolSpec) -> BuiltTool:
    properties: dict[str, Any] = {}
    required: list[str] = []
    path_params: list[str] = []
    query_params: list[str] = []
    for param in _parameters(openapi, spec.path):
        if param.get("in") not in ("path", "query"):
            continue
        name = param["name"]
        prop = dict(param.get("schema", {}))
        prop.pop("title", None)
        if param.get("description"):
            prop["description"] = param["description"]
        if name in ("limit", "page_size"):
            prop = _cap(prop)
        properties[name] = prop
        if param["in"] == "path":
            path_params.append(name)
            required.append(name)
        else:
            query_params.append(name)
            if param.get("required") and not (spec.default_period and name in spec.default_period):
                required.append(name)
    paging = "offset" if "limit" in query_params else "page" if "page_size" in query_params else None
    companion_params = {
        key: tuple(p["name"] for p in _parameters(openapi, path) if p.get("in") == "query")
        for key, path in spec.companions.items()
    }
    properties.update(copy.deepcopy(spec.extra_properties))
    schema: dict[str, Any] = {"type": "object", "properties": properties, "additionalProperties": False}
    if required:
        schema["required"] = required
    return BuiltTool(
        spec=spec,
        input_schema=schema,
        path_params=tuple(path_params),
        query_params=tuple(query_params),
        paging=paging,
        companion_params=companion_params,
        validator=Draft202012Validator(schema),
    )


def all_specs() -> tuple[ToolSpec, ...]:
    """The endpoint tools plus the composite ones (imported here: they build on this module)."""
    from app.mcp import promos_bulk

    return CATALOG + promos_bulk.SPECS


def build_catalog(openapi: dict[str, Any]) -> dict[str, BuiltTool]:
    return {spec.name: build_tool(openapi, spec) for spec in all_specs()}


# ---------------------------------------------------------------- execution


def _validate(tool: BuiltTool, arguments: dict[str, Any]) -> dict[str, Any]:
    errors = sorted(tool.validator.iter_errors(arguments), key=lambda e: list(e.path))
    if errors:
        detail = "; ".join((".".join(str(p) for p in e.path) + ": " if e.path else "") + e.message for e in errors[:5])
        raise ToolCallError(f"Argumentos inválidos: {detail}")
    args = dict(arguments)
    if tool.paging == "offset":
        args.setdefault("limit", DEFAULT_PAGE)
        args.setdefault("offset", 0)
    elif tool.paging == "page":
        args.setdefault("page", 1)
        args.setdefault("page_size", DEFAULT_PAGE)
    if tool.spec.default_period:
        start, end = tool.spec.default_period
        today = date.today()
        args.setdefault(end, today.isoformat())
        args.setdefault(start, (today - timedelta(days=29)).isoformat())
    return args


def _path_value(name: str, value: Any) -> str:
    """One path segment, never a way out of it: the app decodes `%2F` before routing, so separators and dot
    segments are refused (encoded or not) instead of being escaped."""
    text = str(value)
    decoded = unquote(unquote(text))
    if not decoded.strip() or decoded.strip() in (".", "..") or any(ch in decoded for ch in "/\\"):
        raise ToolCallError(f"Argumentos inválidos: {name} no es un identificador válido")
    return quote(text, safe="")


def _url(tool: BuiltTool, args: dict[str, Any]) -> str:
    path = tool.spec.path
    for name in tool.path_params:
        path = path.replace("{" + name + "}", _path_value(name, args[name]))
    return path


def _detail(body: bytes) -> str:
    try:
        data = json.loads(body)
    except ValueError:
        return ""
    if isinstance(data, dict):
        if isinstance(data.get("detail"), str):
            return data["detail"]
        error = data.get("error")
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            return error["message"]
        if data.get("detail") is not None:
            return json.dumps(data["detail"], ensure_ascii=False)[:500]
    return ""


async def _get(path: str, params: dict[str, Any], username: str) -> Any:
    status_code, body = await loopback.send_request(path, params, loopback.identity_headers(username))
    if status_code == 200:
        return json.loads(body) if body else None
    detail = _detail(body)
    if status_code in (401, 403):
        raise ToolCallError(f"Sin permiso: {detail or 'la app negó el acceso'}", status="denied")
    if status_code == 404:
        raise ToolCallError(f"No encontrado: {detail or path}")
    if status_code == 422:
        raise ToolCallError(f"Parámetros inválidos: {detail}")
    if status_code == 429:
        raise ToolCallError("Demasiadas consultas: esperá un minuto", status="limited")
    if status_code == 503:
        raise ToolCallError(f"No disponible: {detail}")
    raise ToolCallError(f"Error del servidor ({status_code})")


def matches_promo_filter(promo: dict[str, Any], types: list[str], names: dict[str, list[str]]) -> bool:
    """The Promociones tab filter (frontend `matchesPromoFilter`): type in the chosen ones (none = all) and, when
    names were chosen for that type, the promo's name among them."""
    if types and promo.get("promotion_type") not in types:
        return False
    chosen = names.get(promo.get("promotion_type") or "")
    if not chosen:
        return True
    payload = promo.get("payload")
    name = promo.get("name") or (payload.get("name") if isinstance(payload, dict) else None)
    return name in chosen


async def _promos_item_filtered(tool: BuiltTool, args: dict[str, Any], username: str) -> Any:
    result = await _get(_url(tool, args), {}, username)
    types, names = args.get("promotion_types") or [], args.get("promotion_names") or {}
    if (types or names) and isinstance(result, dict) and isinstance(result.get("promotions"), list):
        kept = [p for p in result["promotions"] if isinstance(p, dict) and matches_promo_filter(p, types, names)]
        result = {**result, "promotions": kept, "count": len(kept)}
    return result


def drop_costs(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: drop_costs(v) for k, v in value.items() if not _COST_KEY.search(str(k))}
    if isinstance(value, list):
        return [drop_costs(v) for v in value]
    return value


def _cut_strings(value: Any) -> Any:
    if isinstance(value, str) and len(value) > MAX_STRING_CHARS:
        return value[:MAX_STRING_CHARS] + f"… [recortado: {len(value)} caracteres]"
    if isinstance(value, dict):
        return {k: _cut_strings(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_cut_strings(v) for v in value]
    return value


def _size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, default=str).encode("utf-8"))


def fit(value: Any) -> Any:
    """Cut the biggest list until the answer fits MAX_RESULT_BYTES; say so and how to get the rest."""
    value = _cut_strings(value)
    if _size(value) <= MAX_RESULT_BYTES:
        return value
    container = value if isinstance(value, dict) else {"items": value}
    lists = [k for k, v in container.items() if isinstance(v, list) and v]
    if not lists:
        return {"truncated": True, "aviso": "Respuesta demasiado grande; pedí menos datos."}
    key = max(lists, key=lambda k: _size(container[k]))
    rows = container[key]
    lo, hi = 0, len(rows)
    while lo < hi:  # largest prefix that fits
        mid = (lo + hi + 1) // 2
        if _size({**container, key: rows[:mid]}) <= MAX_RESULT_BYTES - 300:
            lo = mid
        else:
            hi = mid - 1
    return {
        **container,
        key: rows[:lo],
        "truncated": True,
        "aviso": f"Se muestran {lo} de {len(rows)} filas de '{key}'. Pedí menos filas (limit/page_size) o "
        "seguí paginando con offset/page.",
    }


async def run_tool(tool: BuiltTool, arguments: dict[str, Any], username: str, can_see_costs: bool) -> Any:
    """Validate, call the backing endpoint(s) as the user, shape the answer."""
    args = _validate(tool, arguments)
    if tool.spec.runner is not None:
        return fit(await tool.spec.runner(tool, args, username))
    query = {k: v for k, v in args.items() if k in tool.query_params}
    result = await _get(_url(tool, args), query, username)
    if tool.spec.companions:
        merged = {tool.spec.main_key or "data": result}
        for key, path in tool.spec.companions.items():
            sub_query = {k: v for k, v in args.items() if k in tool.companion_params[key]}
            merged[key] = await _get(path, sub_query, username)
        result = merged
    if tool.spec.strip_costs and not can_see_costs:
        result = drop_costs(result)
    return fit(result)


def summarize_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    """What the audit log keeps: values cut to 200 chars, lists to 20 items."""
    summary: dict[str, Any] = {}
    for key, value in list(arguments.items())[:40]:
        if isinstance(value, list):
            value = value[:20]
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False, default=str)
        if isinstance(value, str):
            value = value[:200]
        summary[str(key)[:64]] = value
    return summary
