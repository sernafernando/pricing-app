"""`promos_publicaciones` (L5/L8/L9): per publication of a filtered Publicaciones ML page, the promo ML applies now,
the Sugeridas per type, the best of them and how much it improves the markup.

Built only on the app's own endpoints, read as the user (same gates: the items view's and promos.ver):
- `/api/ml-publications/view/items` for the set (every filter of the screen, paginated and capped),
- `/api/promociones/item/{mla}` for each row's promos with `nuestro_markup` / `markup_sell_in_out`,
- `/api/promociones/item/{mla}/markup` for the plain-sale markup when no promo applies (as the panel does),
- `/api/usuarios/pms` to resolve `pm` by name.
The pick itself is app.mcp.promo_pick (the panel's rule, ported with shared test cases).
"""

from __future__ import annotations

import unicodedata
from datetime import UTC, datetime
from typing import Any

import anyio

from app.mcp import promo_pick
from app.mcp.tools import BuiltTool, ToolCallError, ToolSpec, _get, _path_value

ITEMS_PATH = "/api/ml-publications/view/items"
# Per-row reads in flight at once: a page of 50 must not run 100 requests one after another, nor all at once.
ROW_CONCURRENCY = 6
PMS_PATH = "/api/usuarios/pms"


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower().strip()


