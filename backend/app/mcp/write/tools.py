"""MCP write tools (delivery 2). Listed and callable only with a `pricing.write` token.

Every write tool is two calls: `modo: "plan"` (what would change, row by row, plus a single-use `confirm_token`)
and `modo: "aplicar"` with that `plan_id` + `confirm_token`. Each order carries its reason (`motivo`) and its own
limits (`limites`) set by the person; the server adds the fixed ±10% per price change, the minimum markup and the
C1 band. Every applied row is audited and can be undone (`accion_deshacer`, or "Acciones IA" in the app).
"""

from __future__ import annotations

import copy
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from jsonschema import Draft202012Validator
from mcp.types import ToolAnnotations

from app.mcp import promo_pick, promos_bulk, tools
from app.mcp.write import families, guards, service
from app.mcp.write.context import WriteContext, WriteError, in_db

MAX_ITEMS = 50

_LIMITES = {
    "type": "object",
    "description": (
        "Límites de ESTA orden, dichos por la persona (nunca inventados): max_items (siempre), max_cambio_pct "
        "(precios, 0 < x <= 10), min_markup_pct (precios y promos), opcionales max_baja_pct / max_suba_pct. Sin "
        "ellos la herramienta responde faltan_limites."
    ),
    "properties": {
        "max_items": {"type": "integer", "minimum": 1},
        "max_cambio_pct": {"type": "number"},
        "min_markup_pct": {"type": "number"},
        "max_baja_pct": {"type": "number", "minimum": 0},
        "max_suba_pct": {"type": "number", "minimum": 0},
    },
    "additionalProperties": False,
}

WRITE_PROPERTIES: dict[str, Any] = {
    "modo": {
        "type": "string",
        "enum": ["plan", "aplicar"],
        "description": "plan: muestra qué cambiaría y devuelve plan_id + confirm_token. aplicar: ejecuta ese plan.",
    },
    "plan_id": {"type": "string", "maxLength": 40, "description": "modo aplicar: el plan_id del plan."},
    "confirm_token": {
        "type": "string",
        "maxLength": 100,
        "description": "modo aplicar: el confirm_token del plan (un solo uso, 15 minutos).",
    },
    "motivo": {
        "type": "string",
        "maxLength": 500,
        "description": "modo plan: por qué se hace el cambio (obligatorio).",
    },
    "limites": _LIMITES,
}

_MLA = {"type": "string", "pattern": r"^MLA\d+$"}
_PRECIO = {"type": "number", "exclusiveMinimum": 0}
_LISTA = {"type": "string", "enum": ["web", "pvp"], "default": "web", "description": "Lista: web (ML) o pvp."}


def _items(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "array",
        "minItems": 1,
        "maxItems": MAX_ITEMS,
        "items": {"type": "object", "properties": properties, "required": required, "additionalProperties": False},
    }


def _destructive(destructive: bool) -> ToolAnnotations:
    return ToolAnnotations(readOnlyHint=False, destructiveHint=destructive, idempotentHint=True, openWorldHint=True)


READ_AUDIT = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)

Planner = Callable[[WriteContext, dict[str, Any], tools.BuiltTool], Awaitable[list[dict[str, Any]]]]


@dataclass(frozen=True)
class WriteToolSpec:
    name: str
    title: str
    description: str
    kind: str
    annotations: ToolAnnotations
    properties: dict[str, Any] = field(default_factory=dict)
    planner: Planner | None = None
    # Tools that take the Publicaciones ML filters: their schema is derived from that endpoint (like the read tool).
    filters_path: str | None = None


# ---------------------------------------------------------------- planners


async def _plan_promo_aplicar(ctx: WriteContext, args: dict[str, Any], tool: tools.BuiltTool) -> list[dict[str, Any]]:
    return [await families.plan_promo_aplicar(ctx, item) for item in args["items"]]


async def _plan_promo_quitar(ctx: WriteContext, args: dict[str, Any], tool: tools.BuiltTool) -> list[dict[str, Any]]:
    return [await families.plan_promo_quitar(ctx, item) for item in args["items"]]


