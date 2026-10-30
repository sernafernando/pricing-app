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
  queues it again), `en_cola` while queued, else `al_dia`;
- `reparto`, a `monto_total` campaign's split only (T26c): what its shares
  assign, the shares of products with no written row (no sale in the dates:
  "Asignado sin ventas") and the total nobody was given ("Sin asignar"), by
  the allocator's own rule (`reparto.resumen_monto_total`); None amounts when
  the stored shares cannot be split as they stand (`reparto.RepartoInvalido`,
  e.g. a product without VAT on a campaign loaded with VAT), with `motivo`.

The query count is fixed for a whole page, whatever the number of campaigns.

`remanentes` (T26b2, owner: "Está bien que sume al total"): what the
`monto_total` campaigns ending in a period add to the Métricas ML totals with
no sale row to carry it, see its docstring.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models.producto import ProductoERP
from app.models.sell_out import SellOutCampana, SellOutConsumo, SellOutDirty
from app.models.tipo_cambio import TipoCambio
from app.services.sell_in.bonos import tasas_bna_por_fecha
from app.services.sell_out import alcance, asignacion, campanas as campanas_service, queue, reparto
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


# One row's ARS amount in SQL, like `_ars`: NULL for an ARS row (no rate) or a USD row without its rate.
ARS_FILA = func.round(SellOutConsumo.monto * SellOutConsumo.tc_venta, 2)


def monto_ars(
    campana: SellOutCampana, monto: Decimal, montos_ars_fila: Iterable[Optional[Decimal]], sin_tasa: int
) -> Optional[Decimal]:
    """The ARS amount of some of a campaign's rows, from their `monto` sum, their `ARS_FILA` sums and how
    many of them lack `tc_venta`: an ARS campaign's `monto` is already ARS; a row without its rate leaves
    it unknown (None), never a partial sum."""
    if campana.moneda == "ARS":
        return monto
    if sin_tasa:
        return None
    return sum((Decimal(str(x)) for x in montos_ars_fila), Decimal(0))


