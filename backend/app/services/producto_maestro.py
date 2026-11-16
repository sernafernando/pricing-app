"""The product master (abm-productos T4, S9 + S13): every ERP product with its GBP data, our overrides and its texts.

`productos_propios` holds only what an operator set; everything else is read live:
- Overrides: NULL = follow GBP. A stored value is an override and is shown next to the GBP value. A value equal to the
  GBP one is not stored, so "overrideado" always means "different from GBP". Nothing is ever written to the ERP tables.
- Texts (título ML / web, descripción ML / web): the chosen source is followed live (`ml`: the winning publication,
  `tn`: the Tienda Nube product, `gbp`, `nombre`: the product name); `propio` is an own text, stored and fixed. No
  source chosen = the first source of the text with a value.
- Units per closed box: the Gestión Full row (`gestion_full_unidades_caja`), written through its audited service, so
  the ABM and Gestión Full always show the same value.

The winning publication for the ML texts: a live linked one (not gone, not deleted at ML), active first, then the most
recently updated on ML, then the lowest MLA id.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.models.gestion_full_unidades_caja import GestionFullUnidadesCaja
from app.models.producto_propio import ProductoPropio
from app.models.usuario import Usuario
from app.services.gestion_full.unidades_caja import clear_unidades_caja, upsert_unidades_caja
from app.services.producto_propio_service import upsert_producto_propio
from app.services.producto_specs.campos import NOTEBOOK, PC, SUBCATEGORIAS_EXCLUIDAS, campos_de
from app.services.producto_specs.store import completos_sql

PROPIO = "propio"
SIN_CAMBIO = object()  # `unidades_caja` left out of the edit


class DatoNoValido(ValueError):
    """An edit that cannot be stored (unknown brand, a subcategory of another category, a blank own text)."""


# Overridable field -> the column of `_LEER_SQL` holding its GBP value.
OVERRIDES: dict[str, str] = {
    "nombre": "descripcion",
    "ean": "codigo",
    "codigo_fabricante": "gbp_codigo_fabricante",
    "marca_id": "brand_id",
    "categoria_id": "cat_id",
    "subcategoria_id": "subcat_id",
    "garantia_dias": "gbp_garantia",
    "peso_g": "item_weight",
    "ancho_cm": "item_wide",
    "largo_cm": "item_large",
    "alto_cm": "item_higth",
}
_NUMERICOS = {"peso_g", "ancho_cm", "largo_cm", "alto_cm"}


@dataclass(frozen=True)
class Texto:
    columna: str  # the own text, read only when the source is `propio`
    fuente: str  # the chosen source column
    fuentes: tuple[str, ...]  # in default order


TEXTOS: dict[str, Texto] = {
    "titulo_ml": Texto("titulo", "fuente_titulo_ml", ("ml", "tn", "gbp")),
    "titulo_web": Texto("titulo_web", "fuente_titulo_web", ("tn", "ml", "nombre")),
    "descripcion_ml": Texto("descripcion", "fuente_descripcion_ml", ("ml", "tn", "gbp")),
    "descripcion_web": Texto("descripcion_web", "fuente_descripcion_web", ("tn", "ml", "gbp")),
}

_LEER_SQL = text("""
    SELECT p.item_id, p.codigo, p.descripcion, p.costo, p.moneda_costo, p.iva, p.stock,
           t.brand_id, t.cat_id, t.subcat_id, t.item_weight, t.item_wide, t.item_large, t.item_higth,
           t.raw ->> 'item_vendorCode' AS gbp_codigo_fabricante, t.raw ->> 'item_guarantee' AS gbp_garantia,
           t.raw ->> 'item_ML_title' AS gbp_titulo, t.raw ->> 'item_ML_desc' AS gbp_descripcion,
           (SELECT s.supp_name FROM tb_supplier s WHERE s.supp_id::text = t.raw ->> 'supp_id'
            ORDER BY s.comp_id LIMIT 1) AS proveedor,
           (SELECT pr.precio_lista_ml FROM productos_pricing pr WHERE pr.item_id = p.item_id) AS precio_lista_ml
    FROM productos_erp p
    LEFT JOIN LATERAL (SELECT * FROM tb_item ti WHERE ti.item_id = p.item_id ORDER BY ti.comp_id LIMIT 1) t ON true
    WHERE p.item_id = :item_id
