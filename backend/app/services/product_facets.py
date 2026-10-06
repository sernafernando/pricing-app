"""Cross-filtered option lists for the product facets (marca, categoría,
subcategoría, PM) shared by Métricas ML and Ventas ML (ODD
`metricas-ml-filtros-dinamicos`).

The rule is the standard faceting one: each list is computed with EVERY active
selection except its own, so picking a value narrows all the other lists (in
both directions: brand -> categories, subcategory -> brands, PM -> categories,
category -> PMs...) while the list being edited still offers its siblings.

A screen contributes ONE set-based statement: `product_combo_rows` takes a
select of its universe's `(marca, categoria, subcategoria_id)` rows (under every
non-product filter: period, search, store, status...), reduces them to the
distinct combinations and joins, in the same statement, the subcategory names
(`subcategorias_grupos`) and the PM pairs and names (`marcas_pm` x `usuarios`,
matched case-insensitively -- same rule as `productos_listing`). The cascade
itself (`product_facet_options`) then runs over that small set in memory, so a
screen pays one statement, not one per list.

A selected value is always offered, even when the other selections rule it
out, so the operator can untick it.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, NamedTuple, Optional, Set, Tuple

from pydantic import BaseModel
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.models.comision_config import SubcategoriaGrupo
from app.models.marca_pm import MarcaPM
from app.models.usuario import Usuario

NO_CATEGORY_LABEL = "Sin categoría"


@dataclass(frozen=True)
class ProductSelection:
    """What the operator has ticked. Brand and category compare
    case-insensitively; subcategories and PMs are ids."""

    marcas: Tuple[str, ...] = ()
    categorias: Tuple[str, ...] = ()
    subcategorias: Tuple[int, ...] = ()
    pms: Tuple[int, ...] = ()


class SubcategoriaOption(BaseModel):
    id: int
    nombre: str


class SubcategoriaGroup(BaseModel):
    nombre: str
    subcategorias: List[SubcategoriaOption]


class PmOption(BaseModel):
    id: int
    nombre: str


class ProductFacetOptions(BaseModel):
    """What the four dropdowns offer. `subcategorias` keeps the grouped shape
    (`[{nombre: categoría, subcategorias: [{id, nombre}]}]`) of Productos'
    `/subcategorias`."""

    marcas: List[str] = []
    categorias: List[str] = []
    subcategorias: List[Dict[str, Any]] = []
    pms: List[Dict[str, Any]] = []


class ComboRow(NamedTuple):
    """One distinct combination of the universe, with its lookups: the
    subcategory's name and group, and one PM of the (marca, categoría) pair
    (a combination with no PM has `pm_id=None`)."""

    marca: Optional[str]
    categoria: Optional[str]
    subcategoria_id: Optional[int]
    subcategoria_nombre: Optional[str]
    subcategoria_categoria: Optional[str]
    pm_id: Optional[int]
    pm_nombre: Optional[str]


def _upper(value: Optional[str]) -> str:
    return (value or "").strip().upper()


def product_combo_rows(db: Session, source: Select) -> List[ComboRow]:
    """The universe's distinct combinations, with names, in ONE statement.
    `source` selects `marca`, `categoria` and `subcategoria_id` (in that order,
    duplicates welcome)."""
    if len(source.selected_columns) != 3:
        raise ValueError("source must select exactly (marca, categoria, subcategoria_id)")
    combos = source.distinct().subquery("combos")
    marca, categoria, subcat = combos.c[0], combos.c[1], combos.c[2]
    stmt = (
        select(
            marca,
            categoria,
            subcat,
            SubcategoriaGrupo.nombre_subcategoria,
            SubcategoriaGrupo.nombre_categoria,
            MarcaPM.usuario_id,
            Usuario.nombre,
        )
        .select_from(combos)
        .outerjoin(SubcategoriaGrupo, SubcategoriaGrupo.subcat_id == subcat)
        .outerjoin(
            MarcaPM,
            (func.upper(MarcaPM.marca) == func.upper(marca)) & (func.upper(MarcaPM.categoria) == func.upper(categoria)),
        )
        .outerjoin(Usuario, Usuario.id == MarcaPM.usuario_id)
    )
    return [ComboRow(*row) for row in db.execute(stmt)]


def _distinct_spellings(values: Iterable[Optional[str]], selected: Iterable[str] = ()) -> List[str]:
    """One entry per case-insensitive value (the spelling that sorts last, so
    "Epson" wins over "EPSON"), blanks dropped, sorted case-insensitively. A
    `selected` value the universe lacks is added as typed; one it has keeps
    the universe's spelling."""
    shown: Dict[str, str] = {}
    for value in values:
        key = _upper(value)
        if key:
            shown[key] = max(shown.get(key, value), value)  # type: ignore[arg-type]
    for value in selected:
        shown.setdefault(_upper(value), value)
    shown.pop("", None)
    return [shown[key] for key in sorted(shown)]