async def _plan_mejoras(ctx: WriteContext, args: dict[str, Any], tool: tools.BuiltTool) -> list[dict[str, Any]]:
    """`promos_publicaciones` with the same filters, then one enroll per row whose best promo improves the current
    markup by at least `min_mejora_pct` (improvement.percent of that tool)."""
    if tool.paging == "offset":
        args = {"limit": tools.DEFAULT_PAGE, "offset": 0, **args}
    table = await promos_bulk.run(tool, args, ctx.username)
    if table.get("needs_choice"):
        raise WriteError("elegir_pm", table["message"])
    rows = []
    for item in table.get("rows") or []:
        best, improvement = item.get("best"), item.get("improvement") or {}
        percent = promo_pick.finite_or_none(improvement.get("percent"))
        if not best or percent is None or percent < args["min_mejora_pct"]:
            continue
        wanted = {"mla": item["item_id"], "promotion_id": best["promotion_id"], "promotion_type": best["type"]}
        if best["type"] not in families.SMART_LIKE:
            wanted["deal_price"] = best.get("price")
        row = await families.plan_promo_aplicar(ctx, wanted)
        row["mejora"] = improvement
        rows.append(row)
    if not rows:
        raise WriteError("sin_filas", f"ninguna publicación de esta página mejora {args['min_mejora_pct']:g}% o más")
    return rows


async def _plan_estado(ctx: WriteContext, args: dict[str, Any], tool: tools.BuiltTool) -> list[dict[str, Any]]:
    return await families.plan_estado(ctx, list(dict.fromkeys(args["item_ids"])), args["status"])


async def _plan_precio_lista(ctx: WriteContext, args: dict[str, Any], tool: tools.BuiltTool) -> list[dict[str, Any]]:
    lista = args.get("lista_tipo", "web")
    return [await families.plan_precio_lista(ctx, item, lista) for item in args["items"]]


async def _plan_markup(ctx: WriteContext, args: dict[str, Any], tool: tools.BuiltTool) -> list[dict[str, Any]]:
    markup = float(args["markup_objetivo"])
    return [await families.plan_markup_masivo(ctx, int(i), markup) for i in dict.fromkeys(args["item_ids"])]


async def _plan_cuotas(ctx: WriteContext, args: dict[str, Any], tool: tools.BuiltTool) -> list[dict[str, Any]]:
    lista = args.get("lista_tipo", "web")
    return [await families.plan_precio_cuota(ctx, item, lista) for item in args["items"]]


async def _plan_mayorista(ctx: WriteContext, args: dict[str, Any], tool: tools.BuiltTool) -> list[dict[str, Any]]:
    return [await families.plan_mayorista(ctx, args["mla"], args["tramos"])]


# ---------------------------------------------------------------- catalog

