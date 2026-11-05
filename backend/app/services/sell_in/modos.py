"""A product's sell-in cost modes (owner: "Para sell in vamos a mantener el FIFO pero además quiero un sistema que con
un permiso aparte se pueda elegir ponderar el stock y el precio y no usar solo fifo [...]").

`sell_in_modos_producto` holds append-only rows, one per change of a product's mode from `desde` on. No row means
FIFO, the default. The row that governs a date is the latest with `desde <= date`; two rows on the same `desde` are
ordered by id, so the one saved last wins. Design: handoffs `sell-in-costos-propuesta.md`.

A change goes through a mandatory preview (D2): the recompute itself runs with the new row inside a savepoint that is
rolled back, and reports the recorded sales whose sell in changes, the ARS difference, the units and unit value left,
and the ARS the lots hold that no unit hands out. The confirm runs the same simulation and saves it only if its
fingerprint is the preview's; anything that moved in between (a sale, a purchase or a line of one, another mode row, a
new day) refuses it, a purchase that counts only after the preview's date included: under `ultimo` it re-values the
units left once it counts.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Callable, Dict, List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.auditoria import Auditoria, TipoAccion
from app.models.configuracion import Configuracion
from app.models.producto import ProductoERP
from app.models.sell_in import SellInConsumo, SellInModoProducto
from app.models.usuario import Usuario
from app.services.pricing_calculator import obtener_tipo_cambio_actual
from app.services.sell_in import bonos_costo
from app.services.sell_in.compras import moneda as codigo_moneda
from app.services.sell_in.costing import get_costing

MODOS_ESCRITOS = ("fifo", "ponderado", "ultimo", "manual")
# What the panel's selector may open preselected with: a manual mode needs its own quantity and cost typed.
MODOS_POR_DEFECTO = ("fifo", "ponderado", "ultimo")
UNIDAD = Decimal("0.000001")  # `sell_in_modos_producto.costo_unit` / `costo_base_unit` scale
PERMISOS_MODO = {
    "ponderado": "sell_in.costo_ponderado",
    "ultimo": "sell_in.costo_ultimo",
    "manual": "sell_in.costo_manual",
}
PERMISO_RETROACTIVO = "sell_in.costo_retroactivo"


class ModoInvalido(ValueError):
    """A mode this endpoint does not write."""


class SinCosto(ValueError):
    """A manual mode needs the product's cost to freeze, in pesos."""


@dataclass(frozen=True)
class Manual:
    """A manual mode's typed values (D6): units and their unit cost in ARS."""

    cantidad: int
    costo_unit: Decimal


class HuellaVencida(Exception):
    """Something moved since the preview: the user must preview again."""


@dataclass(frozen=True)
class VistaPrevia:
    ventas_cambian: int  # recorded sales whose sell in changes
    diferencia_ars: Decimal  # their new sell in minus the current one
    unidades_restantes: int  # the units the next sale draws from, after the change
    descuento_unit: Optional[Decimal]  # their unit value; None: no unit left
    del_bloque: bool  # the next sale draws from a manual block (D6)
    sin_asignar_antes: Decimal  # ARS the lots hold that no unit hands out, today
    sin_asignar_despues: Decimal  # the same after the change
    huella: str
    costo_base_unit: Optional[Decimal] = None  # `manual`: the product's cost frozen on the row


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


def costo_congelado(db: Session, item_id: int) -> Decimal:
    """The product's cost in ARS a manual row freezes (D6): `productos_erp.costo`, the base a purchase freezes too,
    converted at today's USD rate when the cost is in USD (the rate the Productos screens use)."""
    fila = db.query(ProductoERP.costo, ProductoERP.moneda_costo).filter(ProductoERP.item_id == item_id).first()
    if fila is None or fila.costo is None:
        raise SinCosto("The product has no cost to freeze")
    costo = Decimal(str(fila.costo))
    if codigo_moneda(fila.moneda_costo) == "USD":
        tipo_cambio = obtener_tipo_cambio_actual(db, "USD")
        if not tipo_cambio:
            raise SinCosto("There is no USD rate to freeze the product's cost in pesos")
        costo *= Decimal(str(tipo_cambio))
    return costo.quantize(UNIDAD, rounding=ROUND_HALF_UP)


def vista_previa(
    db: Session, item_id: int, modo: str, desde: date, hoy: date, usuario_id: int, manual: Optional[Manual] = None
) -> VistaPrevia:
    """What saving `modo` from `desde` (a manual one with its typed values) would do, with nothing saved: the
    simulation runs in a savepoint rolled back, which also releases the product's recompute lock it took."""
    savepoint = db.begin_nested()
    try:
        vista, _ = _simular(db, item_id, modo, desde, hoy, usuario_id, manual)
    finally:
        savepoint.rollback()
    return vista


def confirmar(
    db: Session,
    item_id: int,
    modo: str,
    desde: date,
    hoy: date,
    usuario_id: int,
    huella: str,
    manual: Optional[Manual] = None,
) -> int:
    """Saves `modo` from `desde`, recomputes the product and audits it, only if the simulation is still the one the
    preview showed (`huella`); otherwise nothing is kept and `HuellaVencida` is raised. Does not commit."""
    savepoint = db.begin_nested()
    try:
        vista, fila = _simular(db, item_id, modo, desde, hoy, usuario_id, manual)
        if vista.huella != huella:
            raise HuellaVencida()
    except BaseException:
        savepoint.rollback()
        raise
    savepoint.commit()
    bonos_costo.seguir_fifo(db, [item_id])  # like every write that moves the FIFO outside the drain
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
                **(
                    {
                        "cantidad": fila.cantidad,
                        "costo_unit": str(fila.costo_unit),
                        "costo_base_unit": str(fila.costo_base_unit),
                    }
                    if modo == "manual"
                    else {}
                ),
            },
            es_masivo=False,
            fecha=datetime.now(timezone.utc).replace(tzinfo=None),  # naive UTC, like the column's default
        )
    )
    return fila.id


