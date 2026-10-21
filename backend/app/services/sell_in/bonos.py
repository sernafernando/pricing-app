"""Brand bonus reconcile (sell-in-sell-out T3c-3).

A brand bonus (`SellInBonoMarca`) pays `monto_unit` per INVOICED unit of its
brand (owner 2026-10-19: "es sobre lo facturado, no importa lo recibido";
invoiced 100 with a credit note of 10 pays "sobre 90") on every Compras
operation whose supplier invoice date (`pedidos_compra.fecha_factura`) falls in
its range. It is applied by itself (owner: "los pedidos se tienen que aplicar
solos a esa marca"): `reconciliar` keeps ONE sell-in purchase per (bonus,
operation) in step with the rules below. The full reconcile script runs it
for every bonus; the queue's consumer (the `sell_in.bono` worker, shipped on
its own) runs it for every queued change (`bono_queue`).

Desired state of a pair, recomputed from scratch on every call:

- it applies when the bonus is `activa`, the operation exists, is not
  `cancelado`/`rechazado`, has an invoice date inside the bonus's inclusive
  range, and has invoiced units (`pedido_compra_lineas_facturadas`, net of
  credit notes) of items whose `productos_erp.marca` is the bonus's brand
  (exact match, like the list's brand filter);
- then its purchase holds one line per such item: `cantidad` = invoiced units,
  `monto_asignado` = units x `monto_unit` (`formula = 'por_unidad'`), in the
  bonus's currency, dated the invoice date (`cuenta_desde = 'compra'`), of the
  operation's supplier, linked to the operation (`sell_in_compra_pedidos` and
  `pedido_compra_id`), authored by the bonus's author;
- a USD bonus converts at the operation's own rate (`pedidos_compra.tipo_cambio`,
  the effective rate the Compras module keeps), like every sell in (owner
  2026-10-17: the purchase's own rate). An operation without one (an ARS
  operation) takes the BNA rate of its invoice date (`tipo_cambio`, USD venta,
  the latest on or before it). With no rate at all the pair FAILS
  (`ReconcileResult.fallidas`) and is left as it was: never a guessed rate.

Writes, set against what is stored:

- no purchase and it applies → created (audit `SELL_IN_COMPRA_CREADA` per line);
- a purchase and it no longer applies → voided once (`SELL_IN_COMPRA_ANULADA`);
- a purchase and it applies with different units, amounts, dates, rate,
  supplier or estado → updated IN PLACE (a voided one is reactivated: the pair
  keeps one purchase for good), lines added, changed or removed, and one audit
  row with the lines before and after (`SELL_IN_COMPRA_BONO_ACTUALIZADA`);
- otherwise nothing: a re-run writes nothing. A line's `costo_base_unit` is the
  product's cost frozen when the line is first written, never refreshed.

Every product a write touches is recomputed through the active
`SellInCosting` in the same transaction, the way loading or voiding a manual
purchase does, so the consumptions (`sell_in_consumos`) always match. Manual
purchases (`origen = 'manual'`) are never read nor written here. A generated
purchase whose operation was deleted (`bono_pedido_id` set NULL by its FK) is
voided by any call.

ERP independence (owner, 2026-10-17): reads only app tables (`sell_in_*`,
`pedidos_compra`, `pedido_compra_lineas_facturadas`, `productos_erp`,
`tipo_cambio`), never `tb_*`.

Concurrency: before reading what is stored, every call takes
`pg_advisory_xact_lock(LOCK_NAMESPACE, bono_id)` for every bonus involved, in id
order, so two calls never generate the same pair twice (the partial unique
index `uq_sell_in_compras_bono_pedido` backs it). The costing's per-product
locks come after, in the same order everywhere.
"""

from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Dict, Iterable, List, Optional, Set, Tuple

from sqlalchemy import and_, func, or_, text
from sqlalchemy.orm import Session

from app.models.auditoria import Auditoria, TipoAccion
from app.models.pedido_compra import PedidoCompra
from app.models.pedido_compra_linea_facturada import PedidoCompraLineaFacturada
from app.models.producto import ProductoERP
from app.models.sell_in import SellInBonoMarca, SellInCompra, SellInCompraItem, SellInCompraPedido
from app.models.tipo_cambio import TipoCambio
from app.services.sell_in.compras import SellInError, audit, costo_en_moneda, moneda
from app.services.sell_in.costing import get_costing
from app.services.sell_in.split import CENT

