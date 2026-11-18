"""One entry per kind of change (`accion`): how a row is planned from the AI's arguments, how its live value is
re-checked right before writing (and before an undo), how it is applied through the real endpoint, and how it is
undone.

A row is a plain dict (stored in the plan as JSON):
    objetivo, objetivo_label, accion, antes, despues (flat scalars), estado (lista | bloqueada), detalle,
    cambios_pct (price changes, %), markup_previsto (%), datos (what `apply` sends; internal).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from app.mcp import promo_pick, tools
from app.mcp.write import guards, live
from app.mcp.write.context import WriteContext, in_db
from app.services.ml_promotions_pricing import precio_de_oferta

OK = "ok"
RECHAZADA = "rechazada"
BLOQUEADA = "bloqueada"
AMBIGUA = "ambigua"
ERROR = "error"
DENEGADA = "denegada"
RESULTADOS = (OK, RECHAZADA, BLOQUEADA, AMBIGUA, ERROR, DENEGADA)

# ML sets the offer price of these types: we send the price we saw (`precio_visto`) and the endpoint refuses if
# it moved. The others take our `deal_price`.
SMART_LIKE = {"SMART", "PRE_NEGOTIATED", "PRICE_MATCHING"}
APPLIED_STATUSES = ("started", "pending")

Outcome = tuple[str, str | None, dict[str, Any] | None]  # resultado, detalle, despues read back (or None)


def new_row(accion: str, objetivo: str, label: str | None = None) -> dict[str, Any]:
    return {
        "objetivo": str(objetivo)[:64],
        "objetivo_label": label[:255] if label else None,
        "accion": accion,
        "antes": {},
        "despues": {},
        "estado": guards.ESTADO_LISTA,
        "detalle": None,
        "cambios_pct": None,
        "markup_previsto": None,
        "datos": {},
    }


def same_money(a: Any, b: Any) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return round(float(a) * 100) == round(float(b) * 100)


def http_outcome(status: int, body: Any, ok_detail: str | None = None) -> Outcome:
    """Default mapping of an endpoint answer to a row result."""
    detail = live.body_detail(body)
    if status in (200, 201, 204):
        return OK, ok_detail, None
    if status == 202:
        return AMBIGUA, detail or "no se sabe si ML aplicó el cambio: se vuelve a consultar", None
    if status in (401, 403):
        return DENEGADA, detail or "la app negó el permiso", None
    if status in (400, 404, 409, 422):
        return RECHAZADA, detail or f"la app rechazó el cambio ({status})", None
    return ERROR, detail or f"error de la app ({status})", None


# ---------------------------------------------------------------- promos


def _find_promo(promos: list[dict[str, Any]], promotion_id: str, promotion_type: str) -> dict[str, Any] | None:
    for promo in promos:
        if str(promo.get("promotion_id")) == str(promotion_id) and promo.get("promotion_type") == promotion_type:
            return promo
    return None


def _offer_price(promo: dict[str, Any], promotion_type: str, deal_price: Any) -> float | None:
    if promotion_type in SMART_LIKE:
        return precio_de_oferta(promo)
    if deal_price is not None:
        return float(deal_price)
    return promo_pick.finite_or_none(promo.get("suggested_discounted_price")) or promo_pick.promo_display_price(promo)


async def plan_promo_aplicar(ctx: WriteContext, item: dict[str, Any]) -> dict[str, Any]:
    mla, pid, ptype = str(item["mla"]), str(item["promotion_id"]), str(item["promotion_type"])
    row = new_row("promo_aplicar", mla, mla)
    row["datos"] = {"mla": mla, "promotion_id": pid, "promotion_type": ptype}
    if ptype == "LIGHTNING":
        guards.block(row, "no_soportada: las ofertas relámpago (LIGHTNING) necesitan stock: aplicalas desde la app")
        return row
    if ptype in SMART_LIKE and item.get("deal_price") is not None:
        guards.block(row, f"deal_price: ML fija el precio de {ptype}; no se puede elegir")
        return row
    try:
        promos = await live.promos(ctx, mla)
    except tools.ToolCallError as exc:
        guards.block(row, f"lectura: {exc}")
        return row
    promo = _find_promo(promos, pid, ptype)
    if promo is None:
        guards.block(row, "promo_no_disponible: ML no ofrece esa promo para la publicación")
        return row
    row["objetivo_label"] = f"{mla} - {promo_pick.promo_name(promo) or pid}"[:255]
    if promo_pick._status_text(promo) != "candidate":
        guards.block(row, f"no_candidata: la promo está {promo_pick._status_text(promo)}, no como candidata")
        return row
    precio = _offer_price(promo, ptype, item.get("deal_price"))
    if precio is None or precio <= 0:
        guards.block(row, "sin_precio: no se pudo resolver el precio de la promo")
        return row
    current = promo_pick.baseline_promo(promos)
    row["antes"] = {
        "promotion_id": current.get("promotion_id") if current else None,
        "promotion_type": current.get("promotion_type") if current else None,
        "precio": promo_pick.promo_display_price(current) if current else None,
    }
    row["despues"] = {"promotion_id": pid, "promotion_type": ptype, "precio": precio}
    row["datos"]["precio"] = precio
    if ptype in SMART_LIKE:
        markup = promo.get("markup_sell_in_out")
        row["markup_previsto"] = markup if markup is not None else promo.get("nuestro_markup")
    else:
        try:
            row["markup_previsto"] = await live.markup_promo_precio(ctx, mla, precio)
        except tools.ToolCallError:
            row["markup_previsto"] = None
    return row


async def _live_promo(ctx: WriteContext, datos: dict[str, Any]) -> dict[str, Any] | None:
    return _find_promo(await live.promos(ctx, datos["mla"]), datos["promotion_id"], datos["promotion_type"])


async def check_promo_aplicar(ctx: WriteContext, row: dict[str, Any], desde: str) -> str | None:
    datos = row["datos"]
    promo = await _live_promo(ctx, datos)
    if promo is None or promo_pick._status_text(promo) != "candidate":
        return "ML ya no ofrece esa promo"
    if datos["promotion_type"] in SMART_LIKE and not same_money(precio_de_oferta(promo), datos.get("precio")):
        return f"el precio cambió desde {desde}"
    return None


async def apply_promo_aplicar(ctx: WriteContext, row: dict[str, Any]) -> Outcome:
    datos = row["datos"]
    body: dict[str, Any] = {
        "promotion_id": datos["promotion_id"],
        "promotion_type": datos["promotion_type"],
        "markup_visto": row.get("markup_previsto"),
    }
    if datos["promotion_type"] in SMART_LIKE:
        body["precio_visto"] = datos["precio"]
    else:
        body["deal_price"] = datos["precio"]
    path = f"/api/promociones/item/{tools._path_value('mla', datos['mla'])}"
    status, resp = await live.write(ctx, "POST", path, body=body)
    if status == 200 and isinstance(resp, dict) and resp.get("status") == "reconciled_not_applied":
        return RECHAZADA, "ML no aplicó la promo", None
    if status == 409 and isinstance(resp, dict) and isinstance(resp.get("detail"), dict):
        if resp["detail"].get("status") == "rejected_price_changed":
            return RECHAZADA, "el precio cambió desde el plan", None
    return http_outcome(status, resp)


async def plan_promo_quitar(ctx: WriteContext, item: dict[str, Any]) -> dict[str, Any]:
    mla, pid, ptype = str(item["mla"]), str(item["promotion_id"]), str(item["promotion_type"])
    row = new_row("promo_quitar", mla, mla)
    row["datos"] = {"mla": mla, "promotion_id": pid, "promotion_type": ptype}
    try:
        promos = await live.promos(ctx, mla)
    except tools.ToolCallError as exc:
        guards.block(row, f"lectura: {exc}")
        return row
    promo = _find_promo(promos, pid, ptype)
    if promo is None or promo_pick._status_text(promo) not in APPLIED_STATUSES:
        guards.block(row, "no_aplicada: esa promo no está aplicada en la publicación")
        return row
    row["objetivo_label"] = f"{mla} - {promo_pick.promo_name(promo) or pid}"[:255]
    original = promo_pick.finite_or_none(promo.get("original_price"))
    row["antes"] = {"promotion_id": pid, "promotion_type": ptype, "precio": promo_pick.promo_display_price(promo)}
    row["despues"] = {"promotion_id": None, "promotion_type": None, "precio": original}
    if original:
        try:
            row["markup_previsto"] = await live.markup_promo_precio(ctx, mla, original)
        except tools.ToolCallError:
            row["markup_previsto"] = None
    return row


async def check_promo_quitar(ctx: WriteContext, row: dict[str, Any], desde: str) -> str | None:
    promo = await _live_promo(ctx, row["datos"])
    if promo is None or promo_pick._status_text(promo) not in APPLIED_STATUSES:
        return f"la promo ya no está aplicada (cambió desde {desde})"
    return None


async def apply_promo_quitar(ctx: WriteContext, row: dict[str, Any]) -> Outcome:
    datos = row["datos"]
    path = f"/api/promociones/item/{tools._path_value('mla', datos['mla'])}"
    params = {"promotion_type": datos["promotion_type"], "promotion_id": datos["promotion_id"]}
    status, resp = await live.write(ctx, "DELETE", path, params=params)
    if status == 200 and isinstance(resp, dict) and resp.get("status") == "reconciled_not_applied":
        return RECHAZADA, "ML no quitó la promo", None
    return http_outcome(status, resp)


# ---------------------------------------------------------------- pause / activate

_FROM = {"paused": "active", "active": "paused"}
ESTADO_ACCION = {"paused": "estado_pausar", "active": "estado_activar"}


async def plan_estado(ctx: WriteContext, item_ids: list[str], target: str) -> list[dict[str, Any]]:
    current = await in_db(live.estados, list(item_ids))
    rows = []
    for mla in item_ids:
        row = new_row(ESTADO_ACCION[target], mla, mla)
        row["datos"] = {"item_id": mla, "status": target}
        status = current.get(mla)
        row["antes"], row["despues"] = {"estado": status}, {"estado": target}
        if status is None:
            guards.block(row, "estado_desconocido: no se pudo leer el estado de la publicación")
        elif status == target:
            guards.block(row, f"sin_cambio: la publicación ya está {target}")
        elif status != _FROM[target]:
            guards.block(row, f"no_elegible: una publicación {status} no se puede pasar a {target}")
        rows.append(row)
    return rows


async def check_estado(ctx: WriteContext, row: dict[str, Any], desde: str) -> str | None:
    current = (await in_db(live.estados, [row["objetivo"]])).get(row["objetivo"])
    if current != row["antes"].get("estado"):
        return f"el estado cambió desde {desde} (ahora: {current or 'desconocido'})"
    return None


async def apply_estado(ctx: WriteContext, row: dict[str, Any]) -> Outcome:
    datos = row["datos"]
    path = f"/api/ml-publications/items/{tools._path_value('item_id', datos['item_id'])}/status"
    status, resp = await live.write(ctx, "POST", path, body={"status": datos["status"]})
    if status == 503:
        return ERROR, live.body_detail(resp) or "el cambio no llegó a ML", None
    ok_detail = "ya estaba en ese estado" if isinstance(resp, dict) and resp.get("status") == "unchanged" else None
    return http_outcome(status, resp, ok_detail)


# ---------------------------------------------------------------- list prices and cuotas


async def plan_precio_lista(ctx: WriteContext, item: dict[str, Any], lista: str) -> dict[str, Any]:
    item_id, precio = int(item["item_id"]), float(item["precio"])
    label = await in_db(live.producto_label, item_id)
    row = new_row("precio_lista", str(item_id), label)
    row["datos"] = {"item_id": item_id, "lista_tipo": lista, "precio": precio, "recalcular_cuotas": True}
    if precio <= 0:
        guards.block(row, "precio_invalido: el precio debe ser mayor a 0")
        return row
    snapshot = await in_db(live.list_snapshot, item_id, lista)
    if not snapshot or snapshot.get("precio") is None:
        guards.block(row, "sin_precio_actual: el producto no tiene precio en esa lista")
        return row
    row["antes"], row["despues"] = snapshot, {"lista": lista, "precio": precio}
    row["cambios_pct"] = [guards.pct_change(snapshot["precio"], precio)]
    try:
        row["markup_previsto"] = await live.markup_lista(ctx, item_id, precio, live.PRICELIST_CLASICA[lista])
    except tools.ToolCallError:
        row["markup_previsto"] = None
    return row


async def check_precio_lista(ctx: WriteContext, row: dict[str, Any], desde: str) -> str | None:
    snapshot = await in_db(live.list_snapshot, row["datos"]["item_id"], row["datos"]["lista_tipo"])
    if not same_money((snapshot or {}).get("precio"), row["antes"].get("precio")):
        return f"el precio cambió desde {desde}"
    return None


async def apply_precio_lista(ctx: WriteContext, row: dict[str, Any]) -> Outcome:
    datos = row["datos"]
    params = {
        "item_id": datos["item_id"],
        "precio": datos["precio"],
        "recalcular_cuotas": "true" if datos.get("recalcular_cuotas", True) else "false",
        "lista_tipo": datos["lista_tipo"],
    }
    status, resp = await live.write(ctx, "POST", "/api/precios/set-rapido", params=params)
    result = http_outcome(status, resp)
    if result[0] != OK:
        return result
    # Undo of a list price: the cuotas that differ go back to their snapshot too (None erases that cuota, as it was).
    current = await in_db(live.list_snapshot, datos["item_id"], datos["lista_tipo"]) or {}
    for cuota, value in (datos.get("cuotas") or {}).items():
        if same_money(current.get(f"cuota_{cuota}"), value):
            continue
        status, resp = await live.write(
            ctx,
            "POST",
            "/api/precios/set-cuota",
            params={
                "item_id": datos["item_id"],
                "tipo_cuota": cuota,
                "precio": value or 0,
                "lista_tipo": datos["lista_tipo"],
            },
        )
        if status != 200:
            return ERROR, f"precio restaurado pero la cuota {cuota} no: {live.body_detail(resp) or status}", None
    return OK, None, await in_db(live.list_snapshot, datos["item_id"], datos["lista_tipo"])


def _cuota_objetivo(item_id: int, lista: str, cuota: str) -> str:
    return f"{item_id}:{lista}:{cuota}"


async def plan_precio_cuota(ctx: WriteContext, item: dict[str, Any], lista: str) -> dict[str, Any]:
    item_id, cuota, precio = int(item["item_id"]), str(item["tipo_cuota"]), float(item["precio"])
    label = await in_db(live.producto_label, item_id)
    row = new_row("precio_cuota", _cuota_objetivo(item_id, lista, cuota), f"{label or item_id} ({cuota} cuotas)")
    row["datos"] = {"item_id": item_id, "lista_tipo": lista, "tipo_cuota": cuota, "precio": precio}
    if precio <= 0:
        guards.block(row, "precio_invalido: el precio debe ser mayor a 0")
        return row
    snapshot = await in_db(live.list_snapshot, item_id, lista) or {}
    actual = snapshot.get(f"cuota_{cuota}")
    if actual is None:
        guards.block(row, "sin_precio_actual: el producto no tiene precio en esa cuota")
        return row
    row["antes"] = {"lista": lista, "cuota": cuota, "precio": actual}
    row["despues"] = {"lista": lista, "cuota": cuota, "precio": precio}
    row["cambios_pct"] = [guards.pct_change(actual, precio)]
    try:
        row["markup_previsto"] = await live.markup_lista(ctx, item_id, precio, live.PRICELIST_CUOTA[lista][cuota])
    except tools.ToolCallError:
        row["markup_previsto"] = None
    return row


async def check_precio_cuota(ctx: WriteContext, row: dict[str, Any], desde: str) -> str | None:
    datos = row["datos"]
    snapshot = await in_db(live.list_snapshot, datos["item_id"], datos["lista_tipo"]) or {}
    if not same_money(snapshot.get(f"cuota_{datos['tipo_cuota']}"), row["antes"].get("precio")):
        return f"el precio cambió desde {desde}"
    return None


async def apply_precio_cuota(ctx: WriteContext, row: dict[str, Any]) -> Outcome:
    datos = row["datos"]
    params = {
        "item_id": datos["item_id"],
        "tipo_cuota": datos["tipo_cuota"],
        "precio": datos["precio"],
        "lista_tipo": datos["lista_tipo"],
    }
    status, resp = await live.write(ctx, "POST", "/api/precios/set-cuota", params=params)
    return http_outcome(status, resp)


async def plan_markup_masivo(ctx: WriteContext, item_id: int, markup: float) -> dict[str, Any]:
    label = await in_db(live.producto_label, item_id)
    row = new_row("precio_markup_masivo", str(item_id), label)
    snapshot = await in_db(live.list_snapshot, item_id, "web")
    predicted = await in_db(live.precio_por_markup, item_id, markup)
    row["datos"] = {"item_id": item_id, "lista_tipo": "web", "markup_objetivo": markup, "precio_previsto": predicted}
    if not snapshot or snapshot.get("precio") is None:
        guards.block(row, "sin_precio_actual: el producto no tiene precio de lista")
        return row
    if predicted is None:
        guards.block(row, "sin_calculo: no se pudo calcular el precio para ese markup")
        return row
    row["antes"], row["despues"] = snapshot, {"lista": "web", "precio": predicted}
    row["cambios_pct"] = [guards.pct_change(snapshot["precio"], predicted)]
    row["markup_previsto"] = markup
    return row


async def check_markup_masivo(ctx: WriteContext, row: dict[str, Any], desde: str) -> str | None:
    datos = row["datos"]
    problem = await check_precio_lista(ctx, row, desde)
    if problem:
        return problem
    predicted = await in_db(live.precio_por_markup, datos["item_id"], datos["markup_objetivo"])
    if not same_money(predicted, datos["precio_previsto"]):
        return f"el precio previsto cambió desde {desde} (costo o comisión distintos)"
    return None


async def apply_markup_masivo(ctx: WriteContext, row: dict[str, Any]) -> Outcome:
    datos = row["datos"]
    body = {
        "markup_objetivo": datos["markup_objetivo"],
        "pricelist_id": live.PRICELIST_CLASICA["web"],
        "recalcular_cuotas": True,
        "item_ids": [datos["item_id"]],
    }
    status, resp = await live.write(ctx, "POST", "/api/precios/aplicar-markup-masivo", body=body)
    if status != 200:
        return http_outcome(status, resp)
    results = (resp or {}).get("resultados") or [{}]
    if not results[0].get("ok"):
        return RECHAZADA, results[0].get("error") or "la app no aplicó el markup", None
    return OK, None, await in_db(live.list_snapshot, datos["item_id"], "web")


# ---------------------------------------------------------------- mayorista (PxQ)


def _tramo_key(cantidad: int) -> str:
    return f"tramo_{cantidad}"


async def plan_mayorista(ctx: WriteContext, mla: str, wanted: list[dict[str, Any]]) -> dict[str, Any]:
    row = new_row("precio_mayorista", mla, mla)
    current = {t["cantidad_minima"]: t for t in await in_db(live.tramos, mla)}
    tramos, antes, despues, pcts = [], {}, {}, []
    for tramo in wanted:
        cantidad, precio = int(tramo["cantidad_minima"]), float(tramo["precio_unitario"])
        existing = current.get(cantidad)
        if existing is None:
            guards.block(
                row, f"tramo_inexistente: no hay tramo de {cantidad} unidades (solo se cambian los existentes)"
            )
            return row
        if precio <= 0:
            guards.block(row, "precio_invalido: el precio debe ser mayor a 0")
            return row
        tramos.append({"tier_id": existing["id"], "cantidad_minima": cantidad, "precio": precio})
        antes[_tramo_key(cantidad)] = existing["precio_unitario"]
        despues[_tramo_key(cantidad)] = precio
        pcts.append(guards.pct_change(existing["precio_unitario"], precio))
    row["datos"] = {"mla": mla, "tramos": tramos}
    row["antes"], row["despues"] = antes, despues
    row["cambios_pct"] = None if any(p is None for p in pcts) else pcts
    markups = [await in_db(live.markup_mayorista, mla, t["tier_id"], t["precio"]) for t in tramos]
    row["markup_previsto"] = None if not markups or any(m is None for m in markups) else min(markups)
    return row


async def check_mayorista(ctx: WriteContext, row: dict[str, Any], desde: str) -> str | None:
    current = {t["cantidad_minima"]: t["precio_unitario"] for t in await in_db(live.tramos, row["datos"]["mla"])}
    for tramo in row["datos"]["tramos"]:
        if not same_money(
            current.get(tramo["cantidad_minima"]), row["antes"].get(_tramo_key(tramo["cantidad_minima"]))
        ):
            return f"el precio del tramo de {tramo['cantidad_minima']} cambió desde {desde}"
    return None


async def _patch_tramos(ctx: WriteContext, mla: str, tramos: list[dict[str, Any]], key: str) -> tuple[int, Any, int]:
    """PATCH each tier's price; returns (last status, body, how many succeeded)."""
    done = 0
    for tramo in tramos:
        path = f"/api/pxq/{tools._path_value('mla', mla)}/tiers/{int(tramo['tier_id'])}"
        status, resp = await live.write(ctx, "PATCH", path, body={"precio_unitario": tramo[key]})
        if status != 200:
            return status, resp, done
        done += 1
    return 200, None, done