SPECS: tuple[WriteToolSpec, ...] = (
    WriteToolSpec(
        "promo_aplicar",
        "Aplicar promos",
        "Inscribe publicaciones en promos de ML (SMART, PRE_NEGOTIATED, PRICE_MATCHING al precio de ML; "
        "SELLER_CAMPAIGN / DEAL con deal_price o el sugerido). Primero modo plan, después aplicar con el token.",
        guards.KIND_PROMO,
        _destructive(False),
        {
            "items": _items(
                {
                    "mla": _MLA,
                    "promotion_id": {"type": "string", "minLength": 1, "maxLength": 100},
                    "promotion_type": {"type": "string", "minLength": 1, "maxLength": 40},
                    "deal_price": _PRECIO,
                },
                ["mla", "promotion_id", "promotion_type"],
            )
        },
        _plan_promo_aplicar,
    ),
    WriteToolSpec(
        "promo_quitar",
        "Quitar promos",
        "Saca publicaciones de una promo aplicada. Primero modo plan, después aplicar con el token.",
        guards.KIND_PROMO,
        _destructive(True),
        {
            "items": _items(
                {
                    "mla": _MLA,
                    "promotion_id": {"type": "string", "minLength": 1, "maxLength": 100},
                    "promotion_type": {"type": "string", "minLength": 1, "maxLength": 40},
                },
                ["mla", "promotion_id", "promotion_type"],
            )
        },
        _plan_promo_quitar,
    ),
    WriteToolSpec(
        "promos_aplicar_mejoras",
        "Aplicar las promos que mejoran x%",
        '"Aplicá todas las que mejoran x%": toma los mismos filtros que promos_publicaciones (una página: limit / '
        "offset) y planea inscribir la mejor promo de cada publicación cuya mejora (improvement.percent, % sobre el "
        "markup actual) sea >= min_mejora_pct. Primero modo plan, después aplicar con el token.",
        guards.KIND_PROMO,
        _destructive(False),
        {
            "min_mejora_pct": {
                "type": "number",
                "minimum": 0,
                "description": "modo plan: mejora mínima (% sobre el markup actual) para incluir la publicación.",
            }
        },
        _plan_mejoras,
        filters_path=promos_bulk.ITEMS_PATH,
    ),
    WriteToolSpec(
        "publicaciones_estado",
        "Pausar o activar publicaciones",
        "Pausa (paused) o activa (active) publicaciones de ML. Primero modo plan, después aplicar con el token.",
        guards.KIND_ESTADO,
        _destructive(True),
        {
            "status": {"type": "string", "enum": ["paused", "active"]},
            "item_ids": {"type": "array", "minItems": 1, "maxItems": MAX_ITEMS, "items": _MLA},
        },
        _plan_estado,
    ),
    WriteToolSpec(
        "precio_lista_cambiar",
        "Cambiar precio de lista",
        "Cambia el precio de lista (clásica, web o pvp) de productos; las cuotas se recalculan como en la app. "
        "Máximo ±10% por cambio. Primero modo plan, después aplicar con el token.",
        guards.KIND_PRECIO,
        _destructive(True),
        {
            "items": _items({"item_id": {"type": "integer", "minimum": 1}, "precio": _PRECIO}, ["item_id", "precio"]),
            "lista_tipo": _LISTA,
        },
        _plan_precio_lista,
    ),
    WriteToolSpec(
        "precios_markup_masivo",
        "Precio de lista por markup (masivo)",
        "Lleva el precio de lista ML Clásica de hasta 100 productos al markup objetivo (mismo cálculo que la acción "
        "masiva de la app). Filas que muevan el precio más de ±10% quedan bloqueadas. Primero plan, después aplicar.",
        guards.KIND_PRECIO,
        _destructive(True),
        {
            "item_ids": {"type": "array", "minItems": 1, "maxItems": 100, "items": {"type": "integer", "minimum": 1}},
            "markup_objetivo": {"type": "number", "minimum": -100},
        },
        _plan_markup,
    ),
    WriteToolSpec(
        "precio_cuotas_cambiar",
        "Cambiar precio de cuotas",
        "Cambia el precio de una cuota (3, 6, 9, 12) de productos, web o pvp. Máximo ±10% por cambio. Primero modo "
        "plan, después aplicar con el token.",
        guards.KIND_PRECIO,
        _destructive(True),
        {
            "items": _items(
                {
                    "item_id": {"type": "integer", "minimum": 1},
                    "tipo_cuota": {"type": "string", "enum": ["3", "6", "9", "12"]},
                    "precio": _PRECIO,
                },
                ["item_id", "tipo_cuota", "precio"],
            ),
            "lista_tipo": _LISTA,
        },
        _plan_cuotas,
    ),
    WriteToolSpec(
        "precio_mayorista_cambiar",
        "Cambiar precios mayoristas (PxQ)",
        "Cambia el precio unitario de tramos EXISTENTES (por cantidad mínima) de una publicación y los publica en ML. "
        "Máximo ±10% por tramo. Primero modo plan, después aplicar con el token.",
        guards.KIND_PRECIO,
        _destructive(True),
        {
            "mla": _MLA,
            "tramos": {
                "type": "array",
                "minItems": 1,
                "maxItems": 20,
                "items": {
                    "type": "object",
                    "properties": {"cantidad_minima": {"type": "integer", "minimum": 1}, "precio_unitario": _PRECIO},
                    "required": ["cantidad_minima", "precio_unitario"],
                    "additionalProperties": False,
                },
            },
        },
        _plan_mayorista,
    ),
    WriteToolSpec(
        "acciones_recientes",
        "Acciones IA recientes",
        "Tus últimas acciones de escritura (lo que cambió, antes/después, resultado, si se deshizo), más nuevas "
        "primero. Sirve para elegir qué deshacer.",
        "lectura",
        READ_AUDIT,
        {
            "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 20},
            "offset": {"type": "integer", "minimum": 0, "default": 0},
            "plan_id": {"type": "string", "maxLength": 40},
            "tool": {"type": "string", "maxLength": 64},
            "resultado": {"type": "string", "enum": list(families.RESULTADOS)},
        },
    ),
    WriteToolSpec(
        "accion_deshacer",
        "Deshacer acciones",
        "Deshace acciones tuyas (accion_ids) o un plan entero (deshacer_plan_id): vuelve al valor de antes si nada "
        "cambió desde la acción. Mismo flujo: modo plan (con motivo), después aplicar con el token.",
        "deshacer",
        _destructive(True),
        {
            "accion_ids": {"type": "array", "minItems": 1, "maxItems": 100, "items": {"type": "integer", "minimum": 1}},
            "deshacer_plan_id": {
                "type": "string",
                "maxLength": 40,
                "description": "Deshacer todas las filas de ese plan.",
            },
        },
    ),
)

SPECS_BY_NAME = {spec.name: spec for spec in SPECS}
NAMES = frozenset(SPECS_BY_NAME)
ANNOTATIONS = {spec.name: spec.annotations for spec in SPECS}


