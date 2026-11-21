"""Live values a write plan needs, read the way the app reads them.

Reads that the app exposes per user (promos of a publication, markup at a price) go through the app's own GET
endpoints as the user (`read`), so the same permissions apply. Plain stored values the write endpoints themselves
read first (current list price and cuotas, PxQ mirror tiers, publication status) are read from the database with
the same functions/models those endpoints use. Every write goes through `write` (allowlisted loopback routes).
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.mcp import loopback, tools
from app.mcp.write.context import WriteContext
from app.models.ml_pxq_tier import MlPxqTier
from app.models.producto import ProductoERP, ProductoPricing

CUOTAS = ("3", "6", "9", "12")
# Price lists of the clásica and of each cuota, per lista_tipo (same ids as /precios/set-rapido and set-cuota).
PRICELIST_CLASICA = {"web": 4, "pvp": 12}
PRICELIST_CUOTA = {
    "web": {"3": 17, "6": 14, "9": 13, "12": 23},
    "pvp": {"3": 18, "6": 19, "9": 20, "12": 21},
}


# ---------------------------------------------------------------- app endpoints as the user


async def read(ctx: WriteContext, path: str, params: dict[str, Any] | None = None) -> Any:
    """GET as the user; raises tools.ToolCallError on any non-200."""
    return await tools._get(path, params or {}, ctx.username)


async def write(
    ctx: WriteContext, method: str, path: str, params: dict[str, Any] | None = None, body: Any = None
) -> tuple[int, Any]:
    """POST/PATCH/DELETE as the user through the real endpoint; returns (status, parsed body or None)."""
    status, raw = await loopback.send_write(method, path, params or {}, body, loopback.identity_headers(ctx.username))
    try:
        return status, json.loads(raw) if raw else None
    except ValueError:
        return status, None


def body_detail(body: Any) -> str | None:
    if isinstance(body, dict):
        detail = body.get("detail")
        if isinstance(detail, str):
            return detail[:500]
        if isinstance(detail, dict):
            text = detail.get("mensaje") or detail.get("message") or json.dumps(detail, ensure_ascii=False)
            return str(text)[:500]
        if detail is not None:
            return json.dumps(detail, ensure_ascii=False)[:500]
        error = body.get("error")
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            return error["message"][:500]
        if isinstance(body.get("message"), str):
            return body["message"][:500]
    return None


async def promos(ctx: WriteContext, mla: str) -> list[dict[str, Any]]:
    data = await read(ctx, f"/api/promociones/item/{tools._path_value('mla', mla)}") or {}
    return [p for p in data.get("promotions") or [] if isinstance(p, dict)]


async def markup_promo_precio(ctx: WriteContext, mla: str, precio: float) -> float | None:
    """Markup with sell in (else plain) of `mla` sold at `precio` (the panel's manual price input)."""
    data = await read(ctx, f"/api/promociones/item/{tools._path_value('mla', mla)}/markup", {"price": precio}) or {}
    value = data.get("markup_sell_in_out")
    return value if value is not None else data.get("nuestro_markup")


async def markup_lista(ctx: WriteContext, item_id: int, precio: float, pricelist_id: int) -> float | None:
    """Markup (%) of the product at `precio` in a price list (GET /precios/calcular-markup)."""
    data = await read(
        ctx, "/api/precios/calcular-markup", {"item_id": item_id, "precio": precio, "pricelist_id": pricelist_id}
    )
    return data.get("markup") if isinstance(data, dict) else None


# ---------------------------------------------------------------- stored values


def _float(value: Any) -> float | None:
    return None if value is None else round(float(value), 2)


def producto_label(db: Session, item_id: int) -> str | None:
    producto = db.query(ProductoERP).filter(ProductoERP.item_id == item_id).first()
    if producto is None:
        return None
    return f"{producto.codigo or item_id} - {producto.descripcion or ''}".strip(" -")[:255]


def list_snapshot(db: Session, item_id: int, lista_tipo: str) -> dict[str, Any] | None:
    """Clásica + cuotas of one list (web | pvp) as stored in `productos_pricing`; None without a pricing row."""
    pricing = db.query(ProductoPricing).filter(ProductoPricing.item_id == item_id).first()
    if pricing is None:
        return None
    if lista_tipo == "pvp":
        snapshot = {"lista": "pvp", "precio": _float(pricing.precio_pvp)}
        snapshot.update({f"cuota_{c}": _float(getattr(pricing, f"precio_pvp_{c}_cuotas")) for c in CUOTAS})
    else:
        snapshot = {"lista": "web", "precio": _float(pricing.precio_lista_ml)}
        snapshot.update({f"cuota_{c}": _float(getattr(pricing, f"precio_{c}_cuotas")) for c in CUOTAS})
    return snapshot


def precio_por_markup(db: Session, item_id: int, markup_objetivo: float) -> float | None:
    """The ML Clásica price /precios/aplicar-markup-masivo would write for `markup_objetivo` (same calculator and
    inputs, rounded the same way), or None when it cannot be computed."""
    from app.services.envio_real_service import resolver_costo_envio
    from app.services.pricing_calculator import calcular_precio_producto, costo_ars_actual, obtener_tipo_cambio_actual

    producto = db.query(ProductoERP).filter(ProductoERP.item_id == item_id).first()
    if producto is None:
        return None
    tipo_cambio = None
    if producto.moneda_costo == "USD":
        tipo_cambio = obtener_tipo_cambio_actual(db, "USD")
        if not tipo_cambio:
            return None
    calculo = calcular_precio_producto(
        db=db,
        costo=costo_ars_actual(db, producto.item_id, tipo_cambio),  # costo SI (S13)
        moneda_costo="ARS",
        iva=producto.iva,
        envio=resolver_costo_envio(db, producto),
        subcategoria_id=producto.subcategoria_id,
        pricelist_id=PRICELIST_CLASICA["web"],
        markup_objetivo=markup_objetivo,
        tipo_cambio=tipo_cambio,
        adicional_markup=0,
    )
    if "error" in calculo:
        return None
    return float(round(float(calculo["precio"])))


def estados(db: Session, mlas: list[str]) -> dict[str, str]:
    """Publication status per MLA as the pause/activate service reads it (missing key = unknown)."""
    from app.services.ml_publication_status_service import fetch_publication_status_by_mla

    return {mla: status.status for mla, status in fetch_publication_status_by_mla(db, mlas).items()}


def tramos(db: Session, mla: str) -> list[dict[str, Any]]:
    rows = db.query(MlPxqTier).filter(MlPxqTier.item_id == mla).order_by(MlPxqTier.cantidad_minima).all()
    return [
        {"id": t.id, "cantidad_minima": t.cantidad_minima, "precio_unitario": _float(t.precio_unitario)} for t in rows
    ]


def markup_mayorista(db: Session, mla: str, tier_id: int, precio: float) -> float | None:
    """Markup (%) of one PxQ tier at a candidate unit price, with the same chain as the PxQ markup read."""
    from app.services.pricing_calculator import obtener_constantes_pricing
    from app.services.pxq_markup import calcular_markup_pxq, resolve_order_cost, resolve_tier_shipping
    from app.services.pxq_pricing_context import PxqPricingUnavailable, resolve_pxq_pricing_context

    tier = db.get(MlPxqTier, tier_id)
    if tier is None:
        return None
    context = resolve_pxq_pricing_context(db, mla)
    shipping = resolve_tier_shipping(tier)
    if isinstance(context, PxqPricingUnavailable) or shipping is None:
        return None
    computed = calcular_markup_pxq(
        precio_unitario=precio,
        cantidad_minima=tier.cantidad_minima,
        comision_base_pct=context.comision_base_pct,
        iva=context.iva,
        costo=resolve_order_cost(context.costo_ars, tier.cantidad_minima),
        shipping=shipping,
        constantes=obtener_constantes_pricing(db),
    )
    return round(computed["markup"] * 100, 2)