# First key of the two-key advisory lock; the second is the bonus id. Distinct from costing's 0x5E11.
LOCK_NAMESPACE = 0x5E12
ESTADOS_EXCLUIDOS = frozenset({"cancelado", "rechazado"})
ORIGEN = "bono_marca"

_LOCK_SQL = text(
    "SELECT pg_advisory_xact_lock(:ns, i) FROM (SELECT DISTINCT i FROM unnest(CAST(:ids AS integer[])) AS t(i) "
    "ORDER BY i) AS ordered"
)

Par = Tuple[int, int]  # (bono_id, pedido_id)


@dataclass
class ReconcileResult:
    creadas: int = 0
    actualizadas: int = 0
    anuladas: int = 0
    # (bono_id, pedido_id) -> why that pair could not be reconciled (left as it was).
    fallidas: Dict[Par, str] = field(default_factory=dict)


@dataclass(frozen=True)
class _Pedido:
    id: int
    proveedor_id: int
    estado: str
    tipo_cambio: Optional[Decimal]
    fecha_factura: Optional[date]


@dataclass(frozen=True)
class _Deseada:
    """What a pair's purchase must be: header values and `{item_id: (cantidad, monto_asignado)}`."""

    cabecera: dict
    lineas: Dict[int, Tuple[int, Decimal]]


def _bloquear(db: Session, bono_ids: Iterable[int]) -> None:
    ids = sorted({int(i) for i in bono_ids})
    if ids and db.get_bind().dialect.name == "postgresql":
        db.execute(_LOCK_SQL, {"ns": LOCK_NAMESPACE, "ids": ids})


def _pares(db: Session, bono_ids: Set[int], pedido_ids: Set[int]) -> Set[Par]:
    """Every pair a call must look at: what may apply now plus what was generated before."""
    pares: Set[Par] = set()
    en_rango = and_(
        PedidoCompra.fecha_factura >= SellInBonoMarca.fecha_desde,
        PedidoCompra.fecha_factura <= SellInBonoMarca.fecha_hasta,
    )
    if bono_ids:
        # Each given bonus (any state) with every operation invoiced in its range.
        pares.update(
            (int(bid), int(pid))
            for bid, pid in db.query(SellInBonoMarca.id, PedidoCompra.id)
            .join(PedidoCompra, en_rango)
            .filter(SellInBonoMarca.id.in_(bono_ids))
        )
    if pedido_ids:
        # Each given operation with every ACTIVE bonus whose range covers its invoice date.
        pares.update(
            (int(bid), int(pid))
            for bid, pid in db.query(SellInBonoMarca.id, PedidoCompra.id)
            .join(PedidoCompra, en_rango)
            .filter(PedidoCompra.id.in_(pedido_ids), SellInBonoMarca.estado == "activa")
        )
    generadas = db.query(SellInCompra.bono_id, SellInCompra.bono_pedido_id).filter(
        SellInCompra.origen == ORIGEN,
        SellInCompra.bono_pedido_id.isnot(None),
        or_(SellInCompra.bono_id.in_(bono_ids or [-1]), SellInCompra.bono_pedido_id.in_(pedido_ids or [-1])),
    )
    pares.update((int(bid), int(pid)) for bid, pid in generadas)
    return pares


def _huerfanas(db: Session) -> List[SellInCompra]:
    """Active generated purchases whose operation was deleted (`bono_pedido_id` set NULL by the FK)."""
    return (
        db.query(SellInCompra)
        .filter(SellInCompra.origen == ORIGEN, SellInCompra.bono_pedido_id.is_(None), SellInCompra.estado == "activa")
        .order_by(SellInCompra.id)
        .all()
    )


