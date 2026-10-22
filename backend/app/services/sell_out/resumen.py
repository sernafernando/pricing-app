"""What each sell-out campaign credited, read for the sell-out screen (sell-in-sell-out T7 S5).

Read only. Everything comes from what the allocator already wrote or holds:
- the credited rows (`sell_out_consumos`, `asignacion.recalcular`): lines,
  units and amount in the campaign currency, also per channel;
- the ARS amount: each row's `monto x tc_venta`, rounded to cents half up like
  `tope` rounds amounts, summed (an ARS campaign's rows are already ARS). The
  allocator writes `tc_venta` by the campaign's `tc_modo`, so its rules are not
  repeated here. An `al_cobro` campaign whose rate is not set yet is an
  estimate at the latest BNA (`ars_estimado`). A USD row without its rate
  leaves the ARS amount unknown (None), never a partial sum;
- `pendientes_base`: the percentage sales the rebuild skips while their base
  is unknown, counted with the allocator's own rule (`asignacion.base_desconocida`)
  over the same sales (`alcance`), since the rebuild does not store them;
- `recalculo`, the rebuild state: `recalculando` while the allocator holds the
  campaign's advisory lock, `fallida` when the queue row carries an error
  (`detenida` once it is parked after `queue.MAX_ATTEMPTS`, until something
  queues it again), `en_cola` while queued, else `al_dia`.

The query count is fixed for a whole page, whatever the number of campaigns.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.models.producto import ProductoERP
from app.models.sell_out import SellOutCampana, SellOutConsumo, SellOutDirty
from app.services.sell_out import alcance, asignacion, campanas as campanas_service, queue
from app.services.sell_out.tope import cents

CANALES = ("ml", "fuera", "tn")

# Two-key advisory locks show the first key as `classid` and the second as `objid`, with `objsubid` 2.
_EN_CURSO_SQL = text(
    "SELECT DISTINCT objid FROM pg_locks WHERE locktype = 'advisory' AND granted AND objsubid = 2 "
    "AND classid = :ns AND objid = ANY(CAST(:ids AS oid[]))"
)


def _ars(campana: SellOutCampana, monto: Decimal, tc_venta: Optional[Decimal]) -> Optional[Decimal]:
    if campana.moneda == "ARS":
        return monto
    return None if tc_venta is None else cents(Decimal(monto) * Decimal(tc_venta))


def ars_estimado(campana: SellOutCampana) -> bool:
    return campana.moneda == "USD" and campana.tc_modo == "al_cobro" and campana.tipo_cambio is None


def _montos(db: Session, campanas: Dict[int, SellOutCampana]) -> Dict[int, Dict[str, tuple]]:
    """`{campana_id: {canal: (lineas, unidades, monto, monto_ars, sin_tasa)}}` in one query."""
    t = SellOutConsumo
    ars_fila = func.round(t.monto * t.tc_venta, 2)
    rows = (
        db.query(
            t.campana_id,
            t.canal,
            func.count(),
            func.sum(t.unidades),
            func.sum(t.monto),
            func.sum(ars_fila),
            func.count() - func.count(t.tc_venta),
        )
        .filter(t.campana_id.in_(list(campanas)))
        .group_by(t.campana_id, t.canal)
    )
    salida: Dict[int, Dict[str, tuple]] = defaultdict(dict)
    for cid, canal, lineas, unidades, monto, monto_ars, sin_tasa in rows:
        salida[cid][canal] = (int(lineas), int(unidades), Decimal(monto), monto_ars, int(sin_tasa))
    return salida


def _pendientes_base(db: Session, campanas: List[SellOutCampana]) -> Dict[int, int]:
    porcentaje = [c for c in campanas if c.estado == "activa" and c.tipo == "porcentaje"]
    productos = alcance.productos(db, [c.id for c in porcentaje])
    items = {item for alcanzados in productos.values() for item in alcanzados}
    if not items:
        return {}
    desde = min(c.fecha_desde for c in porcentaje)
    ventas = alcance.ventas(db, items, desde, max(c.fecha_hasta for c in porcentaje))
    salida: Dict[int, int] = {}
    for c in porcentaje:
        alcanzados = productos.get(c.id, {})
        salida[c.id] = sum(
            1
            for v in ventas
            if v.item_id in alcanzados and alcance.en_campana(c, v) and asignacion.base_desconocida(c, v)
        )
    return salida


def _recalculos(db: Session, ids: List[int]) -> Tuple[Dict[int, SellOutDirty], set]:
    cola = {d.campana_id: d for d in db.query(SellOutDirty).filter(SellOutDirty.campana_id.in_(ids))}
    en_curso: set = set()
    if db.get_bind().dialect.name == "postgresql":  # the allocator only locks on Postgres
        en_curso = {int(r[0]) for r in db.execute(_EN_CURSO_SQL, {"ns": asignacion.LOCK_NAMESPACE, "ids": ids})}
    return cola, en_curso


def _recalculo(fila: Optional[SellOutDirty], en_curso: bool) -> dict:
    intentos = fila.attempts if fila is not None else 0
    error = fila.last_error if fila is not None else None
    if en_curso:
        estado = "recalculando"
    elif error is not None:
        estado = "fallida"
    elif fila is not None:
        estado = "en_cola"
    else:
        estado = "al_dia"
    return {
        "estado": estado,
        "intentos": intentos,
        "error": error,
        "detenida": intentos >= queue.MAX_ATTEMPTS,
        "encolada_en": fila.enqueued_at if fila is not None else None,
    }


def resumenes(db: Session, campanas: List[SellOutCampana]) -> Dict[int, dict]:
    """`{campana_id: summary}` for a page of campaigns (module docstring)."""
    por_id = {c.id: c for c in campanas}
    if not por_id:
        return {}
    ids = sorted(por_id)
    montos = _montos(db, por_id)
    pendientes = _pendientes_base(db, campanas)
    cola, en_curso = _recalculos(db, ids)
    salida = {}
    for cid, c in por_id.items():
        canales = montos.get(cid, {})
        lineas = sum(x[0] for x in canales.values())
        unidades = sum(x[1] for x in canales.values())
        monto = sum((x[2] for x in canales.values()), Decimal(0))
        if c.moneda == "ARS":
            monto_ars: Optional[Decimal] = monto
        elif any(x[4] for x in canales.values()):
            monto_ars = None
        else:
            monto_ars = sum((Decimal(str(x[3])) for x in canales.values()), Decimal(0))
        salida[cid] = {
            "lineas": lineas,
            "unidades": unidades,
            "monto": monto,
            "monto_ars": monto_ars,
            "ars_estimado": ars_estimado(c),
            "tope_unidades_restantes": None if c.tope_unidades is None else c.tope_unidades - unidades,
            "tope_monto_restante": None if c.tope_monto is None else Decimal(c.tope_monto) - monto,
            "por_canal": [
                {"canal": canal, "lineas": canales[canal][0], "unidades": canales[canal][1], "monto": canales[canal][2]}
                for canal in CANALES
                if canal in canales
            ],
            "pendientes_base": pendientes.get(cid, 0),
            "recalculo": _recalculo(cola.get(cid), cid in en_curso),
        }
    return salida


def serializar(db: Session, campanas: List[SellOutCampana]) -> List[dict]:
    """The campaigns as the API returns them: `campanas.serializar` plus each one's `resumen`."""
    por_id = resumenes(db, campanas)
    return [{**fila, "resumen": por_id[c.id]} for c, fila in zip(campanas, campanas_service.serializar(db, campanas))]


def consumos(db: Session, campana: SellOutCampana, *, page: int = 1, page_size: int = 50) -> Tuple[List[dict], int]:
    """One page of a campaign's credited lines, in sale order, and their total. A return inside the
    campaign is already netted into the row of the sale it returns (fewer units), as the allocator
    stores it: there are no negative rows."""
    t, p = SellOutConsumo, ProductoERP
    query = db.query(t).filter(t.campana_id == campana.id)
    total = query.count()
    rows = (
        db.query(t, p.codigo, p.descripcion)
        .outerjoin(p, p.item_id == t.item_id)
        .filter(t.campana_id == campana.id)
        .order_by(t.fecha_venta, t.canal, t.venta_ref)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return [
        {
            "id": x.id,
            "canal": x.canal,
            "venta_ref": x.venta_ref,
            "fecha_venta": x.fecha_venta,
            "item_id": x.item_id,
            "codigo": codigo,
            "descripcion": descripcion,
            "unidades": x.unidades,
            "monto": x.monto,
            "tc_venta": x.tc_venta,
            "monto_ars": _ars(campana, x.monto, x.tc_venta),
        }
        for x, codigo, descripcion in rows
    ], total