def _montos(db: Session, campanas: Dict[int, SellOutCampana]) -> Dict[int, Dict[str, tuple]]:
    """`{campana_id: {canal: (lineas, unidades, monto, monto_ars, sin_tasa)}}` in one query."""
    t = SellOutConsumo
    rows = (
        db.query(
            t.campana_id,
            t.canal,
            func.count(),
            func.sum(t.unidades),
            func.sum(t.monto),
            func.sum(ARS_FILA),
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


def _repartos(db: Session, campanas: List[SellOutCampana]) -> Dict[int, dict]:
    """`{campana_id: reparto summary}` of the `monto_total` campaigns, in at most three queries for the page."""
    total = [c for c in campanas if c.tipo == "monto_total"]
    if not total:
        return {}
    ids = [c.id for c in total]
    repartos = asignacion.repartos_item(db, total)
    con_iva = [c.id for c in total if c.monto_incluye_iva]
    ivas = alcance.productos(db, con_iva) if con_iva else {}
    con_ventas: Dict[int, set] = defaultdict(set)
    rows = db.query(SellOutConsumo.campana_id, SellOutConsumo.item_id).filter(SellOutConsumo.campana_id.in_(ids))
    for cid, item_id in rows.distinct():
        con_ventas[cid].add(item_id)
    salida = {}
    for c in total:
        mt = reparto.MontoTotal(Decimal(c.monto_total), repartos.get(c.id, {}), c.monto_incluye_iva, ivas.get(c.id, {}))
        try:
            r = reparto.resumen_monto_total(mt, con_ventas[c.id])
        # The stored shares cannot be split as they stand; anything else surfaces.
        except reparto.RepartoInvalido as exc:
            if exc.causa == "sin_iva" and exc.item_id not in ivas.get(c.id, {}):
                # No rate because the product left the reach (the rates come from it), not because it has no VAT.
                exc = reparto.RepartoInvalido(str(exc), causa="fuera_de_alcance", item_id=exc.item_id)
            motivo = campanas_service.mensaje_reparto(exc)
            salida[c.id] = {"asignado": None, "asignado_sin_ventas": None, "sin_asignar": None, "motivo": motivo}
            continue
        asignado = cents(Decimal(c.monto_total)) - r["sin_asignar"]
        salida[c.id] = {"asignado": asignado, **r, "motivo": None}
    return salida


@dataclass(frozen=True)
class Remanente:
    """`remanentes`' result: the known ARS (`monto_ars`), how many campaigns are left out because their USD amount
    has no rate yet (`pendientes`, never read as 0) and how many are in at an estimated rate (`estimados`)."""

    monto_ars: Decimal
    pendientes: int
    estimados: int


def _ultima_bna(db: Session) -> Optional[Decimal]:
    fila = (
        db.query(TipoCambio.venta)
        .filter(TipoCambio.moneda == "USD", TipoCambio.venta > 0)
        .order_by(TipoCambio.fecha.desc(), TipoCambio.id.desc())
        .first()
    )
    return Decimal(str(fila[0])) if fila else None


def remanentes(db: Session, desde: date, hasta: date, item_ids: Any = None) -> Remanente:
    """What the ACTIVE `monto_total` campaigns whose `fecha_hasta` is in `desde`..`hasta` add to the Métricas ML
    totals with no sale row to carry it (T26b2, S34/S35/S37): once per campaign, its "Asignado sin ventas" plus its
    "Sin asignar", as the panel shows them (`_repartos`: a share net of its own product's VAT when loaded with VAT,
    the remainder as loaded, since it is applied to no product), in ARS. A USD amount converts at the rate the
    allocator would give a sale on `fecha_hasta` (`asignacion._tasa`: the campaign's own rate, the BNA of that
    date, or for `al_cobro` without its rate the latest BNA, an estimate); with no rate it is pending, never 0.
    Shares that cannot be split as they stand count nothing (the allocator fails the campaign too).

    `item_ids` (a selectable or list of product ids, or None for every product): only the campaigns whose groups
    reach one of them count (the board's filtered products).

    Statements: the lookup alone when no campaign matches; else at most six, whatever the number of campaigns."""
    c = SellOutCampana
    ids_q = select(c.id).where(c.tipo == "monto_total", c.estado == "activa", c.fecha_hasta.between(desde, hasta))
    if item_ids is not None:
        ids_q = ids_q.where(c.id.in_(alcance.campanas_que_alcanzan(db, item_ids).subquery().select()))
    ids = [int(i) for (i,) in db.execute(ids_q)]
    if not ids:
        return Remanente(Decimal("0"), 0, 0)
    campanas = db.query(c).filter(c.id.in_(ids)).order_by(c.id).all()
    repartos = _repartos(db, campanas)
    usd = [x for x in campanas if x.moneda == "USD"]
    por_dia = tasas_bna_por_fecha(db, {x.fecha_hasta for x in usd if x.tc_modo == "dia_venta"})
    sin_tasa = any(x.tc_modo == "al_cobro" and x.tipo_cambio is None for x in usd)
    tasas = asignacion._Tasas(por_dia, _ultima_bna(db) if sin_tasa else None)
    total, pendientes, estimados = Decimal("0"), 0, 0
    for x in campanas:
        r = repartos[x.id]
        if r["motivo"] is not None:
            continue
        monto = r["asignado_sin_ventas"] + r["sin_asignar"]
        if x.moneda == "USD":
            try:
                tasa = asignacion._tasa(x, x.fecha_hasta, tasas)
            except asignacion.SellOutAsignacionError:  # no rate yet
                pendientes += 1
                continue
            monto = cents(monto * tasa)
            estimados += int(ars_estimado(x))
        total += monto
    return Remanente(total, pendientes, estimados)


def resumenes(db: Session, campanas: List[SellOutCampana]) -> Dict[int, dict]:
    """`{campana_id: summary}` for a page of campaigns (module docstring)."""
    por_id = {c.id: c for c in campanas}
    if not por_id:
        return {}
    ids = sorted(por_id)
    montos = _montos(db, por_id)
    pendientes = _pendientes_base(db, campanas)
    cola, en_curso = _recalculos(db, ids)
    repartos = _repartos(db, campanas)
    salida = {}
    for cid, c in por_id.items():
        canales = montos.get(cid, {})
        lineas = sum(x[0] for x in canales.values())
        unidades = sum(x[1] for x in canales.values())
        monto = sum((x[2] for x in canales.values()), Decimal(0))
        salida[cid] = {
            "lineas": lineas,
            "unidades": unidades,
            "monto": monto,
            "monto_ars": monto_ars(c, monto, (x[3] for x in canales.values()), sum(x[4] for x in canales.values())),
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
        if cid in repartos:
            salida[cid]["reparto"] = repartos[cid]
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