def _tasas_bna(db: Session, fechas: Set[date]) -> Dict[date, Optional[Decimal]]:
    """The BNA USD rate of each date (the latest positive one on or before it; on a tie of dates, the
    highest id), all in ONE read: the rows from the latest one on or before the earliest date through
    the latest date, bisected here."""
    if not fechas:
        return {}
    usd = and_(TipoCambio.moneda == "USD", TipoCambio.venta > 0)
    desde = db.query(func.max(TipoCambio.fecha)).filter(usd, TipoCambio.fecha <= min(fechas)).scalar_subquery()
    filas = (
        db.query(TipoCambio.fecha, TipoCambio.venta)
        .filter(usd, TipoCambio.fecha >= func.coalesce(desde, min(fechas)), TipoCambio.fecha <= max(fechas))
        .order_by(TipoCambio.fecha, TipoCambio.id)
        .all()
    )
    dias = [f for f, _ in filas]
    tasas: Dict[date, Optional[Decimal]] = {}
    for fecha in fechas:
        i = bisect_right(dias, fecha)  # the last row on or before `fecha` (the highest id of its day)
        tasas[fecha] = Decimal(str(filas[i - 1][1])) if i else None
    return tasas


def _deseada(
    db: Session,
    bono: SellInBonoMarca,
    pedido: Optional[_Pedido],
    lineas: List[tuple],
    tasas_bna: Dict[date, Optional[Decimal]],
) -> Optional[_Deseada]:
    """The purchase the pair must have, or None when the bonus does not apply to it. Raises `SellInError`
    when it applies but its USD amount has no rate to convert at. `tasas_bna` holds the BNA rate per
    invoice date for the whole call."""
    if bono.estado != "activa" or pedido is None or pedido.estado in ESTADOS_EXCLUIDOS:
        return None
    fecha = pedido.fecha_factura
    if fecha is None or not (bono.fecha_desde <= fecha <= bono.fecha_hasta):
        return None
    # No duplicate or non-positive units: the snapshot has UNIQUE(pedido_id, item_id) and CHECK(cantidad > 0).
    propias = [linea for linea in lineas if linea[2] == bono.marca]
    if not propias:
        return None
    tasa = pedido.tipo_cambio
    if tasa is None:
        tasa = tasas_bna.get(fecha)
    if bono.moneda == "USD" and tasa is None:
        raise SellInError(
            f"El pedido {pedido.id} no tiene tipo de cambio y no hay cotización del dólar al {fecha.isoformat()}"
        )
    monto_unit = Decimal(bono.monto_unit)
    detalle = {item_id: (cantidad, (monto_unit * cantidad).quantize(CENT)) for item_id, cantidad, _, _, _ in propias}
    cabecera = {
        "estado": "activa",
        "proveedor_id": pedido.proveedor_id,
        "pedido_compra_id": pedido.id,
        "fecha_compra": fecha,
        "moneda": bono.moneda,
        "tipo_cambio": tasa.quantize(Decimal("0.000001")) if tasa is not None else None,
        "monto_total": sum((monto for _, monto in detalle.values()), Decimal("0")),
        "descripcion": f"Bono de marca {bono.marca} (bono {bono.id})",
        "usuario_id": bono.usuario_id,
    }
    return _Deseada(cabecera, detalle)


def _costo(costo, moneda_costo, moneda_compra: str, tasa: Optional[Decimal]) -> Decimal:
    """The product's cost frozen on a new line, in the purchase currency; 0 when it has none or it
    cannot be converted (informational only: the bonus amount never depends on it)."""
    if costo is None:
        return Decimal("0")
    try:
        return costo_en_moneda(Decimal(str(costo)), moneda(moneda_costo), moneda_compra, tasa)
    except SellInError:
        return Decimal("0")


def _lineas_de(items: List[SellInCompraItem]) -> Dict[int, Tuple[int, Decimal]]:
    return {i.item_id: (i.cantidad, Decimal(i.monto_asignado)) for i in items}


def _audit_cambio(db: Session, compra: SellInCompra, antes: dict, despues: dict) -> None:
    def _json(valores: dict) -> dict:
        return {k: (str(v) if v is not None and not isinstance(v, (int, str, list)) else v) for k, v in valores.items()}

    db.add(
        Auditoria(
            item_id=None,
            usuario_id=compra.usuario_id,
            tipo_accion=TipoAccion.SELL_IN_COMPRA_BONO_ACTUALIZADA,
            valores_anteriores=_json(antes),
            valores_nuevos=_json(despues),
            es_masivo=0,
            comentario=None,
            fecha=datetime.now(timezone.utc).replace(tzinfo=None),  # naive UTC, like the column's default
        )
    )


def _foto(compra: SellInCompra, lineas: Dict[int, Tuple[int, Decimal]]) -> dict:
    return {
        "compra_id": compra.id,
        "bono_id": compra.bono_id,
        "pedido_id": compra.bono_pedido_id,
        **{k: getattr(compra, k) for k in _CABECERA},
        "lineas": [[item, cant, str(monto)] for item, (cant, monto) in sorted(lineas.items())],
    }