async def apply_mayorista(ctx: WriteContext, row: dict[str, Any]) -> Outcome:
    mla, tramos = row["datos"]["mla"], row["datos"]["tramos"]
    restore = [{**t, "anterior": row["antes"][_tramo_key(t["cantidad_minima"])]} for t in tramos]
    status, resp, done = await _patch_tramos(ctx, mla, tramos, "precio")
    if status != 200:
        await _patch_tramos(ctx, mla, restore[:done], "anterior")
        return http_outcome(status, resp)
    path = f"/api/pxq/{tools._path_value('mla', mla)}/sync"
    status, resp = await live.write(ctx, "POST", path, body={"allow_clear": False, "publicar_sin_markup": False})
    if status == 200 and isinstance(resp, dict) and resp.get("synced"):
        return OK, None, None
    if status == 502:
        return AMBIGUA, live.body_detail(resp) or "no se sabe si ML tomó los tramos: revisalos en la app", None
    # Not published: put the mirror back so nothing is left pending a later sync.
    await _patch_tramos(ctx, mla, restore, "anterior")
    if status == 200:
        return RECHAZADA, live.body_detail(resp) or "ML no tomó los tramos", None
    return http_outcome(status, resp)


# ---------------------------------------------------------------- registry + undo


@dataclass(frozen=True)
class Family:
    kind: str
    check: Callable[[WriteContext, dict[str, Any], str], Awaitable[str | None]]
    apply: Callable[[WriteContext, dict[str, Any]], Awaitable[Outcome]]