def _built(spec: WriteToolSpec, openapi: dict[str, Any]) -> tools.BuiltTool:
    extra = copy.deepcopy(spec.properties)
    if spec.name not in ("acciones_recientes",):
        extra.update(copy.deepcopy(WRITE_PROPERTIES))
        if spec.name == "accion_deshacer":
            extra.pop("limites")
    tool_spec = tools.ToolSpec(spec.name, spec.filters_path or "", spec.title, spec.description, extra_properties=extra)
    if spec.filters_path:
        built = tools.build_tool(openapi, tool_spec)
        built.input_schema["required"] = ["modo"]
        built.validator = Draft202012Validator(built.input_schema)
        return built
    schema: dict[str, Any] = {"type": "object", "properties": extra, "additionalProperties": False}
    if spec.name != "acciones_recientes":
        schema["required"] = ["modo"]
    return tools.BuiltTool(
        spec=tool_spec,
        input_schema=schema,
        path_params=(),
        query_params=(),
        paging=None,
        companion_params={},
        validator=Draft202012Validator(schema),
    )


def build_catalog(openapi: dict[str, Any]) -> dict[str, tools.BuiltTool]:
    return {spec.name: _built(spec, openapi) for spec in SPECS}


# ---------------------------------------------------------------- execution


def _validate(tool: tools.BuiltTool, arguments: dict[str, Any]) -> dict[str, Any]:
    arguments = {key: value for key, value in arguments.items() if value is not None}  # null = not sent
    errors = sorted(tool.validator.iter_errors(arguments), key=lambda e: list(e.path))
    if errors:
        detail = "; ".join((".".join(str(p) for p in e.path) + ": " if e.path else "") + e.message for e in errors[:5])
        raise WriteError("argumentos_invalidos", detail)
    return dict(arguments)


def _missing(args: dict[str, Any], spec: WriteToolSpec) -> list[str]:
    if spec.name == "accion_deshacer":
        return [] if args.get("accion_ids") or args.get("deshacer_plan_id") else ["accion_ids o deshacer_plan_id"]
    if spec.filters_path:
        return [] if args.get("min_mejora_pct") is not None else ["min_mejora_pct"]
    return [key for key in spec.properties if key not in ("lista_tipo", "deal_price") and args.get(key) is None]


def _with_next_step(plan: dict[str, Any]) -> dict[str, Any]:
    if plan.get("plan_id"):
        plan["siguiente_paso"] = (
            "Mostrale a la persona las filas (antes, después, bloqueadas y por qué). Solo si confirma, llamá a la "
            "misma herramienta con modo 'aplicar', plan_id y confirm_token."
        )
    return plan


def _recent(db: Any, ctx: WriteContext, args: dict[str, Any]) -> dict[str, Any]:
    service.check_reader(db, ctx)
    return service.list_actions(
        db,
        usuario_id=ctx.usuario_id,
        tool=args.get("tool"),
        resultado=args.get("resultado"),
        plan_id=args.get("plan_id"),
        limit=args.get("limit", 20),
        offset=args.get("offset", 0),
    )


async def run(tool: tools.BuiltTool, arguments: dict[str, Any], ctx: WriteContext) -> Any:
    """Run one write tool; WriteError is the caller's to show (code + message)."""
    spec = SPECS_BY_NAME[tool.spec.name]
    args = _validate(tool, arguments)
    if spec.name == "acciones_recientes":
        return await in_db(_recent, ctx, args)
    if args["modo"] == "aplicar":
        try:
            return await service.apply_plan(ctx, spec.name, args.get("plan_id"), args.get("confirm_token"))
        except WriteError as exc:
            if exc.code == "ya_aplicado" and exc.result is not None:
                return {**exc.result, "aviso": "Este plan ya se había aplicado: no se escribió nada nuevo."}
            raise
    if spec.name == "accion_deshacer":
        plan = await service.plan_undo(
            ctx, args.get("motivo"), args.get("accion_ids"), args.get("deshacer_plan_id"), own_only=True
        )
        return _with_next_step(plan)
    planner = spec.planner
    assert planner is not None

    async def build_rows() -> list[dict[str, Any]]:
        missing = _missing(args, spec)
        if missing:
            raise WriteError("argumentos_invalidos", f"modo plan necesita: {', '.join(missing)}")
        return await planner(ctx, args, tool)

    plan = await service.plan_order(ctx, spec.name, spec.kind, args.get("motivo"), args.get("limites"), build_rows)
    return _with_next_step(plan)