_CABECERA = (
    "estado",
    "proveedor_id",
    "pedido_compra_id",
    "fecha_compra",
    "moneda",
    "tipo_cambio",
    "monto_total",
    "descripcion",
    "usuario_id",
)


def reconciliar(db: Session, *, bono_ids: Iterable[int] = (), pedido_ids: Iterable[int] = ()) -> ReconcileResult:
    """Brings the purchases generated for the given bonuses and operations in line with the rules (module
    docstring). Does not commit. A pair whose rate is missing is skipped and reported in `fallidas`; any
    other error propagates and the caller rolls back."""
    bono_set = {int(i) for i in bono_ids}
    pedido_set = {int(i) for i in pedido_ids}
    result = ReconcileResult()
    pares = _pares(db, bono_set, pedido_set)
    huerfanas = _huerfanas(db)
    if not pares and not huerfanas:
        return result
    bloqueados = {bid for bid, _ in pares} | {c.bono_id for c in huerfanas}
    _bloquear(db, bloqueados)
    # Again, now that no other call can write these bonuses' purchases, and ONLY for them: a bonus that
    # appeared while this call waited (activated, its range or brand changed, a purchase of another
    # call) is not locked here, and the change that made it appear queued it through its own trigger.
    pares = {par for par in _pares(db, bono_set, pedido_set) if par[0] in bloqueados}
    huerfanas = [c for c in _huerfanas(db) if c.bono_id in bloqueados]

    # Fresh: a worker batch shares the session, so rows loaded before the lock may be stale.
    bonos = {
        x.id: x
        for x in db.query(SellInBonoMarca).filter(SellInBonoMarca.id.in_({bid for bid, _ in pares})).populate_existing()
    }
    pids = {pid for _, pid in pares}
    pedidos = {
        row.id: _Pedido(
            row.id,
            row.proveedor_id,
            row.estado,
            Decimal(row.tipo_cambio) if row.tipo_cambio is not None else None,
            row.fecha_factura,
        )
        for row in db.query(
            PedidoCompra.id,
            PedidoCompra.proveedor_id,
            PedidoCompra.estado,
            PedidoCompra.tipo_cambio,
            PedidoCompra.fecha_factura,
        ).filter(PedidoCompra.id.in_(pids or [-1]))
    }
    lineas: Dict[int, List[tuple]] = defaultdict(list)
    for pid, item_id, cantidad, marca, costo, moneda_costo in (
        db.query(
            PedidoCompraLineaFacturada.pedido_id,
            PedidoCompraLineaFacturada.item_id,
            PedidoCompraLineaFacturada.cantidad,
            ProductoERP.marca,
            ProductoERP.costo,
            ProductoERP.moneda_costo,
        )
        .join(ProductoERP, ProductoERP.item_id == PedidoCompraLineaFacturada.item_id)
        .filter(PedidoCompraLineaFacturada.pedido_id.in_(pids or [-1]))
    ):
        lineas[pid].append((item_id, cantidad, marca, costo, moneda_costo))
    existentes: Dict[Par, SellInCompra] = {
        (c.bono_id, c.bono_pedido_id): c
        for c in db.query(SellInCompra).filter(
            SellInCompra.origen == ORIGEN, SellInCompra.bono_id.in_({bid for bid, _ in pares})
        )
        if (c.bono_id, c.bono_pedido_id) in pares
    }
    items_por_compra: Dict[int, List[SellInCompraItem]] = defaultdict(list)
    compra_ids = [c.id for c in existentes.values()] + [c.id for c in huerfanas]
    for item in db.query(SellInCompraItem).filter(SellInCompraItem.compra_id.in_(compra_ids or [-1])):
        items_por_compra[item.compra_id].append(item)

    tocados: Set[int] = set()
    tasas_bna = _tasas_bna(
        db, {p.fecha_factura for p in pedidos.values() if p.tipo_cambio is None and p.fecha_factura is not None}
    )
    for compra in huerfanas:
        actuales = items_por_compra.get(compra.id, [])
        compra.estado = "anulada"
        audit(db, compra, actuales, TipoAccion.SELL_IN_COMPRA_ANULADA, compra.usuario_id, _motivo(None))
        tocados |= {i.item_id for i in actuales}
        result.anuladas += 1
    for par in sorted(pares):
        bono_id, pedido_id = par
        pedido = pedidos.get(pedido_id)
        try:
            deseada = _deseada(db, bonos[bono_id], pedido, lineas.get(pedido_id, []), tasas_bna)
        except SellInError as exc:
            result.fallidas[par] = str(exc)
            continue
        compra = existentes.get(par)
        actuales = items_por_compra.get(compra.id, []) if compra is not None else []
        if compra is None and deseada is not None:
            tocados |= _crear(db, bonos[bono_id], pedido_id, deseada, lineas[pedido_id])
            result.creadas += 1
        elif compra is not None and deseada is None:
            if compra.estado == "activa":
                compra.estado = "anulada"
                audit(db, compra, actuales, TipoAccion.SELL_IN_COMPRA_ANULADA, compra.usuario_id, _motivo(pedido))
                tocados |= {i.item_id for i in actuales}
                result.anuladas += 1
        elif compra is not None and deseada is not None:
            cambiados = _actualizar(db, compra, actuales, deseada, lineas[pedido_id])
            if cambiados:
                tocados |= cambiados
                result.actualizadas += 1
    db.flush()
    if tocados:
        # Same transaction, like loading or voiding a manual purchase: the consumptions follow at once.
        get_costing().recompute(db, tocados, isolate_failures=False)
    return result