""")

_GANADORA_SQL = text("""
    SELECT m.item_id, m.title, d.raw ->> 'plain_text' AS descripcion
    FROM ml_item_product_links l
    JOIN ml_items m ON m.item_id = l.item_id
    LEFT JOIN ml_item_descriptions d ON d.item_id = m.item_id
    WHERE l.producto_item_id = :item_id AND l.match_status = 'linked'
      AND m.gone_at IS NULL AND ('deleted' = ANY(m.sub_status)) IS NOT TRUE
    ORDER BY (m.status = 'active') DESC NULLS LAST, m.ml_last_updated DESC NULLS LAST, m.item_id
    LIMIT 1
""")

_PUBLICACIONES_SQL = text("""
    SELECT count(DISTINCT item_id) FROM ml_item_product_links WHERE producto_item_id = :item_id
      AND match_status = 'linked'
""")

_TN_SQL = text("""
    SELECT product_id, product_name, published FROM tienda_nube_productos
    WHERE item_id = :item_id AND activo IS TRUE ORDER BY product_id LIMIT 1
""")


def _numero(value: Any) -> Any:
    """A Decimal as a JSON number: an int when whole."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    return value


def _entero(value: Optional[str]) -> Optional[int]:
    try:
        return int(Decimal(value)) if value not in (None, "") else None
    except (InvalidOperation, ValueError):
        return None


def _gbp(db: Session, item_id: int) -> Optional[dict[str, Any]]:
    row = db.execute(_LEER_SQL, {"item_id": item_id}).mappings().first()
    if row is None:
        return None
    gbp = dict(row)
    gbp["gbp_garantia"] = _entero(gbp["gbp_garantia"])
    return gbp


def _marca(db: Session, brand_id: Optional[int]) -> Optional[str]:
    if brand_id is None:
        return None
    return db.execute(
        text("SELECT brand_desc FROM tb_brand WHERE brand_id = :b ORDER BY comp_id LIMIT 1"), {"b": brand_id}
    ).scalar()


def _categoria(db: Session, cat_id: Optional[int]) -> Optional[str]:
    if cat_id is None:
        return None
    return db.execute(
        text("SELECT cat_desc FROM tb_category WHERE cat_id = :c ORDER BY comp_id LIMIT 1"), {"c": cat_id}
    ).scalar()


def _subcategoria(db: Session, cat_id: Optional[int], subcat_id: Optional[int]) -> Optional[str]:
    if subcat_id is None:
        return None
    return db.execute(
        text(
            "SELECT subcat_desc FROM tb_subcategory WHERE subcat_id = :s "
            "ORDER BY (cat_id IS NOT DISTINCT FROM :c) DESC, comp_id LIMIT 1"
        ),
        {"c": cat_id, "s": subcat_id},
    ).scalar()


def _tipo_specs(cat_id: Optional[int], subcat_id: Optional[int]) -> Optional[str]:
    if cat_id == 46 and subcat_id not in SUBCATEGORIAS_EXCLUIDAS:
        return NOTEBOOK
    return PC if cat_id == 47 else None


def _campos(db: Session, gbp: dict[str, Any], row: Optional[ProductoPropio]) -> dict[str, dict[str, Any]]:
    campos: dict[str, dict[str, Any]] = {}
    for campo, columna in OVERRIDES.items():
        manual = getattr(row, campo) if row is not None else None
        original = _numero(gbp[columna])
        campos[campo] = {
            "valor": _numero(manual) if manual is not None else original,
            "gbp": original,
            "overrideado": manual is not None,
        }
    marca, cat, sub = campos["marca_id"], campos["categoria_id"], campos["subcategoria_id"]
    marca.update(nombre=_marca(db, marca["valor"]), gbp_nombre=_marca(db, marca["gbp"]))
    cat.update(nombre=_categoria(db, cat["valor"]), gbp_nombre=_categoria(db, cat["gbp"]))
    sub.update(
        nombre=_subcategoria(db, cat["valor"], sub["valor"]), gbp_nombre=_subcategoria(db, cat["gbp"], sub["gbp"])
    )
    return campos


def _textos(gbp: dict[str, Any], row: Optional[ProductoPropio], nombre: Optional[str], ganadora, tn) -> dict:
    disponibles = {
        "titulo": {
            "ml": ganadora.title if ganadora else None,
            "tn": tn.product_name if tn else None,
            "gbp": gbp["gbp_titulo"],
            "nombre": nombre,
        },
        # The Tienda Nube description is not stored yet: the TN sync brings it in a later delivery (S12).
        "descripcion": {
            "ml": ganadora.descripcion if ganadora else None,
            "tn": None,
            "gbp": gbp["gbp_descripcion"],
        },
    }
    textos = {}
    for clave, texto in TEXTOS.items():
        valores = disponibles["titulo" if clave.startswith("titulo") else "descripcion"]
        fuentes = {fuente: valores[fuente] or None for fuente in texto.fuentes}
        elegida = getattr(row, texto.fuente) if row is not None else None
        if elegida == PROPIO:
            fuente, valor = PROPIO, getattr(row, texto.columna)
        elif elegida is not None:
            fuente, valor = elegida, fuentes.get(elegida)
        else:
            fuente = next((f for f in texto.fuentes if fuentes[f]), None)
            valor = fuentes[fuente] if fuente else None
        textos[clave] = {"fuente": fuente, "elegida": elegida is not None, "valor": valor, "fuentes": fuentes}
    return textos


