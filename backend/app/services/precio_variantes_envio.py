"""Markup of a candidate price per active publication, each with its own shipping cost.

Every markup in the app prices shipping with MAX(list_cost) across the product's active MLAs
(`envio_real_service`). A product sold through a cheap Flex publication and a dear Colecta one therefore looks
worse than it is on the first. This module prices the same price once per active MLA with THAT MLA's
`list_cost`, through the existing calculator (`calcular_comision_ml_total` -> `calcular_limpio` ->
`calcular_markup`): no new pricing math, and débitos/créditos and IIBB stay inside Varios as today.

It also returns two averages, so the PM can choose a price: a simple one over the priced publications and one
weighted by the units each sold in the last `VENTANA_DIAS` days (`ml_sale_lines`, cancellations already
excluded there); plus today's MAX-based value for comparison.

Reads, all batched and independent of the number of publications: the active publications (one query), their
`ml_items` row (one), their sales in the window (one), their costs (one cross-DB read), the pricing constants
(one) and the commission per DISTINCT price list of the product (`obtener_comision_base`, bounded by the
handful of ML price lists, not by publications).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any, Mapping, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.ml_publications import MlItem
from app.models.ml_sale_line import MlSaleLine
from app.models.producto import ProductoERP
from app.models.publicacion_ml import PublicacionML
from app.services.envio_real_service import costo_envio_maximo, costos_envio_por_mla
from app.services.pricing_calculator import (
    calcular_comision_ml_total,
    calcular_limpio,
    calcular_markup,
    envio_cuenta,
    obtener_comision_base,
    obtener_constantes_pricing,
    obtener_envio_promedio_grupo,
    obtener_grupo_subcategoria,
)

logger = logging.getLogger(__name__)

VENTANA_DIAS = 30
PONDERACION = "unidades_vendidas"
PRICELIST_CLASICA = 4
MOTIVO_SIN_COMISION = "sin_comision"
ORIGEN_MAX = "max_publicaciones"
ORIGEN_ERP = "erp"
ORIGEN_GRUPO_PROMEDIO = "grupo_promedio"
MOTIVO_SIN_COSTO_ENVIO = "sin_costo_envio"

# `ml_items.logistic_type` values the code documents as observed (`mode_resolution.py`); any other value
# passes through raw with no label.
LOGISTICA_POR_TIPO = {
    "self_service": "flex",
    "cross_docking": "colecta",
    "xd_drop_off": "colecta",
    "fulfillment": "full",
}


def _publicaciones_activas(db: Session, item_id: int) -> list[tuple[str, Optional[int]]]:
    rows = db.execute(
        select(PublicacionML.mla, PublicacionML.pricelist_id)
        .where(PublicacionML.item_id == item_id, PublicacionML.activo.is_(True))
        .order_by(PublicacionML.mla)
    ).all()
    return [(mla, pricelist_id) for mla, pricelist_id in rows]


def _datos_ml(db: Session, mlas: list[str]) -> dict[str, tuple[Optional[str], Optional[str]]]:
    """{mla: (listing_type_id, logistic_type)} from the publications mirror."""
    rows = db.execute(
        select(MlItem.item_id, MlItem.listing_type_id, MlItem.logistic_type).where(MlItem.item_id.in_(mlas))
    ).all()
    return {mla: (listing, logistic) for mla, listing, logistic in rows}


def _unidades_vendidas(db: Session, item_id: int, desde: datetime) -> dict[str, int]:
    """Units of the product sold per MLA since `desde` (served by `ix_ml_sale_lines_product_group_date`)."""
    rows = db.execute(
        select(MlSaleLine.mla, func.sum(MlSaleLine.qty))
        .where(MlSaleLine.product == item_id, MlSaleLine.group_date >= desde)
        .group_by(MlSaleLine.mla)
    ).all()
    return {mla: int(units or 0) for mla, units in rows}


def _precio_con_envio(
    *,
    precio: float,
    iva: float,
    costo_ars: float,
    comision_base_pct: Optional[float],
    costo_envio: Optional[float],
    constantes: Mapping[str, float],
) -> tuple[Optional[float], Optional[float]]:
    """(markup %, ganancia ARS) of `precio` with the given shipping cost, through the existing calculator, the
    same calls `GET /precios/calcular-markup` makes. (None, None) when the cost or the commission is unknown.

    `calcular_limpio` gets no session: its only use of one is the group-average fallback for a zero cost above
    the threshold, which `_envio_actual` resolves ONCE per request instead of once per publication."""
    if costo_envio is None or comision_base_pct is None:
        return None, None
    comisiones = calcular_comision_ml_total(precio, comision_base_pct, iva, constantes=dict(constantes))
    limpio = calcular_limpio(precio, iva, costo_envio, comisiones["comision_total"], constantes=dict(constantes))
    return calcular_markup(limpio, costo_ars) * 100, limpio - costo_ars


def _promedios(variantes: list[dict[str, Any]]) -> tuple[Optional[dict], Optional[dict]]:
    priced = [v for v in variantes if v["_markup"] is not None]
    if not priced:
        return None, None
    simple = {
        "markup_pct": round(sum(v["_markup"] for v in priced) / len(priced), 2),
        "ganancia": round(sum(v["_ganancia"] for v in priced) / len(priced), 2),
        "publicaciones": len(priced),
    }
    unidades = sum(v["unidades_vendidas"] for v in priced)
    if unidades == 0:
        return simple, None
    ponderado = {
        "markup_pct": round(sum(v["_markup"] * v["unidades_vendidas"] for v in priced) / unidades, 2),
        "ganancia": round(sum(v["_ganancia"] * v["unidades_vendidas"] for v in priced) / unidades, 2),
        "unidades": unidades,
    }
    return simple, ponderado


def _motivo(comision: Optional[float], costo_envio: Optional[float]) -> Optional[str]:
    """Why a publication has no markup: no commission for its price list, or no shipping cost where it counts."""
    if comision is None:
        return MOTIVO_SIN_COMISION
    if costo_envio is None:
        return MOTIVO_SIN_COSTO_ENVIO
    return None


def _costos(mlas: list[str], item_id: int) -> dict[str, float]:
    """Each MLA's list_cost; on a failed mlwebhook read, `{}` and a warning, so it is not mistaken for no data."""
    try:
        return costos_envio_por_mla(mlas)
    except Exception as exc:
        logger.warning("No se pudo consultar ml_seller_shipping_costs (producto %s): %s", item_id, exc)
        return {}


