"""The link between an ERP product and its Tienda Nube product (abm-productos S12).

The TN sync links variants by SKU (`tienda_nube_productos.item_id`); a link set by hand lives in `producto_tn_vinculos`
and is applied over the SKU match on every sync and right after it is saved
(`tienda_nube_sync_shared.aplicar_vinculos_manuales`). One product links to one TN product.

Suggestions for a product: first the TN products with a variant SKU equal to its EAN (the master's EAN override, else
the ERP `codigo`), both compared without leading zeros and without the `-OB` suffix; then the TN products whose name
shares the most words with the product's name.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.tienda_nube_sync_shared import aplicar_vinculos_manuales

MAX_CANDIDATOS = 20
MAX_POR_NOMBRE = 10
# A name suggestion shares at least this many words and this share of the shorter name's words.
MIN_PALABRAS = 2
MIN_COINCIDENCIA = 0.5


class ProductoNoEncontrado(LookupError):
    pass


class TnProductoNoEncontrado(LookupError):
    pass


@dataclass(frozen=True)
class TnYaVinculado(Exception):
    item_id: int


# One TN product (all its variants): name, SKUs, the lowest variant price, published if any variant is, and the ERP
# product its variants carry today.
_RESUMEN_SQL = """
    SELECT product_id,
           MAX(product_name) AS nombre,
           COALESCE(ARRAY_AGG(DISTINCT variant_sku ORDER BY variant_sku)
                    FILTER (WHERE variant_sku IS NOT NULL AND variant_sku <> ''), '{{}}') AS skus,
           MIN(price) AS precio,
           BOOL_OR(published) AS published,
           MAX(item_id) AS item_id
    FROM tienda_nube_productos
    WHERE {where}
    GROUP BY product_id
"""

# The EAN / SKU as compared for suggestions: upper case, no `-OB` suffix, no leading zeros.
_NORMALIZADO = "REGEXP_REPLACE(REGEXP_REPLACE(UPPER(TRIM({col})), '-OB$', ''), '^0+', '')"


def _resumen(row: Any) -> dict[str, Any]:
    return {
        "tn_product_id": row.product_id,
        "nombre": row.nombre,
        "skus": list(row.skus),
        "precio": float(row.precio) if row.precio is not None else None,
        "published": row.published,
        "item_id": row.item_id,
    }


def _producto(db: Session, item_id: int) -> Any:
    row = db.execute(
        text(
            "SELECT pe.item_id, pe.descripcion, COALESCE(pp.ean, pe.codigo) AS ean FROM productos_erp pe "
            "LEFT JOIN productos_propios pp ON pp.item_id = pe.item_id WHERE pe.item_id = :i"
        ),
        {"i": item_id},
    ).one_or_none()
    if row is None:
        raise ProductoNoEncontrado(item_id)
    return row


def tn_producto(db: Session, tn_product_id: int) -> Optional[dict[str, Any]]:
    row = db.execute(text(_RESUMEN_SQL.format(where="product_id = :p")), {"p": tn_product_id}).one_or_none()
    return _resumen(row) if row is not None else None


def vinculo_actual(db: Session, item_id: int) -> dict[str, Any]:
    """`{origen, tn}`: `origen` is "manual" (set by hand; `tn` None when set as not linked), "sku" (the sync's SKU
    match) or None (not linked)."""
    _producto(db, item_id)
    manual = db.execute(
        text("SELECT tn_product_id FROM producto_tn_vinculos WHERE item_id = :i"), {"i": item_id}
    ).one_or_none()
    if manual is not None:
        tn = tn_producto(db, manual.tn_product_id) if manual.tn_product_id is not None else None
        return {"origen": "manual", "tn": tn}
    product_id = db.execute(
        text("SELECT MIN(product_id) FROM tienda_nube_productos WHERE item_id = :i AND activo = true"),
        {"i": item_id},
    ).scalar()
    if product_id is None:
        return {"origen": None, "tn": None}
    return {"origen": "sku", "tn": tn_producto(db, product_id)}


def guardar_vinculo(db: Session, item_id: int, tn_product_id: Optional[int], user_id: int) -> None:
    """Stores the link set by hand (None: not linked) and applies it at once. The caller commits."""
    _producto(db, item_id)
    if tn_product_id is not None:
        if tn_producto(db, tn_product_id) is None:
            raise TnProductoNoEncontrado(tn_product_id)
        otro = db.execute(
            text("SELECT item_id FROM producto_tn_vinculos WHERE tn_product_id = :p AND item_id <> :i"),
            {"p": tn_product_id, "i": item_id},
        ).scalar()
        if otro is not None:
            raise TnYaVinculado(otro)
    db.execute(
        text("""
            INSERT INTO producto_tn_vinculos (item_id, tn_product_id, updated_by, updated_at)
            VALUES (:i, :p, :u, NOW())
            ON CONFLICT (item_id) DO UPDATE
            SET tn_product_id = EXCLUDED.tn_product_id, updated_by = EXCLUDED.updated_by, updated_at = NOW()
        """),
        {"i": item_id, "p": tn_product_id, "u": user_id},
    )
    aplicar_vinculos_manuales(db)


def _palabras(nombre: Optional[str]) -> set[str]:
    return {w for w in re.split(r"[^0-9a-záéíóúñü]+", (nombre or "").lower()) if len(w) >= 2}


def candidatos(db: Session, item_id: int, q: Optional[str]) -> list[dict[str, Any]]:
    """With `q`: active TN products whose name or a SKU contains it (motivo "busqueda"). Without: the suggestions, by
    EAN (motivo "ean") then by name (motivo "nombre")."""
    producto = _producto(db, item_id)
    q = (q or "").strip()
    if q:
        pattern = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        rows = db.execute(
            text(
                _RESUMEN_SQL.format(
                    where="activo = true AND product_id IN (SELECT product_id FROM tienda_nube_productos "
                    "WHERE product_name ILIKE :q OR variant_sku ILIKE :q)"
                )
                + " ORDER BY MAX(product_name), product_id LIMIT :n"
            ),
            {"q": pattern, "n": MAX_CANDIDATOS},
        ).all()
        return [{**_resumen(r), "motivo": "busqueda"} for r in rows]

    por_ean: list[dict[str, Any]] = []
    if producto.ean:
        rows = db.execute(
            text(
                _RESUMEN_SQL.format(
                    where="activo = true AND product_id IN (SELECT product_id FROM tienda_nube_productos "
                    f"WHERE {_NORMALIZADO.format(col='variant_sku')} = {_NORMALIZADO.format(col=':ean')} "
                    "AND variant_sku <> '')"
                )
                + " ORDER BY product_id"
            ),
            {"ean": producto.ean},
        ).all()
        por_ean = [{**_resumen(r), "motivo": "ean"} for r in rows]

    vistos = {c["tn_product_id"] for c in por_ean}
    propias = _palabras(producto.descripcion)
    puntuados = []
    if propias:
        for row in db.execute(text(_RESUMEN_SQL.format(where="activo = true"))).all():
            if row.product_id in vistos:
                continue
            ajenas = _palabras(row.nombre)
            comunes = len(propias & ajenas)
            if comunes < MIN_PALABRAS:
                continue
            coincidencia = comunes / min(len(propias), len(ajenas))
            if coincidencia >= MIN_COINCIDENCIA:
                puntuados.append((-coincidencia, -comunes, row.product_id, row))
    puntuados.sort(key=lambda t: t[:3])
    por_nombre = [{**_resumen(t[3]), "motivo": "nombre"} for t in puntuados[:MAX_POR_NOMBRE]]
    return (por_ean + por_nombre)[:MAX_CANDIDATOS]