def leer(db: Session, item_id: int) -> Optional[dict[str, Any]]:
    """The product as the master shows it; None when the ERP has no such product."""
    gbp = _gbp(db, item_id)
    if gbp is None:
        return None
    row = db.get(ProductoPropio, item_id)
    campos = _campos(db, gbp, row)
    ganadora = db.execute(_GANADORA_SQL, {"item_id": item_id}).first()
    tn = db.execute(_TN_SQL, {"item_id": item_id}).first()
    unidades = db.get(GestionFullUnidadesCaja, item_id)
    return {
        "item_id": item_id,
        "codigo": gbp["codigo"],
        "tipo_specs": _tipo_specs(gbp["cat_id"], gbp["subcat_id"]),
        "campos": campos,
        "unidades_caja": unidades.unidades if unidades is not None else None,
        "textos": _textos(gbp, row, campos["nombre"]["valor"], ganadora, tn),
        "mla_ganadora": ganadora.item_id if ganadora else None,
        "lectura": {
            "costo": gbp["costo"],
            "moneda_costo": gbp["moneda_costo"],
            "iva": gbp["iva"],
            "stock": gbp["stock"],
            "precio_lista_ml": gbp["precio_lista_ml"],
            "proveedor": gbp["proveedor"],
            "publicaciones_ml": db.execute(_PUBLICACIONES_SQL, {"item_id": item_id}).scalar_one(),
            "tn_producto_id": tn.product_id if tn else None,
            "tn_publicado": tn.published if tn else None,
        },
    }


def _override(campo: str, valor: Any, gbp: Any) -> Any:
    """What is stored for an edited field: None (follow GBP) when blank or equal to the GBP value."""
    if isinstance(valor, str):
        valor = valor.strip() or None
    if valor is None:
        return None
    if campo in _NUMERICOS:
        return None if gbp is not None and Decimal(str(valor)) == Decimal(str(gbp)) else valor
    return None if valor == gbp else valor


def _validar_clasificacion(db: Session, efectivos: dict[str, Optional[int]], editados: set[str]) -> None:
    if "marca_id" in editados and efectivos["marca_id"] is not None and _marca(db, efectivos["marca_id"]) is None:
        raise DatoNoValido(f"No existe la marca {efectivos['marca_id']}")
    cat, subcat = efectivos["categoria_id"], efectivos["subcategoria_id"]
    if "categoria_id" in editados and cat is not None and _categoria(db, cat) is None:
        raise DatoNoValido(f"No existe la categoría {cat}")
    if editados & {"categoria_id", "subcategoria_id"} and subcat is not None:
        pertenece = db.execute(
            text("SELECT 1 FROM tb_subcategory WHERE cat_id IS NOT DISTINCT FROM :c AND subcat_id = :s LIMIT 1"),
            {"c": cat, "s": subcat},
        ).first()
        if pertenece is None:
            raise DatoNoValido(f"La subcategoría {subcat} no pertenece a la categoría {cat}")


def _texto_values(clave: str, fuente: Optional[str], contenido: Optional[str]) -> dict[str, Any]:
    texto = TEXTOS[clave]
    if fuente is not None and fuente != PROPIO and fuente not in texto.fuentes:
        raise DatoNoValido(f"{clave}: la fuente {fuente} no aplica")
    propio = (contenido or "").strip() if fuente == PROPIO else None
    if fuente == PROPIO and not propio:
        raise DatoNoValido(f"{clave}: el texto propio no puede quedar vacío")
    return {texto.fuente: fuente, texto.columna: propio}


