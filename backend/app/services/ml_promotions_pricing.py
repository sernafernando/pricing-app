"""
Per-promo "nuestro markup" enrichment for the ML Seller Promotions panel.

READ-ONLY. Given a list of promo dicts (as returned by
`fetch_item_promotions`), enriches each with `nuestro_markup`: the seller's
markup percentage computed on the promo's effective revenue (effective
discounted price + ML co-funding, when applicable).

Cost/commission context (item, pricelist, cost, IVA, envío, tipo de cambio)
is resolved ONCE per request from `PublicacionML` + `ProductoERP`; each promo
then only runs cheap arithmetic on its own effective revenue. Mirrors the
exact price->markup chain used by `/precios/calcular-markup` and
`calcular_markup_oferta` (pricing.py).

Never crashes: any promo whose cost/publication/effective-price cannot be
resolved gets `nuestro_markup = None`.

The panel reads also ask for `markup_sell_in_out` (promos-markup-sell-in-out):
the same promo net with today's sell in / sell out of the product
(`productos_sell_in_out`, the Precios tab rule), as an extra figure. It never
changes `nuestro_markup`, which keeps ranking the offers.
"""

from datetime import date
from typing import Any, Dict, Iterable, List, Mapping, NamedTuple, Optional

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.producto import ProductoERP
from app.models.publicacion_ml import PublicacionML
from app.services.envio_real_service import resolver_costo_envio
from app.services.productos_sell_in_out import SellInOutBatch, resolver_sell_in_out_batch
from app.services.pricing_calculator import (
    calcular_comision_ml_total,
    calcular_limpio,
    calcular_markup,
    convertir_a_pesos,
    obtener_comision_base,
    obtener_constantes_pricing,
    obtener_envio_promedio_grupo,
    obtener_grupo_subcategoria,
    obtener_tipo_cambio_actual,
)

logger = get_logger(__name__)


def _co_funding_amount(promo: Dict[str, Any]) -> float:
    """ML's co-funded portion of the discount, in currency units.

    SMART, PRE_NEGOTIATED and PRICE_MATCHING: `(meli_percentage / 100) *
    original_price`, read from `promo["payload"]["meli_percentage"]` —
    PRE_NEGOTIATED and PRICE_MATCHING have the same ML co-funding contract as
    SMART. Any other promo type (SELLER_CAMPAIGN, DEAL, PRICE_DISCOUNT,
    unknown) funds nothing: 0.0. Defensive against missing/None inputs —
    always returns 0.0 on any unresolvable input rather than raising.

    ML boost: when `payload["boosted_offer"]` is truthy, ML's real
    contribution is the `meli_percentage` share PLUS an independent boost
    (ML's docs state `discount_meli_boosted_percentage` is independent of
    `meli_percentage`, not a replacement for it). The boost amount prefers
    the absolute `discount_meli_boost_amount` when present — ML's boost
    percentages are rounded to one decimal, and on high prices that rounding
    drifts by hundreds of currency units — falling back to
    `(discount_meli_boosted_percentage / 100) * original_price` when the
    absolute is missing. Any unresolvable boost value (missing/None/garbage)
    contributes 0.0 to the boost rather than raising.
    """
    if promo.get("promotion_type") not in ("SMART", "PRE_NEGOTIATED", "PRICE_MATCHING"):
        return 0.0

    payload = promo.get("payload") or {}
    meli_percentage = payload.get("meli_percentage")
    original_price = promo.get("original_price")

    if meli_percentage is None or original_price is None:
        return 0.0

    try:
        base_amount = (float(meli_percentage) / 100) * float(original_price)
    except (TypeError, ValueError):
        return 0.0

    if not payload.get("boosted_offer"):
        return base_amount

    return base_amount + _boost_amount(payload, original_price)


