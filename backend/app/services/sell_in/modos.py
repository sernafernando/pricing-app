"""A product's sell-in cost modes (owner: "Para sell in vamos a mantener el FIFO pero además quiero un sistema que con
un permiso aparte se pueda elegir ponderar el stock y el precio y no usar solo fifo [...]").

`sell_in_modos_producto` holds append-only rows, one per change of a product's mode from `desde` on. No row means
FIFO, the default. The row that governs a date is the latest with `desde <= date`; two rows on the same `desde` are
ordered by id, so the one saved last wins. Design: handoffs `sell-in-costos-propuesta.md`.

A change goes through a mandatory preview (D2): the recompute itself runs with the new row inside a savepoint that is
rolled back, and reports the recorded sales whose sell in changes, the ARS difference, the units and unit value left,
and the ARS the lots hold that no unit hands out. The confirm runs the same simulation and saves it only if its
fingerprint is the preview's; anything that moved in between (a sale, a purchase, another mode row) refuses it.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Callable, Dict, List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.auditoria import Auditoria, TipoAccion
from app.models.sell_in import SellInConsumo, SellInModoProducto
from app.models.usuario import Usuario
from app.services.sell_in.costing import get_costing

# The modes written here; `manual` (typed quantity and cost) lands in its own slice.
MODOS_ESCRITOS = ("fifo", "ponderado", "ultimo")
PERMISOS_MODO = {
    "ponderado": "sell_in.costo_ponderado",
    "ultimo": "sell_in.costo_ultimo",
    "manual": "sell_in.costo_manual",
}
PERMISO_RETROACTIVO = "sell_in.costo_retroactivo"


class ModoInvalido(ValueError):
    """A mode this endpoint does not write."""


class HuellaVencida(Exception):
    """Something moved since the preview: the user must preview again."""


@dataclass(frozen=True)
class VistaPrevia:
    ventas_cambian: int  # recorded sales whose sell in changes
    diferencia_ars: Decimal  # their new sell in minus the current one
    unidades_restantes: int  # the units the next sale draws from, after the change
    descuento_unit: Optional[Decimal]  # their unit value; None: no unit left
    sin_asignar_antes: Decimal  # ARS the lots hold that no unit hands out, today
    sin_asignar_despues: Decimal  # the same after the change
    huella: str


@dataclass(frozen=True)
class ModoProducto:
    id: int
    modo: str
    desde: date
    cantidad: Optional[int]
    costo_unit: Optional[Decimal]
    costo_base_unit: Optional[Decimal]
    origen: str
    compra_id: Optional[int]
    usuario_id: int
    usuario_nombre: Optional[str]
    created_at: datetime


def historial(db: Session, item_id: int) -> List[ModoProducto]:
    """The product's mode rows, the one that starts last first (same `desde`: the one saved last first)."""
    m = SellInModoProducto
    filas = (
        db.query(m, Usuario.nombre)
        .outerjoin(Usuario, Usuario.id == m.usuario_id)
        .filter(m.item_id == item_id)
        .order_by(m.desde.desc(), m.id.desc())
    )
    return [
        ModoProducto(
            id=fila.id,
            modo=fila.modo,
            desde=fila.desde,
            cantidad=fila.cantidad,
            costo_unit=fila.costo_unit,
            costo_base_unit=fila.costo_base_unit,
            origen=fila.origen,
            compra_id=fila.compra_id,
            usuario_id=fila.usuario_id,
            usuario_nombre=nombre,
            created_at=fila.created_at,
        )
        for fila, nombre in filas
    ]


def vigente(filas: List[ModoProducto], dia: date) -> Optional[ModoProducto]:
    """The row governing `dia` from `historial`'s rows (newest first); None: FIFO."""
    return next((fila for fila in filas if fila.desde <= dia), None)


def permiso_faltante(modo: str, desde: date, hoy: date, tiene: Callable[[str], bool]) -> Optional[str]:
    """The permission the user lacks to save `modo` from `desde`, or None (D7). Each mode needs its own; FIFO needs
    any of the three; a `desde` before `hoy` also needs the backdating one."""
    if modo == "fifo":
        if not any(tiene(codigo) for codigo in PERMISOS_MODO.values()):
            return " | ".join(PERMISOS_MODO.values())
    elif not tiene(PERMISOS_MODO[modo]):
        return PERMISOS_MODO[modo]
    if desde < hoy and not tiene(PERMISO_RETROACTIVO):
        return PERMISO_RETROACTIVO
    return None


def vista_previa(db: Session, item_id: int, modo: str, desde: date, hoy: date, usuario_id: int) -> VistaPrevia:
    """What saving `modo` from `desde` would do, with nothing saved: the simulation runs in a savepoint rolled back,
    which also releases the product's recompute lock it took."""
    savepoint = db.begin_nested()
    try:
        vista, _ = _simular(db, item_id, modo, desde, hoy, usuario_id)
    finally:
        savepoint.rollback()
    return vista


