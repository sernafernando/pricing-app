"""The product of a PDF line (vpf-operaciones S3a, S3b, S3): ONE resolver for the load, the manual fixes and, as
SQL, the migration `20261120_vpf_operaciones_overrides` (`RESOLVER_SQL`, keep both in step).

Order: a remembered mapping (`ventas_fuera_codigo_mapeos`, origin 'mapeo') > for a line with a code, the code
trimmed on both sides against `productos_erp.codigo`, then `tb_item.item_code` ('codigo') > for a line without code,
the FIRST whitespace token of its article, trimmed and case-insensitive, against `productos_erp.codigo`, then
`tb_item.item_code` ('prefijo'). A source with more than one product for the value is ambiguous: the line stays sin
producto (it never falls through to a lower source). A manual product of an override ('manual') beats all of them;
the override module applies it on top.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Optional

from sqlalchemy import case, func, literal, select
from sqlalchemy.orm import Session

from app.models.producto import ProductoERP
from app.models.tb_item import TBItem
from app.models.venta_fuera_pdf import VentaFueraCodigoMapeo

ORIGEN_CODIGO, ORIGEN_PREFIJO, ORIGEN_MAPEO, ORIGEN_MANUAL = "codigo", "prefijo", "mapeo", "manual"
# Why a line has no product (the "Sin producto" summary by cause).
CAUSA_MANUAL, CAUSA_SIN_CODIGO, CAUSA_CODIGO = "sin_codigo_manual", "sin_codigo", "codigo_no_encontrado"
_TOKEN = re.compile(r"\s*(\S+)")

Linea = tuple[Optional[str], str]


@dataclass(frozen=True)
class Resolucion:
    item_id: int
    origen: str


def codigo_limpio(codigo: Optional[str]) -> Optional[str]:
    """The code as SQL `NULLIF(btrim(codigo), '')` leaves it."""
    limpio = (codigo or "").strip(" ")
    return limpio or None


def primer_token(articulo: str) -> Optional[str]:
    """The first whitespace token of the article, upper-cased (`upper(substring(articulo from '^\\s*(\\S+)'))`)."""
    hallado = _TOKEN.match(articulo or "")
    return hallado.group(1).upper() if hallado else None


def clave_mapeo(codigo: Optional[str], articulo: str) -> str:
    """The key a remembered mapping is stored under: 'c:' + upper(btrim(codigo)), or for a line without code
    'a:' + upper(btrim(articulo))."""
    limpio = codigo_limpio(codigo)
    return f"c:{limpio.upper()}" if limpio else f"a:{(articulo or '').strip(' ').upper()}"


def clave_mapeo_sql(codigo, articulo):
    """`clave_mapeo` as a SQL expression over a code and an article column."""
    limpio = func.nullif(func.btrim(codigo), "")
    return case(
        (limpio.isnot(None), literal("c:") + func.upper(limpio)),
        else_=literal("a:") + func.upper(func.btrim(articulo)),
    )


def causa_sin_producto(codigo: Optional[str], articulo: str) -> str:
    """Why a line without product has none: a manual line of GBP ("(Manual)" in the article), no code, or a code no
    product has."""
    if codigo_limpio(codigo):
        return CAUSA_CODIGO
    return CAUSA_MANUAL if "(MANUAL)" in (articulo or "").upper() else CAUSA_SIN_CODIGO


def _unicos(db: Session, columna, valores: set[str], item_id_col) -> dict[str, Optional[int]]:
    """`{value: item_id}` for each value one product matches, `{value: None}` for an ambiguous one."""
    if not valores:
        return {}
    filas = db.execute(
        select(columna.label("v"), func.count(func.distinct(item_id_col)), func.min(item_id_col))
        .where(columna.in_(valores))
        .group_by(columna)
    ).all()
    return {v: (item_id if n == 1 else None) for v, n, item_id in filas}


def resolver(db: Session, lineas: Iterable[Linea]) -> dict[Linea, Optional[Resolucion]]:
    """`{(codigo, articulo): Resolucion | None}` for every line, in a fixed number of queries."""
    pares = set(lineas)
    claves = {par: clave_mapeo(*par) for par in pares}
    mapeos = (
        dict(
            db.execute(
                select(VentaFueraCodigoMapeo.clave, VentaFueraCodigoMapeo.item_id).where(
                    VentaFueraCodigoMapeo.clave.in_(set(claves.values()))
                )
            ).all()
        )
        if claves
        else {}
    )
    codigos = {c for c in (codigo_limpio(codigo) for codigo, _ in pares) if c}
    tokens = {t for t in (primer_token(a) for codigo, a in pares if not codigo_limpio(codigo)) if t}
    erp_codigo = _unicos(db, func.btrim(ProductoERP.codigo), codigos, ProductoERP.item_id)
    item_codigo = _unicos(db, func.btrim(TBItem.item_code), codigos, TBItem.item_id)
    erp_token = _unicos(db, func.upper(func.btrim(ProductoERP.codigo)), tokens, ProductoERP.item_id)
    item_token = _unicos(db, func.upper(func.btrim(TBItem.item_code)), tokens, TBItem.item_id)

    def una(par: Linea) -> Optional[Resolucion]:
        if claves[par] in mapeos:
            return Resolucion(mapeos[claves[par]], ORIGEN_MAPEO)
        codigo = codigo_limpio(par[0])
        valor, origen = (codigo, ORIGEN_CODIGO) if codigo else (primer_token(par[1]), ORIGEN_PREFIJO)
        primera, segunda = (erp_codigo, item_codigo) if codigo else (erp_token, item_token)
        if valor is None:
            return None
        if valor in primera:
            item_id = primera[valor]
        else:
            item_id = segunda.get(valor)
        return Resolucion(item_id, origen) if item_id is not None else None

    return {par: una(par) for par in pares}


def item_existe(db: Session, item_id: int) -> bool:
    """Whether a product can be assigned: it is in productos_erp or in tb_item."""
    return bool(
        db.execute(select(ProductoERP.item_id).where(ProductoERP.item_id == item_id)).first()
        or db.execute(select(TBItem.item_id).where(TBItem.item_id == item_id).limit(1)).first()
    )