def _boost_amount(payload: Dict[str, Any], original_price: Any) -> float:
    """ML's boost contribution: prefers the absolute
    `discount_meli_boost_amount`, falls back to
    `discount_meli_boosted_percentage * original_price`. Returns 0.0 on any
    unresolvable/garbage value rather than raising."""
    boost_amount = payload.get("discount_meli_boost_amount")
    if boost_amount is not None:
        try:
            return float(boost_amount)
        except (TypeError, ValueError):
            pass

    boost_percentage = payload.get("discount_meli_boosted_percentage")
    if boost_percentage is not None:
        try:
            return (float(boost_percentage) / 100) * float(original_price)
        except (TypeError, ValueError):
            pass

    return 0.0


def _positive_float(value: Any) -> Optional[float]:
    """float(value) when it is a finite number > 0, else None. Never raises."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")) or number <= 0:
        return None
    return number


def _status_text(promo: Dict[str, Any]) -> Optional[str]:
    """Status as text: older stored entries carry it as `{"id": "candidate"}`."""
    status = promo.get("status")
    if isinstance(status, dict):
        status = status.get("id")
    return status if isinstance(status, str) else None


def precio_de_oferta(promo: Dict[str, Any]) -> Optional[float]:
    """THE price of a promo offer — the one rule shared by the panel display
    (frontend `promoDisplayPrice`, same fallback order), the pre-apply guard,
    the 409's `precio_actual` and every markup computed on an offer.

    For a LIGHTNING candidate, `suggested_discounted_price` when > 0 first,
    kept within [min,max] when ML sends them
    (its `price` is not the lightning suggestion). Otherwise:
    `price` when > 0; else, for a DEAL, `max_discounted_price` when > 0 (the
    smallest discount ML accepts, the price ML's web proposes; owner
    2026-11-06, MLA1506729443); else `suggested_discounted_price` when > 0;
    else None. Works on both shapes: a mirror row (`promotion_type`) and a
    raw live proxy entry (`type`); both use `price` /
    `suggested_discounted_price` / `max_discounted_price`.

    Which types legitimately carry `price` 0: candidate SELLER_CAMPAIGN /
    DEAL rows (the seller sets the price; ML only proposes
    `suggested_discounted_price` within [min,max]). ML-priced types (SMART,
    PRE_NEGOTIATED, PRICE_MATCHING) normally carry ML's offer in `price`
    even as candidates (ML docs, "Co-fondeada automatizada y precios
    competitivos"); should one arrive with 0, the suggested price is what
    the panel shows, so it is what the guard compares — like with like.
    """
    promotion_type = promo.get("promotion_type") or promo.get("type")
    if promotion_type == "LIGHTNING" and _status_text(promo) == "candidate":
        # A LIGHTNING candidate's `price` is not its suggestion (on MLA1506729443 it was the SMART
        # candidate's price, 2026-11-06): the row shows ML's suggested lightning price.
        suggested = _positive_float(promo.get("suggested_discounted_price"))
        if suggested is not None:
            # Guard: never shown outside the range ML accepts (the apply clamps the same way).
            min_price = _positive_float(promo.get("min_discounted_price"))
            max_price = _positive_float(promo.get("max_discounted_price"))
            if max_price is not None:
                suggested = min(suggested, max_price)
            if min_price is not None:
                suggested = max(suggested, min_price)
            return suggested
    price = _positive_float(promo.get("price"))
    if price is not None:
        return price
    if promotion_type == "DEAL":
        max_price = _positive_float(promo.get("max_discounted_price"))
        if max_price is not None:
            return max_price
    return _positive_float(promo.get("suggested_discounted_price"))


class _PricingContext:
    """Resolved cost/pricelist/commission context for an MLA, shared by
    `enriquecer_markup_por_promo` and `markup_para_precio`.

    Also carries the pricing `constantes` (read ONCE with the rest of the
    context) and the group shipping average (read lazily, at most once), so
    that pricing N promos / N prices costs no extra statement: before, each
    markup re-read both through `calcular_comision_ml_total` / `calcular_limpio`
    (690 statements for the 607 promos of one product's 50 MLAs).
    """

    def __init__(
        self,
        costo_ars: float,
        comision_base: float,
        iva: float,
        costo_envio: float,
        grupo_id: int,
        constantes: Optional[Dict[str, float]] = None,
        producto: Optional[ProductoERP] = None,
        tipo_cambio: Optional[float] = None,
    ) -> None:
        self.costo_ars = costo_ars
        self.comision_base = comision_base
        self.iva = iva
        self.costo_envio = costo_envio
        self.grupo_id = grupo_id
        self.constantes = constantes
        # The product and the USD rate its cost converted at: what the sell in / sell out companion prices with.
        self.producto = producto
        self.tipo_cambio = tipo_cambio
        self._envio_promedio: Optional[float] = None

    def costo_envio_para(self, db: Session, revenue: float) -> float:
        """The shipping cost `calcular_limpio` would use for `revenue`.

        Same rule it applies itself: above the free-shipping tier, a product with no
        shipping cost of its own uses its group's average. Resolved here once per
        context instead of once per priced promo."""
        free_shipping_from = (self.constantes or {}).get("monto_tier3")
        if (
            self.costo_envio == 0
            and self.grupo_id is not None
            and free_shipping_from is not None
            and revenue >= free_shipping_from
        ):
            if self._envio_promedio is None:
                self._envio_promedio = obtener_envio_promedio_grupo(db, self.grupo_id)
            return self._envio_promedio
        return self.costo_envio


def _resolve_pricing_context(db: Session, mla: str) -> Optional[_PricingContext]:
    """Resolves item/pricelist/cost/commission context ONCE for `mla`.
    Returns None (never raises) when the publication, product cost, or
    commission base cannot be resolved."""
    try:
        publicacion = db.query(PublicacionML).filter(PublicacionML.mla == mla).first()
        if not publicacion:
            return None

        producto = db.query(ProductoERP).filter(ProductoERP.item_id == publicacion.item_id).first()
        if not producto or not producto.costo:
            return None

        tipo_cambio = None
        if producto.moneda_costo == "USD":
            tipo_cambio = obtener_tipo_cambio_actual(db, "USD")

        costo_ars = convertir_a_pesos(producto.costo, producto.moneda_costo, tipo_cambio)
        grupo_id = obtener_grupo_subcategoria(db, producto.subcategoria_id)
        comision_base = obtener_comision_base(db, publicacion.pricelist_id, grupo_id)
        costo_envio = resolver_costo_envio(db, producto)
        constantes = obtener_constantes_pricing(db)
    except Exception as e:
        logger.warning("Error resolving pricing context for mla %s: %s", mla, e)
        return None

    if comision_base is None:
        return None

    return _PricingContext(
        costo_ars=costo_ars,
        comision_base=comision_base,
        iva=producto.iva,
        costo_envio=costo_envio,
        grupo_id=grupo_id,
        constantes=constantes,
        producto=producto,
        tipo_cambio=tipo_cambio,
    )


def enriquecer_markup_por_promo(
    db: Session,
    mla: str,
    promociones: List[Dict[str, Any]],
    *,
    sell_in_out: bool = False,
    batch: Optional[SellInOutBatch] = None,
) -> List[Dict[str, Any]]:
    """Adds `nuestro_markup` (Optional[float], percentage) to each promo dict
    in `promociones`, mutating them in place and returning the same list.

    Resolves item/pricelist/cost/commission context ONCE per request from
    `mla`. If the publication or the product cost cannot be resolved, every
    promo in the list gets `nuestro_markup = None` (no exception).

    `sell_in_out` (the panel read only) also adds `markup_sell_in_out`
    (`_markup_sell_in_out`), resolving the product's sell in / sell out once
    for the whole list, or using `batch` when the caller already read it for
    many publications (`resolver_sell_in_out_para_mlas`). Callers that need
    only the plain markup leave it off: they need neither the field nor its
    queries.
    """
    if not promociones:
        return promociones

    context = _resolve_pricing_context(db, mla)
    if context is None:
        for promo in promociones:
            promo["nuestro_markup"] = None
            if sell_in_out:
                promo["markup_sell_in_out"] = None
        return promociones

    if sell_in_out and batch is None:
        batch = _sell_in_out_batch(db, context, mla)
    for promo in promociones:
        promo["nuestro_markup"] = _calcular_nuestro_markup(db=db, promo=promo, context=context)
        if sell_in_out:
            # The extra figure goes with the markup: none when the promo has no markup of its own.
            promo["markup_sell_in_out"] = (
                None if promo["nuestro_markup"] is None else _markup_sell_in_out_de_promo(db, context, batch, promo)
            )

    return promociones


def _markup_con_contexto(
    db: Session,
    context: _PricingContext,
    price: float,
    mla: Optional[str] = None,
) -> Optional[float]:
    """Seller markup percentage for `price` given an ALREADY-RESOLVED
    `context`. Extracted from `markup_para_precio` so a caller that needs
    the markup for MANY prices under the same MLA (e.g. one price per
    catalog competitor) resolves the pricing context ONCE and loops here,
    instead of calling `markup_para_precio` per price — which would
    re-resolve `_resolve_pricing_context` (a publication + product +
    commission lookup) on every single call.

    `mla` is optional and used ONLY for the warning log message on
    failure; it carries no behaviour. Never raises: returns None when the
    markup computation itself fails.
    """
    try:
        return _markup_para_revenue(db, context, price)
    except Exception as e:
        logger.warning("Error calculando markup_para_precio para mla %s, price %s: %s", mla, price, e)
        return None


def markup_para_precio(db: Session, mla: str, price: float) -> Optional[float]:
    """Seller markup percentage for a candidate `price` on `mla`, reusing
    the SAME cost/pricelist/commission resolution and price->markup chain
    as `enriquecer_markup_por_promo`, but on the plain `price` (no
    co-funding — used for SELLER_CAMPAIGN/DEAL, which are seller-funded).

    Never raises: returns None when the cost/publication context is
    unresolvable, or when the markup computation itself fails.
    """
    context = _resolve_pricing_context(db, mla)
    if context is None:
        return None

    return _markup_con_contexto(db, context, price, mla=mla)


class MarkupsDePrecio(NamedTuple):
    """`markup_para_precio` and its sell in / sell out companion for the same price."""

    nuestro_markup: Optional[float]
    markup_sell_in_out: Optional[float]


def markup_para_precio_con_sell_in_out(
    db: Session, mla: str, price: float, *, batch: Optional[SellInOutBatch] = None
) -> MarkupsDePrecio:
    """`markup_para_precio(price)` plus `markup_sell_in_out` on the same net
    (`_markup_sell_in_out`), with ONE pricing context. Used by the panel's
    manual price input and its "Markup vigente" line, and by the hay_mejores
    status quo. `batch`: an already-resolved sell in / sell out read. Never raises."""
    context = _resolve_pricing_context(db, mla)
    if context is None:
        return MarkupsDePrecio(None, None)
    nuestro = _markup_con_contexto(db, context, price, mla=mla)
    if nuestro is None:
        return MarkupsDePrecio(None, None)
    if batch is None:
        batch = _sell_in_out_batch(db, context, mla)
    return MarkupsDePrecio(nuestro, _markup_sell_in_out_seguro(db, context, batch, price, mla))


def _contextos_mlas(db: Session, mlas: list[str]) -> Optional[list[tuple[str, Optional[int]]]]:
    """Store scope for companion markups: one `(ml, store_id)` when every MLA shares the same official store;
    `None` (global) when the set mixes stores — a single batch cannot be both."""
    from app.models.ml_publications import MlItem

    stores = {row[0] for row in db.query(MlItem.official_store_id).filter(MlItem.item_id.in_(mlas)).distinct()}
    if len(stores) != 1:
        return None
    return [("ml", next(iter(stores)))]


def resolver_sell_in_out_para_mlas(db: Session, mlas: Iterable[str]) -> Optional[SellInOutBatch]:
    """Today's sell in / sell out of the products of `mlas`, in ONE read for all of them (one
    publication lookup plus `resolver_sell_in_out_batch`), so ranking many publications does not
    read it publication by publication. In a SAVEPOINT; None (never raises) when it fails, and the
    callers then fall back to the plain markups' own read.

    When every MLA shares the same official store, the batch is store-scoped; mixed stores keep the
    global read (ponytail: split per store when a caller needs mixed-store accuracy in one batch).
    """
    unicos = sorted({m for m in mlas if m})
    if not unicos:
        return None
    try:
        with db.begin_nested():
            ids = [row[0] for row in db.query(PublicacionML.item_id).filter(PublicacionML.mla.in_(unicos)).distinct()]
            return resolver_sell_in_out_batch(db, ids, date.today(), contextos=_contextos_mlas(db, unicos))
    except Exception as e:
        logger.warning("Error resolviendo sell in / sell out para %s publicaciones: %s", len(unicos), e)
        return None


# Types where ML co-funds the discount (`_co_funding_amount`). A started
# offer of one of these is the real status quo when its consumer price is
# the sale_price — plain `markup_para_precio(sale)` would understate markup.
COFUNDED_PROMOTION_TYPES: frozenset[str] = frozenset({"SMART", "PRE_NEGOTIATED", "PRICE_MATCHING"})

# Pesos: sale_price and started `price` can differ by cents (e.g. 555867.83 vs 555867.8).
_BASELINE_PRICE_TOLERANCE_ARS = 1.0


def _prices_close(
    left: Optional[float], right: Optional[float], *, tolerance: float = _BASELINE_PRICE_TOLERANCE_ARS
) -> bool:
    if left is None or right is None:
        return False
    try:
        return abs(float(left) - float(right)) <= tolerance
    except (TypeError, ValueError):
        return False


def markup_baseline_vigente(
    db: Session,
    mla: str,
    baseline_price: float,
    *,
    raw_promotions: Any = None,
) -> Optional[float]:
    """The plain markup of `markups_baseline_vigente` (no sell in / sell out read)."""
    return markups_baseline_vigente(
        db, mla, baseline_price, raw_promotions=raw_promotions, sell_in_out=False
    ).nuestro_markup


def markups_baseline_vigente(
    db: Session,
    mla: str,
    baseline_price: float,
    *,
    raw_promotions: Any = None,
    sell_in_out: bool = True,
    batch: Optional[SellInOutBatch] = None,
) -> MarkupsDePrecio:
    """Seller markup for the MeLi status-quo price used by hay_mejores, with its sell in / sell out
    companion (`markup_sell_in_out`, None with `sell_in_out=False`).

    - If a **started** SMART / PRE_NEGOTIATED / PRICE_MATCHING entry's offer
      price matches ``baseline_price`` (sale), use the co-funded chain
      (same as the promo card / ``enriquecer_markup_por_promo``): the match
      with the best plain markup, and that same offer's companion.
    - Otherwise use plain ``markup_para_precio`` (no co-funding) — list
      price, DEAL/seller campaigns, or no matching cofunded started offer.

    ``raw_promotions`` is the seller-promotions mirror list (store `raw` or
    the same shape); ``batch`` an already-resolved sell in / sell out read.
    Never raises: None when markup cannot be computed.
    """
    if baseline_price is None or baseline_price <= 0:
        return MarkupsDePrecio(None, None)

    def _plano() -> MarkupsDePrecio:
        if sell_in_out:
            return markup_para_precio_con_sell_in_out(db, mla, baseline_price, batch=batch)
        return MarkupsDePrecio(markup_para_precio(db, mla, baseline_price), None)

    started_cofunded: List[Dict[str, Any]] = []
    if isinstance(raw_promotions, list):
        for entry in raw_promotions:
            if not isinstance(entry, Mapping):
                continue
            status = entry.get("status")
            promo_type = entry.get("type") or entry.get("promotion_type")
            if status != "started" or promo_type not in COFUNDED_PROMOTION_TYPES:
                continue
            started_cofunded.append(
                {
                    "mla": mla,
                    "promotion_id": entry.get("id") or entry.get("promotion_id"),
                    "promotion_type": promo_type,
                    "status": status,
                    "price": entry.get("price"),
                    "original_price": entry.get("original_price"),
                    "suggested_discounted_price": entry.get("suggested_discounted_price"),
                    "payload": dict(entry.get("payload") or entry),
                }
            )

    if started_cofunded:
        try:
            enriquecer_markup_por_promo(db, mla, started_cofunded, sell_in_out=sell_in_out, batch=batch)
        except Exception as e:
            logger.warning("Error enriqueciendo baseline cofunded mla %s: %s", mla, e)
            return _plano()

        matched = [
            promo
            for promo in started_cofunded
            if _prices_close(precio_de_oferta(promo), baseline_price) and promo.get("nuestro_markup") is not None
        ]
        if matched:
            # Same consumer price: the best reported markup (ties rare; the first on a tie), with its companion.
            best = max(matched, key=lambda promo: float(promo["nuestro_markup"]))
            return MarkupsDePrecio(float(best["nuestro_markup"]), best.get("markup_sell_in_out"))

    return _plano()


def markup_de_oferta_live(
    db: Session,
    mla: str,
    promotion_type: str,
    live_entry: Dict[str, Any],
    price: Optional[float] = None,
) -> Optional[float]:
    """Seller markup for a LIVE proxy offer entry, computed with exactly the
    chain the panel shows (`enriquecer_markup_por_promo`: effective price +
    ML co-funding + boost).

    The live proxy entry is the raw ML item-promotion object — the same
    object the mirror stores as `payload` — so it is passed as the payload:
    `meli_percentage` / boost fields live there for the co-funding math.
    `price` overrides the entry's price (used to price what ML says it
    actually applied after an enroll).

    Never raises: None when the markup cannot be computed.
    """
    promo: Dict[str, Any] = {
        "mla": mla,
        "promotion_id": live_entry.get("id"),
        "promotion_type": promotion_type,
        "price": price if price is not None else live_entry.get("price"),
        "original_price": live_entry.get("original_price"),
        "suggested_discounted_price": live_entry.get("suggested_discounted_price"),
        # precio_de_oferta prices a candidate DEAL at its max, as the panel and the apply do.
        "max_discounted_price": live_entry.get("max_discounted_price"),
        "payload": live_entry,
    }
    try:
        enriquecer_markup_por_promo(db, mla, [promo])
    except Exception as e:
        logger.warning("Error calculando markup de oferta live mla %s: %s", mla, e)
        return None
    return promo.get("nuestro_markup")


def _limpio_para_revenue(db: Session, context: _PricingContext, revenue: float) -> float:
    """The net (`calcular_limpio`) of `revenue` using ONLY what `context` already resolved
    (constants, shipping): no statement per call."""
    comisiones = calcular_comision_ml_total(
        revenue, context.comision_base, context.iva, db=db, constantes=context.constantes
    )
    return calcular_limpio(
        revenue,
        context.iva,
        context.costo_envio_para(db, revenue),
        comisiones["comision_total"],
        db=db,
        constantes=context.constantes,
    )


def _markup_para_revenue(db: Session, context: _PricingContext, revenue: float) -> float:
    """price->markup chain on `revenue` (`_limpio_para_revenue`): no statement per call."""
    return calcular_markup(_limpio_para_revenue(db, context, revenue), context.costo_ars) * 100


_SELL_IN_OUT_KEY = "promo"


def _sell_in_out_batch(db: Session, context: _PricingContext, mla: str) -> Optional[SellInOutBatch]:
    """Today's sell in / sell out of the context's product (`resolver_sell_in_out_batch`, a few
    queries, once per request). In a SAVEPOINT: a failure leaves the request session usable and
    the companion markups null, never the plain ones."""
    if context.producto is None:
        return None
    try:
        with db.begin_nested():
            return resolver_sell_in_out_batch(
                db, [context.producto.item_id], date.today(), contextos=_contextos_mlas(db, [mla])
            )
    except Exception as e:
        logger.warning("Error resolviendo sell in / sell out para mla %s: %s", mla, e)
        return None


def _markup_sell_in_out(
    db: Session, context: _PricingContext, batch: Optional[SellInOutBatch], revenue: float
) -> Optional[float]:
    """The markup of `revenue`'s net with the product's sell in / sell out today, on the Precios tab
    rule (`ProductPrices.jsx` `SellInOutMarkup`): with sell in + sell out when there is sell out, else
    with sell in only. None when the product has neither, or neither amount is known.

    A `precio_neto` sell out percentage is based on that same `revenue` (owner, 2026-11-06: "se
    calcula sobre lo que nos dejaría la promo como el mark up que se muestra hoy en las promos, no
    tendría sentido tomarla de dos valores distintos"): the promo price plus ML's co-funding."""
    if batch is None or context.producto is None:
        return None
    acc = batch.markups(context.producto, precio_lista_ml=revenue, tipo_cambio=context.tipo_cambio)
    acc.record(_SELL_IN_OUT_KEY, _limpio_para_revenue(db, context, revenue))
    payload = acc.payload()
    if payload is None:
        return None
    con_sell_out = payload.markups_sell_in_out.get(_SELL_IN_OUT_KEY)
    return con_sell_out if con_sell_out is not None else payload.markups_sell_in.get(_SELL_IN_OUT_KEY)


def _markup_sell_in_out_seguro(
    db: Session,
    context: _PricingContext,
    batch: Optional[SellInOutBatch],
    revenue: float,
    mla: Optional[str],
) -> Optional[float]:
    """`_markup_sell_in_out`, None instead of raising."""
    try:
        return _markup_sell_in_out(db, context, batch, revenue)
    except Exception as e:
        logger.warning("Error calculando markup con sell in / sell out para mla %s: %s", mla, e)
        return None


def _markup_sell_in_out_de_promo(
    db: Session, context: _PricingContext, batch: Optional[SellInOutBatch], promo: Dict[str, Any]
) -> Optional[float]:
    """`_markup_sell_in_out` on the same revenue as `nuestro_markup` (effective price + ML co-funding)."""
    effective_price = precio_de_oferta(promo)
    if effective_price is None or batch is None:
        return None
    try:
        revenue = effective_price + _co_funding_amount(promo)
    except Exception as e:
        logger.warning("Error calculando revenue de promo %s: %s", promo.get("promotion_id"), e)
        return None
    return _markup_sell_in_out_seguro(db, context, batch, revenue, promo.get("mla"))


def _calcular_nuestro_markup(db: Session, promo: Dict[str, Any], context: _PricingContext) -> Optional[float]:
    effective_price = precio_de_oferta(promo)
    if effective_price is None:
        return None

    try:
        co_funding = _co_funding_amount(promo)
        return _markup_para_revenue(db, context, effective_price + co_funding)
    except Exception as e:
        logger.warning(
            "Error calculando nuestro_markup para promo %s de mla %s: %s",
            promo.get("promotion_id"),
            promo.get("mla"),
            e,
        )
        return None