def confirmar(db: Session, item_id: int, modo: str, desde: date, hoy: date, usuario_id: int, huella: str) -> int:
    """Saves `modo` from `desde`, recomputes the product and audits it, only if the simulation is still the one the
    preview showed (`huella`); otherwise nothing is kept and `HuellaVencida` is raised. Does not commit."""
    savepoint = db.begin_nested()
    try:
        vista, fila = _simular(db, item_id, modo, desde, hoy, usuario_id)
        if vista.huella != huella:
            raise HuellaVencida()
    except BaseException:
        savepoint.rollback()
        raise
    savepoint.commit()
    db.add(
        Auditoria(
            item_id=item_id,
            usuario_id=usuario_id,
            tipo_accion=TipoAccion.SELL_IN_MODO_CREADO,
            valores_anteriores=None,
            valores_nuevos={
                "modo_id": fila.id,
                "modo": modo,
                "desde": desde.isoformat(),
                "ventas_cambian": vista.ventas_cambian,
                "diferencia_ars": str(vista.diferencia_ars),
                "sin_asignar_ars": str(vista.sin_asignar_despues),
            },
            es_masivo=False,
            fecha=datetime.now(timezone.utc).replace(tzinfo=None),  # naive UTC, like the column's default
        )
    )
    return fila.id


def _simular(
    db: Session, item_id: int, modo: str, desde: date, hoy: date, usuario_id: int
) -> Tuple[VistaPrevia, SellInModoProducto]:
    """Recomputes the product as it stands, then with the new row, and compares; leaves both in the transaction."""
    if modo not in MODOS_ESCRITOS:
        raise ModoInvalido(f"cost mode {modo!r} cannot be set here")
    costing = get_costing()
    # The recompute takes the product's lock first, so the rows read next are the ones a concurrent change left.
    costing.recompute(db, [item_id], isolate_failures=False)  # what is stored, brought up to date
    previos = [
        r[0] for r in db.query(SellInModoProducto.id).filter(SellInModoProducto.item_id == item_id).order_by("id")
    ]
    antes = _por_venta(db, item_id)
    sin_antes = costing.sin_asignar(db, item_id, hoy)
    fila = SellInModoProducto(item_id=item_id, modo=modo, desde=desde, usuario_id=usuario_id, origen="visor")
    db.add(fila)
    db.flush()
    costing.recompute(db, [item_id], isolate_failures=False)
    despues = _por_venta(db, item_id)
    vigente = costing.vigentes(db, [item_id], hoy).get(item_id)
    cambian = [k for k in antes.keys() | despues.keys() if antes.get(k, Decimal(0)) != despues.get(k, Decimal(0))]
    diferencia = sum((despues.get(k, Decimal(0)) - antes.get(k, Decimal(0)) for k in cambian), Decimal("0.00"))
    unidades = vigente.unidades_restantes if vigente is not None else 0
    descuento = vigente.descuento_unit_ars if vigente is not None else None
    sin_despues = costing.sin_asignar(db, item_id, hoy)
    # Everything the preview shows, and what it was computed from: a purchase that moves no sale still moves these.
    contenido = [
        modo,
        desde.isoformat(),
        hoy.isoformat(),
        previos,
        _orden(antes),
        _orden(despues),
        unidades,
        str(descuento),
        str(sin_antes),
        str(sin_despues),
    ]
    vista = VistaPrevia(
        ventas_cambian=len(cambian),
        diferencia_ars=diferencia,
        unidades_restantes=unidades,
        descuento_unit=descuento,
        sin_asignar_antes=sin_antes,
        sin_asignar_despues=sin_despues,
        huella=hashlib.sha256(json.dumps(contenido, separators=(",", ":")).encode()).hexdigest(),
    )
    return vista, fila


def _por_venta(db: Session, item_id: int) -> Dict[Tuple[str, int], Decimal]:
    """Each recorded sale's sell in: the sum of its consumptions."""
    t = SellInConsumo
    filas = (
        db.query(t.canal, t.venta_ref, func.sum(t.descuento_ars))
        .filter(t.item_id == item_id)
        .group_by(t.canal, t.venta_ref)
    )
    salida: Dict[Tuple[str, int], Decimal] = defaultdict(Decimal)
    for canal, ref, total in filas:
        salida[(canal, ref)] = Decimal(total)
    return dict(salida)


def _orden(montos: Dict[Tuple[str, int], Decimal]) -> List[list]:
    return [[canal, ref, str(monto)] for (canal, ref), monto in sorted(montos.items())]