def _simular(
    db: Session, item_id: int, modo: str, desde: date, hoy: date, usuario_id: int, manual: Optional[Manual] = None
) -> Tuple[VistaPrevia, SellInModoProducto]:
    """Recomputes the product as it stands, then with the new row, and compares; leaves both in the transaction."""
    if modo not in MODOS_ESCRITOS or (modo == "manual") != (manual is not None):
        raise ModoInvalido(f"cost mode {modo!r} cannot be set here with these values")
    valores = {}
    if manual is not None:
        valores = {
            "cantidad": manual.cantidad,
            "costo_unit": manual.costo_unit.quantize(UNIDAD, rounding=ROUND_HALF_UP),
            "costo_base_unit": costo_congelado(db, item_id),
        }
    costing = get_costing()
    # The recompute takes the product's lock first, so the rows read next are the ones a concurrent change left.
    costing.recompute(db, [item_id], isolate_failures=False)  # what is stored, brought up to date
    previos = [
        r[0] for r in db.query(SellInModoProducto.id).filter(SellInModoProducto.item_id == item_id).order_by("id")
    ]
    lotes = [
        [lote.compra_item_id, lote.fecha.isoformat(), lote.cantidad, str(lote.descuento_ars)]
        for lote in costing.lotes(db, [item_id]).get(item_id, [])
    ]
    antes = _por_venta(db, item_id)
    sin_antes = costing.sin_asignar(db, item_id, hoy)
    fila = SellInModoProducto(item_id=item_id, modo=modo, desde=desde, usuario_id=usuario_id, origen="visor", **valores)
    db.add(fila)
    db.flush()
    costing.recompute(db, [item_id], isolate_failures=False)
    despues = _por_venta(db, item_id)
    # What the product is left with once the new row governs: from `desde` when it is still to come.
    dia = max(hoy, desde)
    queda = costing.vigentes(db, [item_id], dia).get(item_id)
    cambian = [k for k in antes.keys() | despues.keys() if antes.get(k, Decimal(0)) != despues.get(k, Decimal(0))]
    diferencia = sum((despues.get(k, Decimal(0)) - antes.get(k, Decimal(0)) for k in cambian), Decimal("0.00"))
    unidades = queda.unidades_restantes if queda is not None else 0
    descuento = queda.descuento_unit_ars if queda is not None else None
    sin_despues = costing.sin_asignar(db, item_id, dia)
    # Everything the preview shows, and what it was computed from (every lot, those counting after `dia` included).
    contenido = [
        modo,
        desde.isoformat(),
        hoy.isoformat(),
        previos,
        lotes,
        _orden(antes),
        _orden(despues),
        unidades,
        str(descuento),
        str(sin_antes),
        str(sin_despues),
    ]
    if valores:  # what the user typed and the cost frozen against it
        contenido.append([valores["cantidad"], str(valores["costo_unit"]), str(valores["costo_base_unit"])])
    vista = VistaPrevia(
        ventas_cambian=len(cambian),
        diferencia_ars=diferencia,
        unidades_restantes=unidades,
        descuento_unit=descuento,
        del_bloque=queda is not None and queda.compra_item_id < 0,
        sin_asignar_antes=sin_antes,
        sin_asignar_despues=sin_despues,
        huella=hashlib.sha256(json.dumps(contenido, separators=(",", ":")).encode()).hexdigest(),
        costo_base_unit=valores.get("costo_base_unit"),
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
    return {(canal, ref): Decimal(total) for canal, ref, total in filas}


def _orden(montos: Dict[Tuple[str, int], Decimal]) -> List[list]:
    return [[canal, ref, str(monto)] for (canal, ref), monto in sorted(montos.items())]


CLAVE_POR_DEFECTO = "sell_in_modo_por_defecto"


def modo_por_defecto(db: Session) -> str:
    """The mode the panel's selector opens preselected with (global, `configuracion`); FIFO when unset, unknown or
    `manual`.

    It only preselects the selector: a product without a mode row stays FIFO here, whatever this says.
    """
    fila = db.query(Configuracion).filter(Configuracion.clave == CLAVE_POR_DEFECTO).first()
    return fila.valor if fila is not None and fila.valor in MODOS_POR_DEFECTO else "fifo"


def fijar_modo_por_defecto(db: Session, modo: str, usuario_id: int) -> str:
    """Store the selector's preselected mode (upsert of its `configuracion` key), audit who changed it from what to
    what, and commit."""
    antes = modo_por_defecto(db)
    fila = db.query(Configuracion).filter(Configuracion.clave == CLAVE_POR_DEFECTO).first()
    if fila is None:
        db.add(
            Configuracion(
                clave=CLAVE_POR_DEFECTO,
                valor=modo,
                descripcion="Modo de costo con el que abre preseleccionado el selector del panel de sell in",
                tipo="string",
            )
        )
    else:
        fila.valor = modo
    db.add(
        Auditoria(
            item_id=None,
            usuario_id=usuario_id,
            tipo_accion=TipoAccion.SELL_IN_MODO_POR_DEFECTO,
            valores_anteriores={"modo": antes},
            valores_nuevos={"modo": modo},
            es_masivo=False,
            fecha=datetime.now(timezone.utc).replace(tzinfo=None),  # naive UTC, like the column's default
        )
    )
    db.commit()
    return modo
