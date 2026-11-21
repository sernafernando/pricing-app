"""Manual fixes of PDF lines (vpf-operaciones S3, S3e, S4-L2): a product assigned by hand and / or a cost typed in
ModalEditarCosto, stored apart from the replaceable PDF rows (`ventas_fuera_linea_overrides`, keyed by the document's
natural key + `renglon`).

- Applying a fix writes the line: `item_id` (origin 'manual') and `precio_costo = costo_unitario x cantidad`: the
  cost saved (typed x (1 + the optional %), owner L4) is the line's Precio Costo, and Costo D (x COSTO_D_FACTOR)
  applies on top like on any PDF line. Without a manual cost the line's Precio Costo is the costo SI cost of its
  product (`costo_erp`, sell-in-costo-si T3 PR 9), also after a product is assigned, remembered or the fix removed;
  `precio_costo_pdf` keeps the PDF's only as a reference. T4's trigger on the lines queues the line for offsets and
  sell in / sell out; metrics read the lines, so they follow.
- Owner L2: "hay que hacerle que se persista la data si cargan de nuevo un pdf que sobreescriba la venta". A
  re-upload re-applies each fix whose line snapshot (codigo, articulo, cantidad, precio) is unchanged ('aplicado');
  a changed (or missing) line keeps the PDF's values and the fix is kept with estado 'revisar', never dropped nor
  applied silently. `confirmar` takes the current line as the new snapshot and applies the fix.
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable, Optional

from sqlalchemy import and_, delete, func, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, selectinload

from app.models.venta_fuera_pdf import (
    VentaFueraCodigoMapeo,
    VentaFueraLineaOverride,
    VentaFueraOperacion,
    VentaFueraOperacionLinea,
)
from app.services.ventas_fuera_pdf.costo_erp import (
    combos_desglosados,
    costos_unitarios,
    precio_costo,
    precio_costo_erp,
)
from app.services.ventas_fuera_pdf.resolucion import (
    ORIGEN_MANUAL,
    ORIGEN_MAPEO,
    Resolucion,
    clave_mapeo,
    clave_mapeo_sql,
    item_existe,
    resolver,
)

APLICADO, REVISAR = "aplicado", "revisar"
CENTAVO = Decimal("0.01")

ClaveDoc = tuple[str, str, int, int]


class LineaNoEncontrada(LookupError):
    """No PDF line with that id."""


class OverrideNoEncontrado(LookupError):
    """The line has no manual fix."""


class OverrideInvalido(ValueError):
    """A product that does not exist or a cost not above zero."""


def precio_costo_manual(costo_unitario: Decimal, cantidad: Decimal) -> Decimal:
    """The line's Precio Costo for a manual unit cost: `costo_unitario` x `cantidad` (owner L4: the list adds Costo D
    x COSTO_D_FACTOR on top)."""
    return (Decimal(costo_unitario) * Decimal(cantidad)).quantize(CENTAVO, rounding=ROUND_HALF_UP)


def _snapshot_igual(override: VentaFueraLineaOverride, linea: VentaFueraOperacionLinea) -> bool:
    return (override.codigo, override.articulo, Decimal(override.cantidad), Decimal(override.precio)) == (
        linea.codigo,
        linea.articulo,
        Decimal(linea.cantidad),
        Decimal(linea.precio),
    )


def _tomar_snapshot(override: VentaFueraLineaOverride, linea: VentaFueraOperacionLinea) -> None:
    override.codigo, override.articulo = linea.codigo, linea.articulo
    override.cantidad, override.precio = linea.cantidad, linea.precio


def _automatico(linea: VentaFueraOperacionLinea, resolucion: Optional[Resolucion]) -> None:
    linea.item_id = resolucion.item_id if resolucion else None
    linea.item_origen = resolucion.origen if resolucion else None


Costos = dict[tuple[int, date], Optional[Decimal]]
Desglosados = dict[VentaFueraOperacion, set[int]]


def _desglosados(db: Session, lineas: Iterable[VentaFueraOperacionLinea]) -> Desglosados:
    """The combos broken down in the documents of `lineas`, by operation, from their lines as they are now (owner L19,
    `costo_erp.combos_desglosados`): one call for every document a loop touches. Keyed by the operation object, not
    its id: a load re-applies its fixes before the new operations are flushed."""
    hermanas = {linea.operacion: [otra.item_id for otra in linea.operacion.lineas] for linea in lineas}
    return combos_desglosados(db, hermanas) if hermanas else {}


def _costo_erp(
    db: Session,
    linea: VentaFueraOperacionLinea,
    costos: Optional[Costos] = None,
    desglosados: Optional[Desglosados] = None,
) -> Decimal:
    """The line's Precio Costo from the costo SI of its current product and sale date (0 without product, and 0 for a
    combo whose document brings its breakdown, owner L19). `costos` and `desglosados`: unit costs
    (`costos_unitarios`) and broken-down combos (`_desglosados`) already fetched in one batch, so a loop does not
    query per line."""
    if linea.item_id is None:
        return precio_costo(None, linea.cantidad)
    if desglosados is None:
        desglosados = _desglosados(db, [linea])
    if linea.item_id in desglosados.get(linea.operacion, set()):
        return precio_costo(None, linea.cantidad)
    if costos is None:
        return precio_costo_erp(db, linea.item_id, linea.operacion.fecha, linea.cantidad)
    return precio_costo(costos.get((linea.item_id, linea.operacion.fecha)), linea.cantidad)


def aplicar(
    db: Session,
    linea: VentaFueraOperacionLinea,
    override: VentaFueraLineaOverride,
    resolucion: Optional[Resolucion],
    costos: Optional[Costos] = None,
    desglosados: Optional[Desglosados] = None,
) -> None:
    """Write the fix on the line (`resolucion`: the automatic product, used when the fix sets none; `costos` and
    `desglosados`: fetched in one batch, see `_costo_erp`)."""
    if linea.precio_costo_pdf is None:
        linea.precio_costo_pdf = linea.precio_costo
    _producto(linea, override, resolucion)
    linea.precio_costo = (
        precio_costo_manual(override.costo_unitario, linea.cantidad)
        if override.costo_unitario is not None
        else _costo_erp(db, linea, costos, desglosados)
    )
    linea.override_estado = override.estado = APLICADO


def _producto(
    linea: VentaFueraOperacionLinea, override: VentaFueraLineaOverride, resolucion: Optional[Resolucion]
) -> None:
    if override.item_id is not None:
        linea.item_id, linea.item_origen = override.item_id, ORIGEN_MANUAL
    else:
        _automatico(linea, resolucion)


def aplicar_en_carga(
    db: Session, empresa: str, lineas: dict[ClaveDoc, list[VentaFueraOperacionLinea]]
) -> tuple[int, int]:
    """After a load built its lines (automatic product already set): re-apply the fixes of the loaded documents whose
    line did not change, flag the others 'revisar'. Fixes of documents the PDF does not hold are left alone. Returns
    `(aplicados, revisar)`."""
    if not lineas:
        return 0, 0
    overrides = db.execute(
        select(VentaFueraLineaOverride).where(
            VentaFueraLineaOverride.empresa == empresa,
            tuple_(
                VentaFueraLineaOverride.tipo,
                VentaFueraLineaOverride.letra,
                VentaFueraLineaOverride.punto_venta,
                VentaFueraLineaOverride.numero,
            ).in_(list(lineas)),
        )
    ).scalars()
    pares = []
    for override in overrides:
        clave = (override.tipo, override.letra, override.punto_venta, override.numero)
        linea = next((ln for ln in lineas[clave] if ln.renglon == override.renglon), None)
        pares.append((override, linea))
    # One query for the cost of every line a fix re-applies without a manual cost (its product or the fix's).
    costos = costos_unitarios(
        db,
        [
            (override.item_id if override.item_id is not None else linea.item_id, linea.operacion.fecha)
            for override, linea in pares
            if linea is not None
            and override.costo_unitario is None
            and (override.item_id is not None or linea.item_id is not None)
        ],
    )
    aplicables = []
    revisar = 0
    for override, linea in pares:
        if linea is not None and _snapshot_igual(override, linea):
            automatica = Resolucion(linea.item_id, linea.item_origen) if linea.item_id is not None else None
            aplicables.append((override, linea, automatica))
        else:
            override.estado = REVISAR
            if linea is not None:
                linea.override_estado = REVISAR
            revisar += 1
    # Every fix's product first, then one breakdown check of their documents as they end up (a fix may change which
    # combo a document breaks down).
    for override, linea, automatica in aplicables:
        _producto(linea, override, automatica)
    desglosados = _desglosados(db, [linea for _, linea, _ in aplicables])
    for override, linea, automatica in aplicables:
        aplicar(db, linea, override, automatica, costos, desglosados)
    return len(aplicables), revisar


def _linea(db: Session, linea_id: int) -> VentaFueraOperacionLinea:
    linea = db.get(VentaFueraOperacionLinea, linea_id)
    if linea is None:
        raise LineaNoEncontrada(linea_id)
    return linea


def _clave(linea: VentaFueraOperacionLinea) -> dict:
    op: VentaFueraOperacion = linea.operacion
    return {
        "empresa": op.empresa,
        "tipo": op.tipo,
        "letra": op.letra,
        "punto_venta": op.punto_venta,
        "numero": op.numero,
        "renglon": linea.renglon,
    }


def override_de(db: Session, linea: VentaFueraOperacionLinea) -> Optional[VentaFueraLineaOverride]:
    clave = _clave(linea)
    return db.execute(
        select(VentaFueraLineaOverride).where(
            and_(*(getattr(VentaFueraLineaOverride, k) == v for k, v in clave.items()))
        )
    ).scalar_one_or_none()


def _resolucion(db: Session, linea: VentaFueraOperacionLinea) -> Optional[Resolucion]:
    return resolver(db, [(linea.codigo, linea.articulo)])[(linea.codigo, linea.articulo)]


def guardar(
    db: Session,
    linea_id: int,
    cambios: dict,
    recordar_mapeo: bool,
    usuario_id: Optional[int],
) -> VentaFueraOperacionLinea:
    """Create or change the fix of a line (only the fields in `cambios`: `costo_unitario`, `item_id`; None clears
    one), snapshot the line as it is now and apply it. `recordar_mapeo` also remembers the product for the line's
    code (or article) and gives it to the other lines of that key still without product. Commits."""
    linea = _linea(db, linea_id)
    costo = cambios.get("costo_unitario")
    if costo is not None and Decimal(str(costo)) <= 0:
        raise OverrideInvalido("El costo unitario tiene que ser mayor a cero")
    item_id = cambios.get("item_id")
    if item_id is not None and not item_existe(db, item_id):
        raise OverrideInvalido(f"El producto {item_id} no existe")
    override = override_de(db, linea)
    if override is None:
        override = VentaFueraLineaOverride(**_clave(linea))
        db.add(override)
    if "costo_unitario" in cambios:
        override.costo_unitario = Decimal(str(costo)) if costo is not None else None
    if "item_id" in cambios:
        override.item_id = item_id
    if recordar_mapeo and override.item_id is None:
        raise OverrideInvalido("Para recordar el producto en las próximas cargas hay que asignar uno")
    override.usuario_id = usuario_id
    _tomar_snapshot(override, linea)
    aplicar(db, linea, override, _resolucion(db, linea))
    if recordar_mapeo:
        _recordar(db, linea, override.item_id, usuario_id)
    db.commit()
    return linea


def _recordar(db: Session, linea: VentaFueraOperacionLinea, item_id: int, usuario_id: Optional[int]) -> None:
    clave = clave_mapeo(linea.codigo, linea.articulo)
    db.execute(
        insert(VentaFueraCodigoMapeo)
        .values(clave=clave, item_id=item_id, usuario_id=usuario_id)
        .on_conflict_do_update(
            index_elements=[VentaFueraCodigoMapeo.clave],
            set_={"item_id": item_id, "usuario_id": usuario_id, "updated_at": func.now()},
        )
    )
    otras = (
        db.execute(
            select(VentaFueraOperacionLinea)
            # their documents and all their lines in two queries: the breakdown check reads them (`_desglosados`)
            .options(selectinload(VentaFueraOperacionLinea.operacion).selectinload(VentaFueraOperacion.lineas))
            .where(
                VentaFueraOperacionLinea.item_id.is_(None),
                VentaFueraOperacionLinea.id != linea.id,
                clave_mapeo_sql(VentaFueraOperacionLinea.codigo, VentaFueraOperacionLinea.articulo) == clave,
            )
        )
        .scalars()
        .all()
    )
    if not otras:
        return
    # One query for their applied manual costs and one for their costs, not two per line.
    con_costo_manual = {
        tuple(fila)
        for fila in db.execute(
            select(
                VentaFueraLineaOverride.empresa,
                VentaFueraLineaOverride.tipo,
                VentaFueraLineaOverride.letra,
                VentaFueraLineaOverride.punto_venta,
                VentaFueraLineaOverride.numero,
                VentaFueraLineaOverride.renglon,
            ).where(
                VentaFueraLineaOverride.costo_unitario.is_not(None),
                VentaFueraLineaOverride.estado == APLICADO,
                tuple_(
                    VentaFueraLineaOverride.empresa,
                    VentaFueraLineaOverride.tipo,
                    VentaFueraLineaOverride.letra,
                    VentaFueraLineaOverride.punto_venta,
                    VentaFueraLineaOverride.numero,
                    VentaFueraLineaOverride.renglon,
                ).in_([tuple(_clave(otra).values()) for otra in otras]),
            )
        )
    }
    costos = costos_unitarios(db, [(item_id, otra.operacion.fecha) for otra in otras])
    for otra in otras:
        otra.item_id, otra.item_origen = item_id, ORIGEN_MAPEO
    desglosados = _desglosados(db, otras)
    for otra in otras:
        # Only an APPLIED manual cost keeps the line's cost; one flagged 'revisar' is not on the line.
        if tuple(_clave(otra).values()) not in con_costo_manual:
            otra.precio_costo = _costo_erp(db, otra, costos, desglosados)


def quitar(db: Session, linea_id: int) -> VentaFueraOperacionLinea:
    """Delete the fix: the line goes back to the automatic product and its costo SI cost. Commits."""
    linea = _linea(db, linea_id)
    override = override_de(db, linea)
    if override is None:
        raise OverrideNoEncontrado(linea_id)
    db.execute(delete(VentaFueraLineaOverride).where(VentaFueraLineaOverride.id == override.id))
    _automatico(linea, _resolucion(db, linea))
    linea.precio_costo = _costo_erp(db, linea)
    linea.override_estado = None
    db.commit()
    return linea


def confirmar(db: Session, linea_id: int) -> VentaFueraOperacionLinea:
    """A fix flagged 'revisar': take the current line as its snapshot and apply it. Commits."""
    linea = _linea(db, linea_id)
    override = override_de(db, linea)
    if override is None:
        raise OverrideNoEncontrado(linea_id)
    _tomar_snapshot(override, linea)
    aplicar(db, linea, override, _resolucion(db, linea))
    db.commit()
    return linea