def product_facet_options(db: Session, rows: Iterable[ComboRow], selection: ProductSelection) -> ProductFacetOptions:
    """The four option lists for `rows` (`product_combo_rows`) under `selection`."""
    # One entry per (marca, categoría, subcategoría) key, in upper case.
    keys: Dict[Tuple[str, str, Optional[int]], Tuple[Optional[str], Optional[str], Set[int]]] = {}
    sub_names: Dict[int, Tuple[str, str]] = {}
    pm_names: Dict[int, str] = {}
    for row in rows:
        key = (_upper(row.marca), _upper(row.categoria), row.subcategoria_id)
        seen = keys.get(key)
        pms: Set[int] = set(seen[2]) if seen else set()
        if row.pm_id is not None:
            pms.add(row.pm_id)
            pm_names[row.pm_id] = row.pm_nombre or str(row.pm_id)
        # Same value spelled twice ("EPSON"/"Epson"): keep the spelling that sorts last.
        keys[key] = (
            max(seen[0] or "", row.marca or "") or None if seen else row.marca,
            max(seen[1] or "", row.categoria or "") or None if seen else row.categoria,
            pms,
        )
        if row.subcategoria_id is not None and row.subcategoria_nombre:
            sub_names[row.subcategoria_id] = (row.subcategoria_nombre, row.subcategoria_categoria or NO_CATEGORY_LABEL)

    sel_marcas = {_upper(m) for m in selection.marcas}
    sel_categorias = {_upper(c) for c in selection.categorias}
    sel_subs = set(selection.subcategorias)
    sel_pms = set(selection.pms)

    def survivors(
        skip: str,
    ) -> List[Tuple[Tuple[str, str, Optional[int]], Tuple[Optional[str], Optional[str], Set[int]]]]:
        out = []
        for key, value in keys.items():
            if skip != "marcas" and sel_marcas and key[0] not in sel_marcas:
                continue
            if skip != "categorias" and sel_categorias and key[1] not in sel_categorias:
                continue
            if skip != "subcategorias" and sel_subs and key[2] not in sel_subs:
                continue
            # A PM with no pairs intersects nothing: it matches no product (never every one).
            if skip != "pms" and sel_pms and not (value[2] & sel_pms):
                continue
            out.append((key, value))
        return out

    marcas = _distinct_spellings([v[0] for _, v in survivors("marcas")], selection.marcas)
    categorias = _distinct_spellings([v[1] for _, v in survivors("categorias")], selection.categorias)
    sub_ids: Set[int] = {key[2] for key, _ in survivors("subcategorias") if key[2] is not None} | sel_subs
    pm_ids: Set[int] = set(sel_pms)
    for _, value in survivors("pms"):
        pm_ids |= value[2]

    # A SELECTED value the universe does not hold has no name in `rows`: look it
    # up. (A universe value with no name is just not offered, like Productos.)
    missing_subs = {i for i in sel_subs if i not in sub_names}
    if missing_subs:
        for subcat_id, nombre, categoria in db.execute(
            select(
                SubcategoriaGrupo.subcat_id, SubcategoriaGrupo.nombre_subcategoria, SubcategoriaGrupo.nombre_categoria
            ).where(SubcategoriaGrupo.subcat_id.in_(missing_subs))
        ):
            if nombre:
                sub_names[subcat_id] = (nombre, categoria or NO_CATEGORY_LABEL)
    missing_pms = {i for i in sel_pms if i not in pm_names}
    if missing_pms:
        for user_id, nombre in db.execute(select(Usuario.id, Usuario.nombre).where(Usuario.id.in_(missing_pms))):
            pm_names[user_id] = nombre or str(user_id)

    grouped: Dict[str, List[SubcategoriaOption]] = defaultdict(list)
    for sub_id in sorted(sub_ids, key=lambda i: (sub_names.get(i, ("", ""))[1], sub_names.get(i, ("", ""))[0])):
        if sub_id in sub_names:
            nombre, grupo = sub_names[sub_id]
            grouped[grupo].append(SubcategoriaOption(id=sub_id, nombre=nombre))
    return ProductFacetOptions(
        marcas=marcas,
        categorias=categorias,
        subcategorias=[
            SubcategoriaGroup(nombre=grupo, subcategorias=subs).model_dump() for grupo, subs in sorted(grouped.items())
        ],
        pms=[
            PmOption(id=pm_id, nombre=pm_names[pm_id]).model_dump()
            for pm_id in sorted(pm_ids, key=lambda i: (pm_names.get(i, ""), i))
            if pm_id in pm_names
        ],
    )
