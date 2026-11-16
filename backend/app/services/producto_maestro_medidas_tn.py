"""The TN publisher's stored measurements live in the product master (abm-productos T7, L8 Q3).

The publisher speaks TN units and is keyed by the GBP `Código` (EAN); the master (`productos_propios`) is keyed by
`item_id` and holds grams and cm. This module is the only translation between the two:
- the product is the one ERP product with that `productos_erp.codigo` (none or several: nothing is read or written);
- weight: TN kg <-> `peso_g`; TN width = GBP large <-> `largo_cm`; TN depth = GBP wide <-> `ancho_cm`; height <->
  `alto_cm` (see `tn_publish_core.resolve.map_dimensions` for why width/depth cross over).

The master rule holds: NULL = follow GBP, and a value equal to the GBP one (`tb_item`) is not stored. The ERP tables are
only read.
"""

from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from typing import Iterable, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.producto import ProductoERP
from app.models.producto_propio import ProductoPropio
from app.models.tb_item import TBItem
from app.services.producto_maestro import OVERRIDES, valor_override
from app.services.producto_propio_service import upsert_producto_propio

logger = logging.getLogger(__name__)

# The master columns are Numeric(10, 2) and (12, 2): a value from 10^8 on does not fit (the migration uses the same cap).
MAXIMO = Decimal(100_000_000)

# TN publisher field -> (master column, TN units per master unit)
CAMPOS_TN: dict[str, tuple[str, Decimal]] = {
    "weight": ("peso_g", Decimal(1000)),
    "width": ("largo_cm", Decimal(1)),
    "depth": ("ancho_cm", Decimal(1)),
    "height": ("alto_cm", Decimal(1)),
}


def _item_ids_por_ean(db: Session, eans: Iterable[str]) -> dict[str, int]:
    """EAN -> item_id, only for a code that belongs to exactly one ERP product."""
    eans = set(eans)
    if not eans:
        return {}
    rows = (
        db.query(ProductoERP.codigo, func.min(ProductoERP.item_id), func.count(ProductoERP.item_id))
        .filter(ProductoERP.codigo.in_(eans))
        .group_by(ProductoERP.codigo)
        .all()
    )
    return {codigo: item_id for codigo, item_id, cuantos in rows if cuantos == 1}


def _texto(valor: Decimal) -> str:
    """A Decimal as the publisher's string, without trailing zeros (9500 g -> "9.5")."""
    return format(valor.normalize(), "f")


def medidas_por_ean(db: Session, eans: Iterable[str]) -> dict[str, dict[str, str]]:
    """The master's measurement overrides of each EAN, as the publisher's `{campo: valor}` in TN units. One query
    for the codes and one for the master rows, whatever the number of EANs."""
    item_por_ean = _item_ids_por_ean(db, eans)
    if not item_por_ean:
        return {}
    filas = {
        row.item_id: row
        for row in db.query(ProductoPropio).filter(ProductoPropio.item_id.in_(set(item_por_ean.values()))).all()
    }
    medidas: dict[str, dict[str, str]] = {}
    for ean, item_id in item_por_ean.items():
        row = filas.get(item_id)
        if row is None:
            continue
        valores = {
            campo: _texto(Decimal(getattr(row, columna)) / factor)
            for campo, (columna, factor) in CAMPOS_TN.items()
            if getattr(row, columna) is not None
        }
        if valores:
            medidas[ean] = valores
    return medidas


def _a_maestro(valor: str, factor: Decimal) -> Optional[Decimal]:
    try:
        numero = Decimal(str(valor).strip()) * factor
    except (InvalidOperation, ValueError):
        return None
    return numero if numero.is_finite() and 0 < numero < MAXIMO else None


def guardar_medidas(db: Session, ean: str, medidas: dict[str, str], usuario_id: int) -> bool:
    """Store the publisher's edited measurements (TN units) on the product's master row; the caller commits. False,
    writing nothing, when the EAN is not exactly one ERP product. An unknown field or a value that is not a positive
    number below `MAXIMO` is skipped (logged), so one bad value never loses the others."""
    item_id = _item_ids_por_ean(db, [ean]).get(ean)
    if item_id is None:
        logger.warning("TN publish measurements not stored: ean=%s is not exactly one ERP product", ean)
        return False
    gbp = db.query(TBItem).filter(TBItem.item_id == item_id).order_by(TBItem.comp_id).first()
    values = {}
    for campo, valor in medidas.items():
        if campo not in CAMPOS_TN:
            logger.warning("TN publish measurement skipped: ean=%s has no master column for %s", ean, campo)
            continue
        columna, factor = CAMPOS_TN[campo]
        numero = _a_maestro(valor, factor)
        if numero is None:
            logger.warning(
                "TN publish measurement skipped: ean=%s %s=%r is not a positive number in range", ean, campo, valor
            )
            continue
        values[columna] = valor_override(columna, numero, getattr(gbp, OVERRIDES[columna]) if gbp else None)
    if not values:
        return False
    upsert_producto_propio(db, item_id, {**values, "updated_by": usuario_id})
    return True
