"""Derived prices the Productos screens show next to a product's stored prices:
the rebate price and its markup, and the best current ML offer.

ONE computation for every endpoint that returns them -- the Productos listing
(`GET /productos`) and the product detail (`GET /productos/{item_id}`) -- so
the two can never disagree on the same product. Pure functions over a
`PricingContext`; the only query is the batch prefetch of publications and
current offers.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from typing import Any, Callable, Optional

from sqlalchemy.orm import Session

from app.models.oferta_ml import OfertaML
from app.models.publicacion_ml import PublicacionML
from app.services.pricing_calculator import calcular_comision_ml_total, calcular_limpio, calcular_markup
from app.services.pricing_context import PricingContext

# Rebate percentage when the product has none stored.
PORCENTAJE_REBATE_DEFAULT = 3.8
# The rebate is priced on the ML clásica list.
PRICELIST_CLASICA = 4

# (item_id, envio_erp, grupo_id, precio) -> shipping cost: `resolve_envio`
# bound to the request's context and its real-shipping batch.
ResolveEnvio = Callable[[int, float, Optional[int], float], float]


@dataclass(frozen=True)
class MejorOferta:
    """The best current offer as `ProductoResponse.mejor_oferta_*` carries it.

    `markup` is a decimal ratio (not a percentage), as the response has it.
    `limpio` is what the markup was computed from (the PPP companion needs it).
    """

    precio: Optional[float] = None
    monto_rebate: Optional[float] = None
    pvp_seller: Optional[float] = None
    markup: Optional[float] = None
    porcentaje_rebate: Optional[float] = None
    fecha_hasta: Optional[date] = None
    limpio: Optional[float] = None


@dataclass(frozen=True)
class Rebate:
    """The rebate price and its markup (a percentage), with the `limpio` behind it."""

    precio: Optional[float] = None
    markup: Optional[float] = None
    limpio: Optional[float] = None


def cargar_ofertas_vigentes(
    db: Session, item_ids: list[int], hoy: date
) -> tuple[dict[int, list[PublicacionML]], dict[str, OfertaML], list[str]]:
    """The products' publications by product, per MLA its first current offer
    with a seller PVP, and every MLA in the order the publications were read."""
    all_pubs = db.query(PublicacionML).filter(PublicacionML.item_id.in_(item_ids)).all() if item_ids else []
    pubs_by_item: dict[int, list[PublicacionML]] = {}
    all_mla_list: list[str] = []
    for pub in all_pubs:
        pubs_by_item.setdefault(pub.item_id, []).append(pub)
        all_mla_list.append(pub.mla)

    ofertas_by_mla: dict[str, OfertaML] = {}
    if all_mla_list:
        all_ofertas = (
            db.query(OfertaML)
            .filter(
                OfertaML.mla.in_(all_mla_list),
                OfertaML.fecha_desde <= hoy,
                OfertaML.fecha_hasta >= hoy,
                OfertaML.pvp_seller.isnot(None),
            )
            .all()
        )
        for oferta in all_ofertas:
            if oferta.mla not in ofertas_by_mla:
                ofertas_by_mla[oferta.mla] = oferta
    return pubs_by_item, ofertas_by_mla, all_mla_list


def calcular_mejor_oferta(
    ctx: PricingContext,
    producto_erp: Any,
    pubs: list[PublicacionML],
    ofertas_by_mla: dict[str, OfertaML],
    grupo_id: Optional[int],
    resolve_envio: ResolveEnvio,
) -> MejorOferta:
    """The first publication's current offer, with its markup over the list cost."""
    mejor_oferta = None
    mejor_pub = None
    for pub in pubs:
        oferta = ofertas_by_mla.get(pub.mla)
        if oferta and not mejor_oferta:
            mejor_oferta = oferta
            mejor_pub = pub
    if not (mejor_oferta and mejor_pub):
        return MejorOferta()

    precio = float(mejor_oferta.precio_final) if mejor_oferta.precio_final else None
    pvp = float(mejor_oferta.pvp_seller) if mejor_oferta.pvp_seller else None
    porcentaje = float(mejor_oferta.aporte_meli_porcentaje) if mejor_oferta.aporte_meli_porcentaje else None
    monto = pvp - precio if precio and pvp else None

    markup = None
    limpio = None
    if pvp and pvp > 0:
        costo_calc = ctx.costo_en_pesos(producto_erp.costo, producto_erp.moneda_costo)
        comision_base = ctx.comision(mejor_pub.pricelist_id, grupo_id)
        if comision_base:
            comisiones = calcular_comision_ml_total(pvp, comision_base, producto_erp.iva, constantes=ctx.constantes)
            costo_envio = resolve_envio(producto_erp.item_id, producto_erp.envio or 0, grupo_id, pvp)
            limpio = calcular_limpio(
                pvp, producto_erp.iva, costo_envio, comisiones["comision_total"], constantes=ctx.constantes
            )
            markup = calcular_markup(limpio, costo_calc)

    return MejorOferta(
        precio=precio,
        monto_rebate=monto,
        pvp_seller=pvp,
        markup=markup,
        porcentaje_rebate=porcentaje,
        fecha_hasta=mejor_oferta.fecha_hasta,
        limpio=limpio,
    )


def calcular_rebate(
    ctx: PricingContext,
    producto_erp: Any,
    producto_pricing: Any,
    grupo_id: Optional[int],
    resolve_envio: ResolveEnvio,
) -> Rebate:
    """The ML list price grossed up by the rebate percentage, priced as a clásica."""
    if not (producto_pricing and producto_pricing.precio_lista_ml and producto_pricing.participa_rebate):
        return Rebate()
    porcentaje = float(
        producto_pricing.porcentaje_rebate
        if producto_pricing.porcentaje_rebate is not None
        else PORCENTAJE_REBATE_DEFAULT
    )
    precio = float(producto_pricing.precio_lista_ml) / (1 - porcentaje / 100)

    costo = ctx.costo_en_pesos(producto_erp.costo, producto_erp.moneda_costo)
    comision_base = ctx.comision(PRICELIST_CLASICA, grupo_id)
    if not (comision_base and precio > 0):
        return Rebate(precio=precio)
    comisiones = calcular_comision_ml_total(precio, comision_base, producto_erp.iva, constantes=ctx.constantes)
    costo_envio = resolve_envio(producto_erp.item_id, producto_erp.envio or 0, grupo_id, precio)
    limpio = calcular_limpio(
        precio, producto_erp.iva, costo_envio, comisiones["comision_total"], constantes=ctx.constantes
    )
    return Rebate(precio=precio, markup=calcular_markup(limpio, costo) * 100, limpio=limpio)


def mejor_oferta_out_of_cards(mejor_oferta: MejorOferta, rebate: Rebate, producto_pricing: Any) -> MejorOferta:
    """An out-of-cards product with a priced rebate shows the rebate as its best
    offer (same price as PVP, no Meli contribution, no end date); otherwise the
    offer is kept."""
    if not (
        producto_pricing and producto_pricing.out_of_cards and rebate.precio is not None and rebate.markup is not None
    ):
        return mejor_oferta
    return replace(
        mejor_oferta,
        precio=rebate.precio,
        pvp_seller=rebate.precio,
        markup=rebate.markup / 100,
        porcentaje_rebate=None,
        monto_rebate=None,
        fecha_hasta=None,
        limpio=rebate.limpio,
    )
