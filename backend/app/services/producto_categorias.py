"""Categories, subcategories and brands masters (abm-productos delivery 2+3, S11, L10).

- Seeded from GBP with the same ids; the seed inserts only missing ids, so it re-runs on every ERP master sync and never
  touches a local name, state or link.
- `nombre` NULL follows GBP's name. Setting a name equal to GBP's stores NULL, so "overrideado" means "differs from GBP".
  Clearing it (None) goes back to GBP's name; an own row has no GBP name, so it cannot.
- Own rows get ids from `PRIMER_ID_PROPIO` up. Only an own subcategory may move to another category (GBP keeps its tree).
- A category or subcategory links to one Tienda Nube category of the mirrored tree (`tn_category_embedding`). A
  subcategory without its own link uses its category's (`tn_category_efectiva`).
- The TN suggestion reuses the embeddings suggester (`embed_category_text` + `suggest_category_for_embedding`); for a
  subcategory it is kept inside the branch of its category's link when there is one. Nothing is linked automatically.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional, Union

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.models.producto_categoria import PRIMER_ID_PROPIO, ProductoCategoria, ProductoSubcategoria
from app.models.producto_marca import ProductoMarca
from app.models.tn_category_embedding import TnCategoryEmbedding
from app.services.tn_category_embedding_service import suggest_category_for_embedding

# Same statements as the migration `20261117_producto_categorias_marcas` (a test pins them equal).
SEED_SQL = (
    "INSERT INTO producto_categorias (id, activa, propia) "
    "SELECT DISTINCT cat_id, true, false FROM tb_category WHERE cat_id IS NOT NULL "
    "ON CONFLICT (id) DO NOTHING",
    "INSERT INTO producto_subcategorias (id, categoria_id, activa, propia) "
    "SELECT s.subcat_id, MIN(s.cat_id), true, false FROM tb_subcategory s "
    "JOIN producto_categorias c ON c.id = s.cat_id WHERE s.subcat_id IS NOT NULL GROUP BY s.subcat_id "
    "ON CONFLICT (id) DO NOTHING",
    "INSERT INTO producto_marcas (id, activa, propia) "
    "SELECT DISTINCT brand_id, true, false FROM tb_brand WHERE brand_id IS NOT NULL "
    "ON CONFLICT (id) DO NOTHING",
)

NOMBRE_MAX = 255
SUGERENCIAS = 5
_SUGERENCIAS_RAMA = 20  # asked from the embeddings before keeping only the category's branch

Fila = Union[ProductoCategoria, ProductoSubcategoria, ProductoMarca]


class NoEncontrado(LookupError):
    """The category, subcategory or brand does not exist (404)."""


class Invalido(ValueError):
    """The change breaks a master rule (422)."""


# GBP owns its tree: a GBP subcategory moved to another (already seeded) category follows it. Own rows never move here.
_SEGUIR_GBP_SQL = (
    "UPDATE producto_subcategorias SET categoria_id = ("
    "SELECT MIN(s.cat_id) FROM tb_subcategory s WHERE s.subcat_id = producto_subcategorias.id) "
    "WHERE propia = false AND categoria_id <> ("
    "SELECT MIN(s.cat_id) FROM tb_subcategory s WHERE s.subcat_id = producto_subcategorias.id) "
    "AND (SELECT MIN(s.cat_id) FROM tb_subcategory s WHERE s.subcat_id = producto_subcategorias.id) "
    "IN (SELECT id FROM producto_categorias)"
)


def sembrar_desde_gbp(db: Session) -> dict[str, int]:
    """Insert the GBP categories, subcategories and brands that are not in the masters yet, and move a GBP subcategory
    GBP moved. Names, states and TN links are never touched. The caller commits."""
    counts = [db.execute(text(statement)).rowcount or 0 for statement in SEED_SQL]
    db.execute(text(_SEGUIR_GBP_SQL))
    return dict(zip(("categorias", "subcategorias", "marcas"), counts))


# --- reading -------------------------------------------------------------------------------------------------------


def _pares(db: Session, sql: str) -> dict[int, Any]:
    return {row[0]: row[1] for row in db.execute(text(sql)).all()}


def _gbp_categorias(db: Session) -> dict[int, str]:
    return _pares(db, "SELECT cat_id, MIN(cat_desc) FROM tb_category GROUP BY cat_id")


def _gbp_subcategorias(db: Session) -> dict[int, str]:
    return _pares(db, "SELECT subcat_id, MIN(subcat_desc) FROM tb_subcategory GROUP BY subcat_id")


def _gbp_marcas(db: Session) -> dict[int, str]:
    return _pares(db, "SELECT brand_id, MIN(brand_desc) FROM tb_brand GROUP BY brand_id")


def _productos_por(db: Session, columna: str) -> dict[int, int]:
    # Products are counted by their GBP category/subcategory/brand (`tb_item`).
    return _pares(
        db, f"SELECT {columna}, COUNT(DISTINCT item_id) FROM tb_item WHERE {columna} IS NOT NULL GROUP BY {columna}"
    )


def _tn_paths(db: Session) -> dict[int, str]:
    rows = db.query(TnCategoryEmbedding.tn_category_id, TnCategoryEmbedding.category_path_text).all()
    return {tn_id: path for tn_id, path in rows}


def _base(row: Fila, gbp: dict[int, str], productos: dict[int, int]) -> dict[str, Any]:
    nombre_gbp = None if row.propia else gbp.get(row.id)
    return {
        "id": row.id,
        "nombre": row.nombre if row.nombre is not None else nombre_gbp,
        "nombre_gbp": nombre_gbp,
        "overrideado": row.nombre is not None and not row.propia,
        "propia": row.propia,
        "activa": row.activa,
        "productos": productos.get(row.id, 0),
    }


def _vinculo(cat_link: Optional[int], sub_links: list[Optional[int]]) -> str:
    """completo: every subcategory ends at a TN category (or the category itself is linked and has none); parcial: some
    do; ninguno: none."""
    efectivos = [link or cat_link for link in sub_links] if sub_links else [cat_link]
    linked = sum(1 for link in efectivos if link)
    if linked == len(efectivos):
        return "completo"
    return "parcial" if linked else "ninguno"


@dataclass
class _Contexto:
    gbp_cats: dict[int, str] = field(default_factory=dict)
    gbp_subs: dict[int, str] = field(default_factory=dict)
    prod_cats: dict[int, int] = field(default_factory=dict)
    prod_subs: dict[int, int] = field(default_factory=dict)
    tn: dict[int, str] = field(default_factory=dict)


def _contexto(db: Session) -> _Contexto:
    return _Contexto(
        gbp_cats=_gbp_categorias(db),
        gbp_subs=_gbp_subcategorias(db),
        prod_cats=_productos_por(db, "cat_id"),
        prod_subs=_productos_por(db, "subcat_id"),
        tn=_tn_paths(db),
    )


def _subcategoria(sub: ProductoSubcategoria, cat: ProductoCategoria, ctx: _Contexto) -> dict[str, Any]:
    efectiva = sub.tn_category_id or cat.tn_category_id
    return {
        **_base(sub, ctx.gbp_subs, ctx.prod_subs),
        "categoria_id": sub.categoria_id,
        "tn_category_id": sub.tn_category_id,
        "tn_categoria": ctx.tn.get(sub.tn_category_id) if sub.tn_category_id else None,
        "tn_category_id_efectiva": efectiva,
        "tn_categoria_efectiva": ctx.tn.get(efectiva) if efectiva else None,
        "tn_heredada": sub.tn_category_id is None and cat.tn_category_id is not None,
    }


def _categoria(cat: ProductoCategoria, subs: list[ProductoSubcategoria], ctx: _Contexto) -> dict[str, Any]:
    return {
        **_base(cat, ctx.gbp_cats, ctx.prod_cats),
        "tn_category_id": cat.tn_category_id,
        "tn_categoria": ctx.tn.get(cat.tn_category_id) if cat.tn_category_id else None,
        "vinculo_tn": _vinculo(cat.tn_category_id, [s.tn_category_id for s in subs]),
        "subcategorias": [_subcategoria(s, cat, ctx) for s in subs],
    }


def _subs_de(db: Session, categoria_id: int) -> list[ProductoSubcategoria]:
    return (
        db.query(ProductoSubcategoria)
        .filter(ProductoSubcategoria.categoria_id == categoria_id)
        .order_by(ProductoSubcategoria.id)
        .all()
    )


def listar_categorias(db: Session) -> list[dict[str, Any]]:
    """Every category (active or not) with its subcategories, names, product counts and TN links."""
    ctx = _contexto(db)
    subs_por_cat: dict[int, list[ProductoSubcategoria]] = {}
    for sub in db.query(ProductoSubcategoria).order_by(ProductoSubcategoria.id).all():
        subs_por_cat.setdefault(sub.categoria_id, []).append(sub)
    cats = db.query(ProductoCategoria).order_by(ProductoCategoria.id).all()
    return [_categoria(cat, subs_por_cat.get(cat.id, []), ctx) for cat in cats]


def leer_categoria(db: Session, categoria_id: int) -> dict[str, Any]:
    cat = _get(db, ProductoCategoria, categoria_id)
    return _categoria(cat, _subs_de(db, cat.id), _contexto(db))


def leer_subcategoria(db: Session, subcategoria_id: int) -> dict[str, Any]:
    sub = _get(db, ProductoSubcategoria, subcategoria_id)
    return _subcategoria(sub, _get(db, ProductoCategoria, sub.categoria_id), _contexto(db))


def tn_category_efectiva(db: Session, categoria_id: Optional[int], subcategoria_id: Optional[int]) -> Optional[int]:
    """The TN category of a product: its subcategory's link, else its category's link, else None."""
    if subcategoria_id is not None:
        sub = db.get(ProductoSubcategoria, subcategoria_id)
        if sub is not None and sub.tn_category_id is not None:
            return sub.tn_category_id
    cat = db.get(ProductoCategoria, categoria_id) if categoria_id is not None else None
    return cat.tn_category_id if cat is not None else None


def listar_tn_categorias(db: Session, q: str = "", limit: int = 500) -> list[dict[str, Any]]:
    """The mirrored TN tree for the picker, optionally filtered by a case-insensitive substring of the path."""
    query = db.query(TnCategoryEmbedding.tn_category_id, TnCategoryEmbedding.category_path_text)
    if q.strip():
        query = query.filter(TnCategoryEmbedding.category_path_text.icontains(q.strip(), autoescape=True))
    rows = query.order_by(TnCategoryEmbedding.category_path_text).limit(limit).all()
    return [{"tn_category_id": tn_id, "category_path": path} for tn_id, path in rows]


# --- writing -------------------------------------------------------------------------------------------------------


def _get(db: Session, model: type, row_id: int) -> Any:
    row = db.get(model, row_id)
    if row is None:
        raise NoEncontrado(f"{model.__tablename__} {row_id} no existe")
    return row


def _limpio(nombre: Optional[str]) -> str:
    valor = (nombre or "").strip()
    if not valor:
        raise Invalido("El nombre no puede estar vacío")
    if len(valor) > NOMBRE_MAX:
        raise Invalido(f"El nombre no puede superar {NOMBRE_MAX} caracteres")
    return valor


def _nuevo_id(db: Session, model: type) -> int:
    ultimo = db.query(func.max(model.id)).filter(model.id >= PRIMER_ID_PROPIO).scalar()
    return PRIMER_ID_PROPIO if ultimo is None else ultimo + 1


def _tocar(row: Fila, user_id: Optional[int]) -> None:
    row.updated_by = user_id
    row.updated_at = datetime.now(timezone.utc)


def _renombrar(row: Fila, nombre: Optional[str], gbp: dict[int, str]) -> None:
    if nombre is None:
        if row.propia:
            raise Invalido("Una fila propia no tiene un valor de GBP al que volver")
        row.nombre = None
        return
    valor = _limpio(nombre)
    row.nombre = None if not row.propia and valor == gbp.get(row.id) else valor


def _vincular_tn(db: Session, row: Fila, tn_category_id: Optional[int]) -> None:
    if tn_category_id is not None:
        existe = db.query(TnCategoryEmbedding.id).filter(TnCategoryEmbedding.tn_category_id == tn_category_id).first()
        if existe is None:
            raise Invalido(f"La categoría de Tienda Nube {tn_category_id} no existe; actualizá la lista desde TN")
    row.tn_category_id = tn_category_id


def _aplicar(db: Session, row: Fila, cambios: dict[str, Any], gbp: dict[int, str]) -> None:
    if "nombre" in cambios:
        _renombrar(row, cambios["nombre"], gbp)
    if cambios.get("activa") is not None:
        row.activa = cambios["activa"]
    if "tn_category_id" in cambios:
        _vincular_tn(db, row, cambios["tn_category_id"])


def crear_categoria(db: Session, nombre: str, user_id: Optional[int]) -> dict[str, Any]:
    cat = ProductoCategoria(id=_nuevo_id(db, ProductoCategoria), nombre=_limpio(nombre), activa=True, propia=True)
    _tocar(cat, user_id)
    db.add(cat)
    db.flush()
    return leer_categoria(db, cat.id)


def editar_categoria(db: Session, categoria_id: int, cambios: dict[str, Any], user_id: Optional[int]) -> dict[str, Any]:
    """`cambios` holds only the fields sent: `nombre` (None = back to GBP), `activa`, `tn_category_id` (None = unlink)."""
    cat = _get(db, ProductoCategoria, categoria_id)
    _aplicar(db, cat, cambios, _gbp_categorias(db))
    _tocar(cat, user_id)
    db.flush()
    return leer_categoria(db, cat.id)


def crear_subcategoria(db: Session, categoria_id: int, nombre: str, user_id: Optional[int]) -> dict[str, Any]:
    _get(db, ProductoCategoria, categoria_id)
    sub = ProductoSubcategoria(
        id=_nuevo_id(db, ProductoSubcategoria),
        categoria_id=categoria_id,
        nombre=_limpio(nombre),
        activa=True,
        propia=True,
    )
    _tocar(sub, user_id)
    db.add(sub)
    db.flush()
    return leer_subcategoria(db, sub.id)


def editar_subcategoria(
    db: Session, subcategoria_id: int, cambios: dict[str, Any], user_id: Optional[int]
) -> dict[str, Any]:
    """Like `editar_categoria`, plus `categoria_id` to move an own subcategory to another category."""
    sub = _get(db, ProductoSubcategoria, subcategoria_id)
    destino = cambios.get("categoria_id")
    if destino is not None and destino != sub.categoria_id:
        if not sub.propia:
            raise Invalido("Una subcategoría de GBP no se puede mover de categoría")
        _get(db, ProductoCategoria, destino)
        sub.categoria_id = destino
    _aplicar(db, sub, cambios, _gbp_subcategorias(db))
    _tocar(sub, user_id)
    db.flush()
    return leer_subcategoria(db, sub.id)


def texto_sugerencia_categoria(db: Session, categoria_id: int) -> tuple[str, Optional[str]]:
    """What to rank TN categories for: the category's name; no branch restriction."""
    return leer_categoria(db, categoria_id)["nombre"] or "", None