FAMILIES: dict[str, Family] = {
    "promo_aplicar": Family(guards.KIND_PROMO, check_promo_aplicar, apply_promo_aplicar),
    "promo_quitar": Family(guards.KIND_PROMO, check_promo_quitar, apply_promo_quitar),
    "estado_pausar": Family(guards.KIND_ESTADO, check_estado, apply_estado),
    "estado_activar": Family(guards.KIND_ESTADO, check_estado, apply_estado),
    "precio_lista": Family(guards.KIND_PRECIO, check_precio_lista, apply_precio_lista),
    "precio_cuota": Family(guards.KIND_PRECIO, check_precio_cuota, apply_precio_cuota),
    "precio_markup_masivo": Family(guards.KIND_PRECIO, check_markup_masivo, apply_markup_masivo),
    "precio_mayorista": Family(guards.KIND_PRECIO, check_mayorista, apply_mayorista),
}


async def undo_row(ctx: WriteContext, action: dict[str, Any]) -> dict[str, Any]:
    """The row that puts `action`'s target back to its `antes`. Its own `antes` is the action's `despues`: the
    live check (`Family.check`) then verifies nothing changed since the action."""
    accion, objetivo = action["accion"], action["objetivo"]
    antes, despues = action.get("antes") or {}, action.get("despues") or {}
    if accion == "promo_aplicar":
        row = new_row("promo_quitar", objetivo, action.get("objetivo_label"))
        row["datos"] = {
            "mla": objetivo,
            "promotion_id": despues.get("promotion_id"),
            "promotion_type": despues.get("promotion_type"),
        }
    elif accion == "promo_quitar":
        row = new_row("promo_aplicar", objetivo, action.get("objetivo_label"))
        row["datos"] = {
            "mla": objetivo,
            "promotion_id": antes.get("promotion_id"),
            "promotion_type": antes.get("promotion_type"),
            "precio": antes.get("precio"),
        }
    elif accion in ("estado_pausar", "estado_activar"):
        target = antes.get("estado")
        row = new_row(ESTADO_ACCION.get(target, accion), objetivo, action.get("objetivo_label"))
        row["datos"] = {"item_id": objetivo, "status": target}
    elif accion in ("precio_lista", "precio_markup_masivo"):
        row = new_row("precio_lista", objetivo, action.get("objetivo_label"))
        row["datos"] = {
            "item_id": int(objetivo),
            "lista_tipo": antes.get("lista") or "web",
            "precio": antes.get("precio"),
            "recalcular_cuotas": False,
            "cuotas": {c: antes[f"cuota_{c}"] for c in live.CUOTAS if f"cuota_{c}" in antes},
        }
    elif accion == "precio_cuota":
        item_id, lista, cuota = objetivo.split(":")
        row = new_row("precio_cuota", objetivo, action.get("objetivo_label"))
        row["datos"] = {
            "item_id": int(item_id),
            "lista_tipo": lista,
            "tipo_cuota": cuota,
            "precio": antes.get("precio"),
        }
    elif accion == "precio_mayorista":
        row = new_row("precio_mayorista", objetivo, action.get("objetivo_label"))
        current = {t["cantidad_minima"]: t["id"] for t in await in_db(live.tramos, objetivo)}
        tramos = []
        for key, precio in antes.items():
            cantidad = int(key.removeprefix("tramo_"))
            if cantidad not in current:
                guards.block(row, f"tramo_inexistente: el tramo de {cantidad} unidades ya no existe")
                return row
            tramos.append({"tier_id": current[cantidad], "cantidad_minima": cantidad, "precio": precio})
        row["datos"] = {"mla": objetivo, "tramos": tramos}
    else:
        row = new_row(accion, objetivo, action.get("objetivo_label"))
        guards.block(row, "no_deshacible: esta acción no se puede deshacer")
        return row
    row["antes"], row["despues"] = despues, antes
    return row
