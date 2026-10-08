"""Shared pricing context: the per-request prefetch behind the markup maths.

The Productos listing used to build this inline (exchange rate, pricing
constants, subcategory -> grupo map, active commission version, per-grupo
shipping average) and close over it in two helpers, `_lookup_comision` and
`_resolve_envio`. Moving it here lets a second screen (Publicaciones ML) compute
the SAME markup from the SAME inputs without a parallel formula.

This is a lift, not a rewrite: `build_pricing_context` issues exactly the
queries the endpoint issued, in the same order, and the methods return exactly
what the closures returned. `tests/integration/test_productos_listing_golden.py`
pins the listing output byte for byte across the move.

Build it ONCE per request (about 7 statements, independent of how many rows the
caller then prices) and pass it around; it is immutable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Mapping, Optional

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.models.comision_config import SubcategoriaGrupo
from app.models.comision_versionada import ComisionAdicionalCuota, ComisionBase, ComisionVersion
from app.models.producto import ProductoERP
from app.services.pricing_calculator import (
    GRUPO_DEFAULT,
    convertir_a_pesos,
    obtener_constantes_pricing,
    obtener_tipo_cambio_actual,
)
from app.services.pricing_columns import CUOTAS_BY_PRICELIST, PVP_TO_WEB_PRICELIST

# Used when the pricing constants row is missing (same literal the endpoint used).
_MONTO_TIER3_FALLBACK = 33000


@dataclass(frozen=True)
class PricingContext:
    hoy: date
    tipo_cambio_usd: Optional[float]
    constantes: Optional[dict]
    subcat_to_grupo: Mapping[int, int]
    active_version_id: Optional[int]
    comision_base: Mapping[int, float]  # grupo_id -> base commission of the active version
    comision_adicional: Mapping[int, float]  # cuotas -> surcharge of the active version
    envio_promedio_by_grupo: Mapping[int, float]

    def grupo_of(self, subcategoria_id) -> int:
        """Commission grupo of a subcategory; `GRUPO_DEFAULT` when unmapped."""
        return self.subcat_to_grupo.get(subcategoria_id, GRUPO_DEFAULT)

    def comision(self, pricelist_id: int, grupo_id: int) -> Optional[float]:
        """Pure dict lookup replacement for `obtener_comision_base`.

        PVP lists resolve through their web equivalent; installment lists add
        the version's surcharge for their number of cuotas. `None` when there is
        no active version or no base for the grupo.
        """
        resolved_pl = PVP_TO_WEB_PRICELIST.get(pricelist_id, pricelist_id)
        if self.active_version_id is None:
            return None
        base = self.comision_base.get(grupo_id)
        if base is None:
            return None
        if resolved_pl == 4:
            return base
        cuotas = CUOTAS_BY_PRICELIST.get(resolved_pl)
        if cuotas is None:
            return base
        adicional = self.comision_adicional.get(cuotas, 0)
        return base + adicional

    def costo_en_pesos(self, costo: float, moneda) -> float:
        """`convertir_a_pesos` with the prefetched USD rate (only used for USD)."""
        tipo_cambio = self.tipo_cambio_usd if moneda == "USD" else None
        return convertir_a_pesos(costo, moneda, tipo_cambio)


def build_pricing_context(db: Session, hoy: Optional[date] = None) -> PricingContext:
    """Run the markup prefetch (rate, constants, grupos, commissions, shipping averages)."""
    hoy = hoy or date.today()

    tipo_cambio_usd = obtener_tipo_cambio_actual(db, "USD")
    constantes = obtener_constantes_pricing(db)

    all_subcat_grupos = db.query(SubcategoriaGrupo).all()
    subcat_to_grupo = {sg.subcat_id: sg.grupo_id for sg in all_subcat_grupos}

    active_version = (
        db.query(ComisionVersion)
        .filter(
            and_(
                ComisionVersion.fecha_desde <= hoy,
                or_(ComisionVersion.fecha_hasta.is_(None), ComisionVersion.fecha_hasta >= hoy),
                ComisionVersion.activo == True,  # noqa: E712 (SQL comparison)
            )
        )
        .first()
    )
    comision_base: dict = {}
    comision_adicional: dict = {}
    if active_version:
        for cb in db.query(ComisionBase).filter(ComisionBase.version_id == active_version.id).all():
            comision_base[cb.grupo_id] = float(cb.comision_base)
        for ca in db.query(ComisionAdicionalCuota).filter(ComisionAdicionalCuota.version_id == active_version.id).all():
            comision_adicional[ca.cuotas] = float(ca.adicional)

    unique_grupo_ids = set(subcat_to_grupo.values())
    envio_promedio_by_grupo: dict = {gid: 0.0 for gid in unique_grupo_ids}
    # Reverse map: grupo_id -> [subcat_ids]
    grupo_to_subcats: dict = {}
    for sc_id, g_id in subcat_to_grupo.items():
        grupo_to_subcats.setdefault(g_id, []).append(sc_id)
    all_subcat_ids_envio = list(subcat_to_grupo.keys())
    if all_subcat_ids_envio:
        envio_rows = (
            db.query(ProductoERP.subcategoria_id, func.avg(ProductoERP.envio))
            .filter(
                ProductoERP.subcategoria_id.in_(all_subcat_ids_envio),
                ProductoERP.activo == True,  # noqa: E712 (SQL comparison)
                ProductoERP.envio > 0,
            )
            .group_by(ProductoERP.subcategoria_id)
            .all()
        )
        subcat_envio_avg = {sc_id: float(avg_val) for sc_id, avg_val in envio_rows}
        for gid, sc_list in grupo_to_subcats.items():
            vals = [subcat_envio_avg[sc] for sc in sc_list if sc in subcat_envio_avg]
            if vals:
                envio_promedio_by_grupo[gid] = sum(vals) / len(vals)

    return PricingContext(
        hoy=hoy,
        tipo_cambio_usd=tipo_cambio_usd,
        constantes=constantes,
        subcat_to_grupo=subcat_to_grupo,
        active_version_id=active_version.id if active_version else None,
        comision_base=comision_base,
        comision_adicional=comision_adicional,
        envio_promedio_by_grupo=envio_promedio_by_grupo,
    )


def resolve_envio(
    ctx: PricingContext,
    envio_real_by_item: Mapping[int, float],
    item_id: int,
    producto_envio: float,
    grupo_id: int,
    precio: float,
) -> float:
    """Resolve costo_envio: real mlwebhook cost first, then the grupo average fallback.

    Bind `ctx` and `envio_real_by_item` with `functools.partial` to get the
    `(item_id, producto_envio, grupo_id, precio)` shape the listing loop calls.
    """
    # Real cost from the mlwebhook DB (already resolved as a batch)
    real_cost = envio_real_by_item.get(item_id)
    if real_cost is not None:
        return real_cost
    # ERP + grupo-average fallback
    costo_envio = producto_envio or 0
    montot3 = ctx.constantes["monto_tier3"] if ctx.constantes else _MONTO_TIER3_FALLBACK
    if costo_envio == 0 and precio >= montot3 and grupo_id is not None:
        costo_envio = ctx.envio_promedio_by_grupo.get(grupo_id, 0.0)
    return costo_envio