def texto_sugerencia_subcategoria(db: Session, subcategoria_id: int) -> tuple[str, Optional[str]]:
    """What to rank TN categories for: "<category> > <subcategory>", and the TN path of the category's link (the branch
    the suggestion stays in) when it has one."""
    sub = leer_subcategoria(db, subcategoria_id)
    cat = leer_categoria(db, sub["categoria_id"])
    return f"{cat['nombre']} > {sub['nombre']}", cat["tn_categoria"]


def sugerencias_tn(db: Session, embedding: Optional[list[float]], rama: Optional[str]) -> dict[str, Any]:
    """TN categories nearest to `embedding` (from `embed_category_text`, called by the caller without a DB session),
    kept inside `rama` when given. Empty, never an error, when the embedder was unavailable."""
    result = suggest_category_for_embedding(db, embedding, top_n=_SUGERENCIAS_RAMA if rama else SUGERENCIAS)
    sugerencias = result["suggestions"]
    if rama:
        sugerencias = [
            s
            for s in sugerencias
            if s["category_path_text"] == rama or s["category_path_text"].startswith(f"{rama} > ")
        ]
    sugerencias = sugerencias[:SUGERENCIAS]
    return {"sugerencias": sugerencias, "top": sugerencias[0] if sugerencias else None}


