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
cantidad`, a return's original sale resolved by `costing.resolver_objetivos`. A sale
belongs to a campaign when it is dated inside its inclusive range, and so does a
return: only a return dated inside it frees units (`tope.asignar`). A return
dated after the end keeps the credit of its sale (owner, 2026-10-21: "si el
producto se devuelve después del cierre de la campaña computa como venta").
Every campaign has an end (`fecha_hasta` is NOT NULL).

Each sale also carries, per unit and in ARS, what a percentage campaign needs,
as recorded ON THE SALE (never the current `productos_erp.costo`); None when
unknown:
- cost without VAT: ML `mcosto / qty` (the line's share of the order's frozen
  cost of goods; 0 means unknown), fuera / TN `costo_total / units`;
- price: ML `gross / qty` (unit price x qty, WITH VAT; 0 means unknown: an
  unsettled or non-ARS order), fuera / TN `monto_total / units` (without VAT).
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
from app.services.sell_in.costing import VENTAS_FACTURADAS, resolver_objetivos, unidades_firmadas, utc_date


@dataclass(frozen=True)
class Venta:
    canal: str
    venta_ref: int
    item_id: int
    fecha: date
    unidades: int  # negative: a return
    objetivo: Optional[Tuple[str, int]] = None  # a return's original sale, when resolved
    costo_unit: Optional[Decimal] = None  # ARS, without VAT
    precio_unit: Optional[Decimal] = None  # ARS; with VAT when `precio_con_iva`
    precio_con_iva: bool = False


def _positivo(x: Decimal) -> bool:
    return x > 0


def _no_negativo(x: Decimal) -> bool:
    return x >= 0


def _por_unidad(total, unidades: int, conocido) -> Optional[Decimal]:
    return Decimal(total) / unidades if total is not None and conocido(Decimal(total)) else None


def _texto(columna, producto):
    return or_(func.coalesce(columna, "") == "", producto == columna)


def _numero(columna, producto):
    return or_(func.coalesce(columna, 0) == 0, producto == columna)


def _alcanzados(db: Session, *columnas):
    """`columnas` over every (campaign, product) pair a filter row of the campaign's groups reaches."""
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
    return (
        db.query(*columnas)
        .select_from(SellOutCampanaGrupo)
        .join(f, f.grupo_id == SellOutCampanaGrupo.grupo_id)
        .join(p, coincide)
    )


def productos(db: Session, campana_ids: Iterable[int]) -> Dict[int, Dict[int, Optional[Decimal]]]:
    """`{campana_id: {item_id: iva_pct}}` of the given campaigns, in ONE query; a campaign
    reaching nothing is absent."""
    ids = sorted({int(i) for i in campana_ids})
    if not ids:
        return {}
    p = ProductoERP
    rows = (
        _alcanzados(db, SellOutCampanaGrupo.campana_id, p.item_id, p.iva)
        .filter(SellOutCampanaGrupo.campana_id.in_(ids))
        .distinct()
    )
    salida: Dict[int, Dict[int, Optional[Decimal]]] = defaultdict(dict)
    for campana_id, item_id, iva in rows:
        salida[campana_id][item_id] = Decimal(str(iva)) if iva is not None else None
    return dict(salida)


def campanas_por_venta(db: Session, ventas: Iterable[Tuple[int, date]]) -> Set[int]:
    """The ACTIVE campaigns reaching some `(item_id, fecha)` sale inside their range, in ONE query
    over the sales' products and overall dates (sell-out queue fan-out, T7 S3)."""
    ventas = set(ventas)
    if not ventas:
        return set()
    c, g = SellOutCampana, SellOutCampanaGrupo
    rows = (
        _alcanzados(db, c.id, ProductoERP.item_id, c.fecha_desde, c.fecha_hasta)
        .join(c, c.id == g.campana_id)
        .filter(
            c.estado == "activa",
            ProductoERP.item_id.in_(sorted({item for item, _ in ventas})),
            c.fecha_desde <= max(dia for _, dia in ventas),
            c.fecha_hasta >= min(dia for _, dia in ventas),
        )
        .distinct()
    )
    fechas: Dict[int, Set[date]] = defaultdict(set)
    for item, dia in ventas:
        fechas[item].add(dia)
    return {cid for cid, item, desde, hasta in rows if any(desde <= dia <= hasta for dia in fechas[item])}


def en_campana(campana: SellOutCampana, venta: Venta) -> bool:
    """Sales and returns alike: inside the campaign's inclusive range (module docstring)."""
    return campana.fecha_desde <= venta.fecha <= campana.fecha_hasta


def ventas(db: Session, item_ids: Set[int], desde: date, hasta: date) -> List[Venta]:
    """The sales and returns of `item_ids` dated `desde`..`hasta`, every channel: one query per
    channel plus one per channel with returns (their original sales)."""
    if not item_ids:
        return []
    ids = sorted(item_ids)
    salida = [
        Venta(
            "ml",
            ref,
            item_id,
            dia,
            int(qty),
            costo_unit=_por_unidad(mcosto, qty, _positivo),
            precio_unit=_por_unidad(gross, qty, _positivo),
            precio_con_iva=True,
        )
        for ref, item_id, dia, qty, gross, mcosto in db.query(
            MlSaleLine.item_row_id,
            MlSaleLine.product,
            MlSaleLine.day,
            MlSaleLine.qty,
            MlSaleLine.gross,
            MlSaleLine.mcosto,
        ).filter(MlSaleLine.product.in_(ids), MlSaleLine.day.between(desde, hasta), MlSaleLine.qty > 0)
    ]
    inicio = datetime.combine(desde, time(0), tzinfo=timezone.utc)
    fin = datetime.combine(hasta, time.max, tzinfo=timezone.utc)
    for canal, model in VENTAS_FACTURADAS:
        rows = db.query(
            model.it_transaction,
            model.item_id,
            model.fecha_venta,
            model.signo,
            model.cantidad,
            model.cust_id,
            model.monto_total,
            model.costo_total,
        ).filter(
            model.item_id.in_(ids),
            model.fecha_venta >= inicio,
            model.fecha_venta <= fin,
        )
        devoluciones = []
        for ref, item_id, fecha, signo, cantidad, cust_id, monto, costo in rows:
            unidades = unidades_firmadas(signo, cantidad)
            if unidades > 0:
                costo_unit = _por_unidad(costo, unidades, _positivo)
                precio_unit = _por_unidad(monto, unidades, _no_negativo)
                salida.append(Venta(canal, ref, item_id, utc_date(fecha), unidades, None, costo_unit, precio_unit))
            elif unidades < 0:
                devoluciones.append((ref, item_id, utc_date(fecha), unidades, cust_id))
        objetivos = resolver_objetivos(db, model, devoluciones)
        for ref, item_id, fecha, unidades, _ in devoluciones:
            objetivo = objetivos.get(ref)
            salida.append(Venta(canal, ref, item_id, fecha, unidades, (canal, objetivo) if objetivo else None))
    return salida
