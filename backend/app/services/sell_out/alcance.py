"""Which sales a sell-out campaign reaches (sell-in-sell-out T7 S2).

Products: a campaign reaches every `productos_erp` row matched by a filter row
(`offset_grupo_filtros`) of any of its groups. Within a row the fields that are
set (`marca`, `categoria`, `subcategoria_id`, `item_id`; NULL, '' or 0 is
unset, like the legacy offsets) must ALL match, exactly; a product matching ANY
row is reached. A row with nothing set reaches nothing (fail-closed: the API
refuses it, a stray one must not reach the whole catalog).

Sales: every channel, all app-owned (`ml_sale_lines`, `ventas_fuera_ml_metricas`,
`ventas_tienda_nube_metricas`; ERP independence, owner 2026-10-17), read the way
the sell-in allocation reads them (`sell_in.costing`): ML `item_row_id`, `day`,
`qty`; fuera / TN `it_transaction`, the UTC date of `fecha_venta` and `signo *
cantidad`, a return's original sale resolved by `costing._objetivos`. A sale
belongs to a campaign when it is dated inside its inclusive range; a return from
the campaign's first day on, with no end, so a credited unit returned after the
campaign ends loses its credit (`tope.asignar` frees it from its sale).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import Dict, Iterable, List, Optional, Set, Tuple

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.models.ml_sale_line import MlSaleLine
from app.models.offset_grupo_filtro import OffsetGrupoFiltro
from app.models.producto import ProductoERP
from app.models.sell_out import SellOutCampana, SellOutCampanaGrupo
from app.services.sell_in.costing import _VENTAS_FACTURADAS, _objetivos, _unidades, _utc_date


@dataclass(frozen=True)
class Venta:
    canal: str
    venta_ref: int
    item_id: int
    fecha: date
    unidades: int  # negative: a return
    objetivo: Optional[Tuple[str, int]] = None  # a return's original sale, when resolved


def _texto(columna, producto):
    return or_(func.coalesce(columna, "") == "", producto == columna)


def _numero(columna, producto):
    return or_(func.coalesce(columna, 0) == 0, producto == columna)


def productos(db: Session, campana_ids: Iterable[int]) -> Dict[int, Dict[int, Optional[Decimal]]]:
    """`{campana_id: {item_id: iva_pct}}` of the given campaigns, in ONE query; a campaign
    reaching nothing is absent."""
    ids = sorted({int(i) for i in campana_ids})
    if not ids:
        return {}
    f, p = OffsetGrupoFiltro, ProductoERP
    algo = or_(
        func.coalesce(f.marca, "") != "",
        func.coalesce(f.categoria, "") != "",
        func.coalesce(f.subcategoria_id, 0) != 0,
        func.coalesce(f.item_id, 0) != 0,
    )
    coincide = and_(
        algo,
        _texto(f.marca, p.marca),
        _texto(f.categoria, p.categoria),
        _numero(f.subcategoria_id, p.subcategoria_id),
        _numero(f.item_id, p.item_id),
    )
    rows = (
        db.query(SellOutCampanaGrupo.campana_id, p.item_id, p.iva)
        .join(f, f.grupo_id == SellOutCampanaGrupo.grupo_id)
        .join(p, coincide)
        .filter(SellOutCampanaGrupo.campana_id.in_(ids))
        .distinct()
    )
    salida: Dict[int, Dict[int, Optional[Decimal]]] = defaultdict(dict)
    for campana_id, item_id, iva in rows:
        salida[campana_id][item_id] = Decimal(str(iva)) if iva is not None else None
    return dict(salida)


def en_campana(campana: SellOutCampana, venta: Venta) -> bool:
    if venta.unidades < 0:
        return venta.fecha >= campana.fecha_desde
    return campana.fecha_desde <= venta.fecha <= campana.fecha_hasta


def ventas(db: Session, item_ids: Set[int], desde: date, hasta: date) -> List[Venta]:
    """The sales of `item_ids` dated `desde`..`hasta` and their returns from `desde` on, every
    channel: one query per channel plus one per channel with returns (their original sales)."""
    if not item_ids:
        return []
    ids = sorted(item_ids)
    salida = [
        Venta("ml", ref, item_id, dia, int(qty))
        for ref, item_id, dia, qty in db.query(
            MlSaleLine.item_row_id, MlSaleLine.product, MlSaleLine.day, MlSaleLine.qty
        ).filter(MlSaleLine.product.in_(ids), MlSaleLine.day.between(desde, hasta), MlSaleLine.qty > 0)
    ]
    inicio = datetime.combine(desde, time(0), tzinfo=timezone.utc)
    fin = datetime.combine(hasta, time.max, tzinfo=timezone.utc)
    for canal, model in _VENTAS_FACTURADAS:
        rows = db.query(
            model.it_transaction, model.item_id, model.fecha_venta, model.signo, model.cantidad, model.cust_id
        ).filter(
            model.item_id.in_(ids),
            model.fecha_venta >= inicio,
            or_(model.fecha_venta <= fin, func.coalesce(model.signo, 1) * model.cantidad < 0),
        )
        devoluciones = []
        for ref, item_id, fecha, signo, cantidad, cust_id in rows:
            unidades = _unidades(signo, cantidad)
            if unidades > 0:  # the query only reads positive lines up to `hasta`
                salida.append(Venta(canal, ref, item_id, _utc_date(fecha), unidades))
            elif unidades < 0:
                devoluciones.append((ref, item_id, _utc_date(fecha), unidades, cust_id))
        objetivos = _objetivos(db, model, devoluciones)
        for ref, item_id, fecha, unidades, _ in devoluciones:
            objetivo = objetivos.get(ref)
            salida.append(Venta(canal, ref, item_id, fecha, unidades, (canal, objetivo) if objetivo else None))
    return salida