# --- brands --------------------------------------------------------------------------------------------------------


def _marca(row: ProductoMarca, gbp: dict[int, str], productos: dict[int, int]) -> dict[str, Any]:
    return _base(row, gbp, productos)


def listar_marcas(db: Session) -> list[dict[str, Any]]:
    gbp, productos = _gbp_marcas(db), _productos_por(db, "brand_id")
    return [_marca(row, gbp, productos) for row in db.query(ProductoMarca).order_by(ProductoMarca.id).all()]


def crear_marca(db: Session, nombre: str, user_id: Optional[int]) -> dict[str, Any]:
    row = ProductoMarca(id=_nuevo_id(db, ProductoMarca), nombre=_limpio(nombre), activa=True, propia=True)
    _tocar(row, user_id)
    db.add(row)
    db.flush()
    return _marca(row, {}, {})


def editar_marca(db: Session, marca_id: int, cambios: dict[str, Any], user_id: Optional[int]) -> dict[str, Any]:
    """`cambios` holds only the fields sent: `nombre` (None = back to GBP) and `activa`."""
    row = _get(db, ProductoMarca, marca_id)
    gbp = _gbp_marcas(db)
    _aplicar(db, row, {k: v for k, v in cambios.items() if k != "tn_category_id"}, gbp)
    _tocar(row, user_id)
    db.flush()
    return _marca(row, gbp, _productos_por(db, "brand_id"))