def guardar(
    db: Session,
    item_id: int,
    cambios: dict[str, Any],
    textos: dict[str, tuple[Optional[str], Optional[str]]],
    usuario: Usuario,
    unidades_caja: Any = SIN_CAMBIO,
) -> Optional[dict[str, Any]]:
    """Apply an edit and commit; None when the product is unknown. Fields left out keep their value; None goes back
    to GBP (or to the default text source). `textos`: clave -> (fuente, texto). Raises `DatoNoValido` before
    writing anything."""
    gbp = _gbp(db, item_id)
    if gbp is None:
        return None
    row = db.get(ProductoPropio, item_id, with_for_update=True)
    values = {campo: _override(campo, valor, gbp[OVERRIDES[campo]]) for campo, valor in cambios.items()}
    efectivos = {}
    for campo in ("marca_id", "categoria_id", "subcategoria_id"):
        manual = values[campo] if campo in values else (getattr(row, campo) if row is not None else None)
        efectivos[campo] = manual if manual is not None else gbp[OVERRIDES[campo]]
    _validar_clasificacion(db, efectivos, set(values))
    for clave, (fuente, contenido) in textos.items():
        values.update(_texto_values(clave, fuente, contenido))
    if values:
        upsert_producto_propio(db, item_id, {**values, "updated_by": usuario.id})
    # The Gestión Full service commits this whole transaction together with its audit row.
    if unidades_caja is None:
        clear_unidades_caja(db, producto_item_id=item_id, usuario=usuario)
    elif unidades_caja is not SIN_CAMBIO:
        upsert_unidades_caja(db, producto_item_id=item_id, unidades=unidades_caja, usuario=usuario)
    db.commit()
    return leer(db, item_id)


def listar(
    db: Session,
    *,
    tipo: Optional[str] = None,
    marca: Optional[str] = None,
    q: Optional[str] = None,
    incompletos: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> tuple[int, list[dict[str, Any]]]:
    """Every ERP product with its effective name, EAN and brand, ordered by stock. Notebooks and PCs carry how many of
    their spec fields are complete; `incompletos` keeps the ones with an applicable field still empty."""
    sql = f"""
        WITH base AS (
            SELECT p.item_id, p.codigo, COALESCE(pp.ean, p.codigo) AS ean,
                   COALESCE(pp.nombre, p.descripcion) AS nombre, COALESCE(b.brand_desc, p.marca) AS marca, p.stock,
                   CASE WHEN t.cat_id = 46 AND COALESCE(t.subcat_id, -1) NOT IN :excluidas THEN 'notebook'
                        WHEN t.cat_id = 47 THEN 'pc' END AS tipo
            FROM productos_erp p
            LEFT JOIN LATERAL (SELECT ti.cat_id, ti.subcat_id FROM tb_item ti WHERE ti.item_id = p.item_id
                               ORDER BY ti.comp_id LIMIT 1) t ON true
            LEFT JOIN productos_propios pp ON pp.item_id = p.item_id
            LEFT JOIN LATERAL (SELECT tb.brand_desc FROM tb_brand tb WHERE tb.brand_id = pp.marca_id
                               ORDER BY tb.comp_id LIMIT 1) b ON true
        ), conteo AS (
            SELECT b.*,
                   CASE b.tipo WHEN 'pc' THEN COALESCE({completos_sql(PC)}, 0)
                               WHEN 'notebook' THEN COALESCE({completos_sql(NOTEBOOK)}, 0) END AS specs_completos,
                   CASE b.tipo WHEN 'pc' THEN {len(campos_de(PC))}
                               WHEN 'notebook' THEN {len(campos_de(NOTEBOOK))} END AS specs_total
            FROM base b
            LEFT JOIN producto_specs s ON s.item_id = b.item_id
        )
        SELECT c.*, count(*) OVER () AS filas FROM conteo c
        WHERE (CAST(:tipo AS text) IS NULL OR c.tipo = :tipo)
          AND (CAST(:marca AS text) IS NULL OR upper(c.marca) = upper(:marca))
          AND (CAST(:q AS text) IS NULL OR c.nombre ILIKE :like OR c.ean ILIKE :like OR c.codigo ILIKE :like
               OR CAST(c.item_id AS text) = :q)
          AND (NOT :incompletos OR c.specs_completos < c.specs_total)
        ORDER BY COALESCE(c.stock, 0) DESC, c.nombre, c.item_id
        LIMIT :limit OFFSET :offset
    """
    q_clean = (q or "").strip() or None
    rows = db.execute(
        text(sql).bindparams(bindparam("excluidas", expanding=True)),
        {
            "excluidas": list(SUBCATEGORIAS_EXCLUIDAS),
            "tipo": tipo,
            "marca": (marca or "").strip() or None,
            "q": q_clean,
            "like": f"%{q_clean}%" if q_clean else None,
            "incompletos": incompletos,
            "limit": limit,
            "offset": offset,
        },
    ).all()
    total = rows[0].filas if rows else 0
    return total, [{k: v for k, v in row._mapping.items() if k != "filas"} for row in rows]