def _envio_actual(
    db: Session, costos: Mapping[str, float], envio_erp: Optional[float], envio_aplica: bool, grupo_id: int
) -> tuple[float, str]:
    """Today's shipping cost and its origin: MAX(list_cost), else the ERP `envio`, else (a zero cost where shipping
    counts) the group average `calcular_limpio` would look up, the same `obtener_envio_promedio_grupo`."""
    envio = costo_envio_maximo(costos, envio_erp)
    if costos:
        return envio, ORIGEN_MAX
    if envio == 0 and envio_aplica:
        return obtener_envio_promedio_grupo(db, grupo_id), ORIGEN_GRUPO_PROMEDIO
    return envio, ORIGEN_ERP


def _round(value: Optional[float]) -> Optional[float]:
    return None if value is None else round(value, 2)


def calcular_variantes_envio(
    db: Session,
    producto: ProductoERP,
    precio: float,
    costo_ars: float,
    *,
    pricelist_actual: int = PRICELIST_CLASICA,
    ahora: Optional[datetime] = None,
) -> dict[str, Any]:
    """The variants, the averages and today's value of `precio` for `producto` (see the module docstring)."""
    ahora = ahora or datetime.now(UTC)
    iva = producto.iva
    constantes = obtener_constantes_pricing(db)
    grupo_id = obtener_grupo_subcategoria(db, producto.subcategoria_id)

    publicaciones = _publicaciones_activas(db, producto.item_id)
    mlas = [mla for mla, _ in publicaciones]
    costos = _costos(mlas, producto.item_id) if mlas else {}
    datos = _datos_ml(db, mlas) if mlas else {}
    unidades = _unidades_vendidas(db, producto.item_id, ahora - timedelta(days=VENTANA_DIAS)) if mlas else {}

    listas = {pl for _, pl in publicaciones if pl is not None} | {pricelist_actual}
    comisiones = {pl: obtener_comision_base(db, pl, grupo_id) for pl in sorted(listas)}

    envio_aplica = envio_cuenta(precio, constantes)
    envio_actual, origen_actual = _envio_actual(db, costos, producto.envio, envio_aplica, grupo_id)
    comun = {"precio": precio, "iva": iva, "costo_ars": costo_ars, "constantes": constantes}

    variantes: list[dict[str, Any]] = []
    for mla, pricelist_id in publicaciones:
        listing, logistic = datos.get(mla, (None, None))
        comision = comisiones.get(pricelist_id) if pricelist_id is not None else None
        costo_envio = costos.get(mla)
        # Below the threshold shipping never reaches the markup, so a missing cost does not block pricing.
        envio_para_precio = costo_envio if costo_envio is not None or envio_aplica else 0.0
        markup, ganancia = _precio_con_envio(comision_base_pct=comision, costo_envio=envio_para_precio, **comun)
        markup_actual, _ = _precio_con_envio(comision_base_pct=comision, costo_envio=envio_actual, **comun)
        variantes.append(
            {
                "mla": mla,
                "pricelist_id": pricelist_id,
                "listing_type": listing,
                "logistic_type": logistic,
                "logistica": LOGISTICA_POR_TIPO.get(logistic) if logistic else None,
                "costo_envio": costo_envio,
                "sin_costo_envio": costo_envio is None,
                "sin_precio_motivo": _motivo(comision, envio_para_precio),
                "comision_base_pct": comision,
                "markup_pct": _round(markup),
                "ganancia": _round(ganancia),
                "markup_pct_actual": _round(markup_actual),
                "unidades_vendidas": unidades.get(mla, 0),
                "_markup": markup,
                "_ganancia": ganancia,
            }
        )

    promedio_simple, promedio_ponderado = _promedios(variantes)
    comision_actual = comisiones[pricelist_actual]
    markup_hoy, ganancia_hoy = _precio_con_envio(comision_base_pct=comision_actual, costo_envio=envio_actual, **comun)
    for v in variantes:
        del v["_markup"], v["_ganancia"]

    return {
        "umbral_envio_gratis": constantes["monto_tier3"],
        "envio_aplica": envio_aplica,
        "ventana_dias": VENTANA_DIAS,
        "ponderacion": PONDERACION,
        "variantes": variantes,
        "publicaciones_sin_costo_envio": [v["mla"] for v in variantes if v["sin_costo_envio"]],
        "publicaciones_sin_precio": [
            {"mla": v["mla"], "motivo": v["sin_precio_motivo"]} for v in variantes if v["sin_precio_motivo"]
        ],
        "promedio_simple": promedio_simple,
        "promedio_ponderado": promedio_ponderado,
        "actual": {
            "costo_envio": envio_actual,
            "origen": origen_actual,
            "pricelist_id": pricelist_actual,
            "comision_base_pct": comision_actual,
            "markup_pct": _round(markup_hoy),
            "ganancia": _round(ganancia_hoy),
        },
    }