def _motivo(pedido: Optional[_Pedido]) -> str:
    if pedido is None:
        return "Bono de marca: el pedido de compra ya no existe"
    return "Bono de marca: el pedido ya no está alcanzado por el bono"


def _crear(db: Session, bono: SellInBonoMarca, pedido_id: int, deseada: _Deseada, lineas: List[tuple]) -> Set[int]:
    compra = SellInCompra(
        **deseada.cabecera,
        cuenta_desde="compra",
        formula="por_unidad",
        origen=ORIGEN,
        bono_id=bono.id,
        bono_pedido_id=pedido_id,
    )
    db.add(compra)
    db.flush()
    db.add(SellInCompraPedido(compra_id=compra.id, pedido_compra_id=pedido_id))
    costos = {item: (costo, moneda_costo) for item, _, _, costo, moneda_costo in lineas}
    items = [
        SellInCompraItem(
            compra_id=compra.id,
            item_id=item_id,
            cantidad=cantidad,
            costo_base_unit=_costo(*costos[item_id], compra.moneda, compra.tipo_cambio),
            monto_asignado=monto,
        )
        for item_id, (cantidad, monto) in sorted(deseada.lineas.items())
    ]
    db.add_all(items)
    db.flush()
    audit(db, compra, items, TipoAccion.SELL_IN_COMPRA_CREADA, compra.usuario_id)
    return set(deseada.lineas)


def _actualizar(
    db: Session, compra: SellInCompra, actuales: List[SellInCompraItem], deseada: _Deseada, lineas: List[tuple]
) -> Set[int]:
    """Updates the purchase in place when it differs; returns the products touched (empty: nothing changed)."""
    antes_lineas = _lineas_de(actuales)
    cabecera_igual = all(getattr(compra, k) == v for k, v in deseada.cabecera.items())
    if cabecera_igual and antes_lineas == deseada.lineas:
        return set()
    antes = _foto(compra, antes_lineas)
    for k, v in deseada.cabecera.items():
        setattr(compra, k, v)
    costos = {item: (costo, moneda_costo) for item, _, _, costo, moneda_costo in lineas}
    for item in actuales:
        if item.item_id not in deseada.lineas:
            db.delete(item)
        else:
            item.cantidad, item.monto_asignado = deseada.lineas[item.item_id]
    for item_id, (cantidad, monto) in sorted(deseada.lineas.items()):
        if item_id not in antes_lineas:
            db.add(
                SellInCompraItem(
                    compra_id=compra.id,
                    item_id=item_id,
                    cantidad=cantidad,
                    costo_base_unit=_costo(*costos[item_id], compra.moneda, compra.tipo_cambio),
                    monto_asignado=monto,
                )
            )
    db.flush()
    _audit_cambio(db, compra, antes, _foto(compra, deseada.lineas))
    return set(antes_lineas) | set(deseada.lineas)
