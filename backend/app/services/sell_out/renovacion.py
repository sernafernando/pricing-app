"""Renewing a sell-out campaign (campaign system, slice B; owner: "que cuando haya que renovar una campaña por el
quarter no haya que hacer todo de 0").

A renewal is a NEW campaign: `borrador` only proposes it, in the shape `campanas.crear_campana` takes
(`SellOutCampanaIn`), and writes nothing (no row, no audit, no queue entry). The original is never edited, so its
history does not change; a voided campaign can be renewed too, since the draft is a copy.

Copied: the type and its amount (`monto_unit`, `porcentaje` or `monto_total`), `base_porcentaje`, `moneda`,
`tc_modo` (the fixed rate only when it is `fijo`), the caps, `acumulable`, `monto_incluye_iva`, the groups, the
per-product amounts or the `monto_total` shares (only of products the groups still reach: an out-of-reach one would
be refused on create), the program (only while it is active: an archived one takes no campaigns) and the
description. Not copied: the state, what it credited, the `al_cobro` payment rate, the legacy offset and the audit.
The dates default to the calendar quarter after the one holding the original's end, and the name advances its
trailing period, when it has one (`nombre_renovado`).
"""

from __future__ import annotations

import calendar
import re
from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from app.models.sell_out import SellOutCampana, SellOutPrograma
from app.schemas.sell_out import SellOutCampanaIn, SellOutCampanaItemIn
from app.services.sell_out import alcance, campanas

MESES = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)
# A trailing period: "Q4 2026", "4Q26", or a Spanish month with an optional year ("noviembre 2026").
_TRIMESTRE = re.compile(r"(?<!\w)(?P<q>[Qq])(?P<n>[1-4])(?P<sep>[\s-]*)(?P<anio>\d{4})\s*$")
_TRIMESTRE_CORTO = re.compile(r"(?<!\w)(?P<n>[1-4])(?P<q>[Qq])(?P<anio>\d{2})\s*$")
_MES = re.compile(
    r"(?<!\w)(?P<mes>" + "|".join(MESES) + r"|setiembre)(?:(?P<sep>\s+)(?P<anio>\d{4}))?\s*$",
    re.IGNORECASE,
)


def siguiente_trimestre(fecha_hasta: date) -> tuple[date, date]:
    """The calendar quarter after the one holding `fecha_hasta`: its first and last day."""
    trimestre = (fecha_hasta.month - 1) // 3 + 1  # 1..4
    anio = fecha_hasta.year + trimestre // 4
    primer_mes = (trimestre % 4) * 3 + 1
    ultimo_mes = primer_mes + 2
    return date(anio, primer_mes, 1), date(anio, ultimo_mes, calendar.monthrange(anio, ultimo_mes)[1])


def _como(original: str, palabra: str) -> str:
    """`palabra` written in `original`'s case: UPPER, Capitalized or lower."""
    if original.isupper():
        return palabra.upper()
    if original[0].isupper():
        return palabra.capitalize()
    return palabra


def nombre_renovado(nombre: str, desde: date) -> str:
    """`nombre` with its trailing period advanced to the quarter starting on `desde`; any other name exactly as it
    is (production's are models and amounts, like "MARCA PROG 3.0" or "MODELO 8180"). A month becomes the quarter's
    first month."""
    trimestre = (desde.month - 1) // 3 + 1
    if m := _TRIMESTRE.search(nombre):
        return f"{nombre[: m.start()]}{m['q']}{trimestre}{m['sep']}{desde.year}"
    if m := _TRIMESTRE_CORTO.search(nombre):
        return f"{nombre[: m.start()]}{trimestre}{m['q']}{desde.year % 100:02d}"
    if m := _MES.search(nombre):
        mes = _como(m["mes"], MESES[desde.month - 1])
        anio = f"{m['sep']}{desde.year}" if m["anio"] else ""
        return f"{nombre[: m.start()]}{mes}{anio}"
    return nombre


def borrador(db: Session, campana_id: int) -> Optional[SellOutCampanaIn]:
    """The renewal draft of the campaign, active or voided (module docstring); None when it does not exist.
    Read-only."""
    campana = db.get(SellOutCampana, campana_id)
    if campana is None:
        return None
    desde, hasta = siguiente_trimestre(campana.fecha_hasta)
    alcanzados = alcance.productos(db, [campana.id]).get(campana.id, {})
    items = [
        SellOutCampanaItemIn(
            item_id=i["item_id"],
            monto_unit=i["monto_unit"],
            reparto_porcentaje=i["reparto_porcentaje"],
            reparto_monto=i["reparto_monto"],
        )
        for i in campanas._items(db, [campana.id])[campana.id]
        if i["item_id"] in alcanzados and campana.tipo != "porcentaje"
    ]
    programa_id = None
    if campana.programa_id is not None:
        programa = db.get(SellOutPrograma, campana.programa_id)
        programa_id = programa.id if programa is not None and programa.estado == "activo" else None
    return SellOutCampanaIn(
        nombre=nombre_renovado(campana.nombre, desde),
        descripcion=campana.descripcion,
        fecha_desde=desde,
        fecha_hasta=hasta,
        tipo=campana.tipo,
        monto_unit=campana.monto_unit,
        monto_total=campana.monto_total,
        porcentaje=campana.porcentaje,
        base_porcentaje=campana.base_porcentaje,
        moneda=campana.moneda,
        tc_modo=campana.tc_modo,
        tipo_cambio=campana.tipo_cambio if campana.tc_modo == "fijo" else None,
        tope_unidades=campana.tope_unidades,
        tope_monto=campana.tope_monto,
        acumulable=campana.acumulable,
        monto_incluye_iva=campana.monto_incluye_iva,
        grupo_ids=campanas._grupo_ids(db, campana.id),
        items=items,
        programa_id=programa_id,
    )