def match_pms(query: str, pms: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """PMs whose name words (or email user) start with every word of `query`, accents and case ignored. A full-name
    match wins over prefix matches."""
    wanted = _normalize(query).split()
    if not wanted:
        return []
    exact = [pm for pm in pms if _normalize(pm.get("nombre", "")) == " ".join(wanted)]
    if exact:
        return exact
    found = []
    for pm in pms:
        words = _normalize(pm.get("nombre", "")).split() + [_normalize((pm.get("email") or "").split("@")[0])]
        if all(any(word.startswith(part) for word in words if word) for part in wanted):
            found.append(pm)
    return found


async def _resolve_pm(query: str, username: str) -> dict[str, Any]:
    pms = await _get(PMS_PATH, {"solo_con_marcas": True}, username) or []
    found = match_pms(query, pms)
    if not found:
        names = ", ".join(pm["nombre"] for pm in pms[:30])
        raise ToolCallError(f"No hay un PM que coincida con '{query}'. PMs: {names}")
    return {"found": found}


def _promo_summary(promo: dict[str, Any] | None, *, with_markups: bool = True) -> dict[str, Any] | None:
    if not promo:
        return None
    summary: dict[str, Any] = {
        "promotion_id": promo.get("promotion_id"),
        "name": promo_pick.promo_name(promo),
        "type": promo.get("promotion_type"),
    }
    if with_markups:
        summary["price"] = promo_pick.promo_display_price(promo)
        summary["markup"] = promo.get("nuestro_markup")
        summary["markup_sell_in_out"] = promo.get("markup_sell_in_out")
    return summary


async def _row(item: dict[str, Any], username: str, now: datetime) -> dict[str, Any]:
    item_id = str(item.get("item_id"))
    price = (item.get("price") or {}).get("amount")
    link = item.get("link") or {}
    row: dict[str, Any] = {
        "item_id": item_id,
        "title": item.get("title"),
        "seller_sku": item.get("seller_sku"),
        "product": link.get("codigo"),
        "brand": link.get("marca"),
        "sale_price": price,
    }
    base = f"/api/promociones/item/{_path_value('item_id', item_id)}"
    data = await _get(base, {}, username) or {}
    promotions = data.get("promotions") or []

    applied = promo_pick.baseline_promo(promotions)
    if applied is not None:
        current = {
            "promo": _promo_summary(applied, with_markups=False),
            "price": promo_pick.promo_display_price(applied),
            "markup": applied.get("nuestro_markup"),
            "markup_sell_in_out": applied.get("markup_sell_in_out"),
        }
    else:
        plain: dict[str, Any] = {}
        if promo_pick.finite_or_none(price) is not None and price > 0:
            plain = await _get(f"{base}/markup", {"price": price}, username) or {}
        current = {
            "promo": None,
            "price": price,
            "markup": plain.get("nuestro_markup"),
            "markup_sell_in_out": plain.get("markup_sell_in_out"),
        }
    row["current"] = current

    if promo_pick.finite_or_none(current["markup"]) is None or current["price"] is None:
        row.update(suggested={}, best=None, improvement=None)
        row["note"] = "Sin markup actual (falta costo, lista o precio): no se puede comparar."
        return row

    slots = promo_pick.pick_mejores_candidatas(
        promotions,
        baseline_price=current["price"],
        baseline_markup=current["markup"],
        baseline_sell_in_out=current["markup_sell_in_out"],
        now=now,
    )
    best = promo_pick.best_suggestion(slots)
    row["suggested"] = {kind: _promo_summary(promo) for kind, promo in slots.items() if promo}
    row["best"] = _promo_summary(best)
    status_quo = {"nuestro_markup": current["markup"], "markup_sell_in_out": current["markup_sell_in_out"]}
    row["improvement"] = promo_pick.improvement(best, status_quo)
    if best is None:
        row["note"] = "Ninguna candidata aplicable hoy mejora la situación actual."
    return row


async def _rows(items: list[dict[str, Any]], username: str, now: datetime) -> list[dict[str, Any]]:
    """Every row, in page order, at most ROW_CONCURRENCY reads at a time; the first failure (in order) wins."""
    results: list[dict[str, Any] | BaseException | None] = [None] * len(items)
    limiter = anyio.CapacityLimiter(ROW_CONCURRENCY)

    async def one(index: int, item: dict[str, Any]) -> None:
        async with limiter:
            try:
                results[index] = await _row(item, username, now)
            except ToolCallError as exc:
                results[index] = exc

    async with anyio.create_task_group() as group:
        for index, item in enumerate(items):
            group.start_soon(one, index, item)
    for result in results:
        if isinstance(result, BaseException):
            raise result
    return [r for r in results if isinstance(r, dict)]


async def run(tool: BuiltTool, args: dict[str, Any], username: str) -> Any:
    query = {k: v for k, v in args.items() if k in tool.query_params}
    pm_info = None
    if args.get("pm"):
        if args.get("pms") or args.get("pm_grupo"):
            raise ToolCallError("Usá `pm` (nombre) o `pms`/`pm_grupo` (ids), no los dos.")
        found = (await _resolve_pm(args["pm"], username))["found"]
        if len(found) > 1:
            listed = ", ".join(f"{pm['nombre']} (id {pm['id']})" for pm in found)
            return {
                "needs_choice": "pm",
                "message": f"'{args['pm']}' coincide con varios PMs: {listed}. Preguntá cuál y repetí con pms=<id>.",
                "candidates": [{"id": pm["id"], "nombre": pm["nombre"]} for pm in found],
            }
        pm_info = {"id": found[0]["id"], "nombre": found[0]["nombre"]}
        query["pms"] = str(pm_info["id"])

    page = await _get(ITEMS_PATH, query, username) or {}
    now = datetime.now(UTC)
    rows = await _rows(page.get("items") or [], username, now)
    result: dict[str, Any] = {
        "total": page.get("total"),
        "limit": page.get("limit", query.get("limit")),
        "offset": page.get("offset", query.get("offset")),
        "rows": rows,
        "rule": (
            "current = promo ML applies now (else the sale price and its markup); suggested = per type, the "
            "candidates applicable today that beat it (Sugerida of the panel); best = the suggestion with the "
            "highest markup c/ SO (with sell out; the sell in is inside the cost); improvement = best minus current, "
            "in points and % of current."
        ),
    }
    if pm_info:
        result["pm"] = pm_info
    return result


SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(
        "promos_publicaciones",
        ITEMS_PATH,
        "Promos por publicación (actual, sugeridas, mejor)",
        "Table of publications with their current promo, the Sugeridas per type, the best one (highest markup with "
        "sell in / sell out) with sale price, markups and improvement in points and %. Takes every filter of "
        "`pubml_items`; `pm` resolves a product manager by name (ambiguous names return the candidates to ask).",
        extra_properties={
            "pm": {
                "type": "string",
                "minLength": 2,
                "maxLength": 80,
                "description": "Product manager name or part of it (e.g. 'eli'); alternative to `pms`.",
            }
        },
        runner=run,
    ),
)
