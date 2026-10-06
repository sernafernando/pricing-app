"""Cross-filtered option lists for the product facets (marca, categoría,
subcategoría, PM) shared by Métricas ML and Ventas ML (ODD
`metricas-ml-filtros-dinamicos`).

The rule is the standard faceting one: each list is computed with EVERY active
selection except its own, so picking a value narrows all the other lists (in
both directions: brand -> categories, subcategory -> brands, PM -> categories,
category -> PMs...) while the list being edited still offers its siblings.

The caller reads ONE set-based query of the distinct `(marca, categoria,
subcategoria_id)` combinations present in the screen's universe (under every
non-product filter: period, search, store, status...) and hands the rows here;
the cascade itself runs over that small set in memory, so it costs one extra
statement per screen instead of one per list. PMs are never joined in SQL: the
pair table `marcas_pm` is tiny and is read whole, matched case-insensitively
(`PM pairs`, same rule as `productos_listing`).

A selected value is always offered, even when the other selections rule it
out, so the operator can untick it.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.comision_config import SubcategoriaGrupo
from app.models.marca_pm import MarcaPM
from app.models.usuario import Usuario

NO_CATEGORY_LABEL = "Sin categoría"

Combo = Tuple[Optional[str], Optional[str], Optional[int]]


@dataclass(frozen=True)
class ProductSelection:
    """What the operator has ticked. Brand and category compare
    case-insensitively; subcategories and PMs are ids."""

    marcas: Tuple[str, ...] = ()
    categorias: Tuple[str, ...] = ()
    subcategorias: Tuple[int, ...] = ()
    pms: Tuple[int, ...] = ()

    @property
    def any(self) -> bool:
        return bool(self.marcas or self.categorias or self.subcategorias or self.pms)


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


def _upper(value: Optional[str]) -> str:
    return (value or "").strip().upper()


def _pm_ids_by_pair(db: Session) -> Dict[Tuple[str, str], Set[int]]:
    pairs: Dict[Tuple[str, str], Set[int]] = defaultdict(set)
    for marca, categoria, usuario_id in db.execute(select(MarcaPM.marca, MarcaPM.categoria, MarcaPM.usuario_id)):
        if usuario_id is not None:
            pairs[(_upper(marca), _upper(categoria))].add(int(usuario_id))
    return pairs


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


def product_facet_options(db: Session, combos: Iterable[Combo], selection: ProductSelection) -> ProductFacetOptions:
    """The four option lists for `combos` (the universe's distinct
    `(marca, categoria, subcategoria_id)` rows) under `selection`."""
    pm_by_pair = _pm_ids_by_pair(db)
    universe: Dict[Tuple[str, str, Optional[int]], Tuple[Optional[str], Optional[str], Set[int]]] = {}
    for marca, categoria, subcategoria_id in combos:
        key = (_upper(marca), _upper(categoria), subcategoria_id)
        seen = universe.get(key)
        if seen is None:
            universe[key] = (marca, categoria, pm_by_pair.get((key[0], key[1]), set()))
        else:
            # Same value spelled twice ("EPSON"/"Epson"): keep the spelling that sorts last.
            universe[key] = (
                max(seen[0] or "", marca or "") or None,
                max(seen[1] or "", categoria or "") or None,
                seen[2],
            )

    sel_marcas = {_upper(m) for m in selection.marcas}
    sel_categorias = {_upper(c) for c in selection.categorias}
    sel_subs = set(selection.subcategorias)
    sel_pms = set(selection.pms)

    def passes(key: Tuple[str, str, Optional[int]], pms: Set[int], skip: str) -> bool:
        if skip != "marcas" and sel_marcas and key[0] not in sel_marcas:
            return False
        if skip != "categorias" and sel_categorias and key[1] not in sel_categorias:
            return False
        if skip != "subcategorias" and sel_subs and key[2] not in sel_subs:
            return False
        # A PM with no pairs intersects nothing: it matches no product (never every one).
        if skip != "pms" and sel_pms and not (pms & sel_pms):
            return False
        return True

    def survivors(skip: str):
        return [
            (key, spelled, pms)
            for key, spelled, pms in ((k, v[:2], v[2]) for k, v in universe.items())
            if passes(key, pms, skip)
        ]

    marcas = _distinct_spellings([s[0] for _, s, _ in survivors("marcas")], selection.marcas)
    categorias = _distinct_spellings([s[1] for _, s, _ in survivors("categorias")], selection.categorias)

    sub_ids: Set[int] = {key[2] for key, _, _ in survivors("subcategorias") if key[2] is not None} | sel_subs
    pm_ids: Set[int] = set(sel_pms)
    for _, _, pms in survivors("pms"):
        pm_ids |= pms

    return ProductFacetOptions(
        marcas=marcas,
        categorias=categorias,
        subcategorias=_subcategoria_groups(db, sub_ids),
        pms=_pm_options(db, pm_ids),
    )


def _subcategoria_groups(db: Session, sub_ids: Set[int]) -> List[Dict[str, Any]]:
    if not sub_ids:
        return []
    grouped: Dict[str, List[SubcategoriaOption]] = defaultdict(list)
    rows = db.execute(
        select(SubcategoriaGrupo.subcat_id, SubcategoriaGrupo.nombre_subcategoria, SubcategoriaGrupo.nombre_categoria)
        .where(SubcategoriaGrupo.subcat_id.in_(sub_ids))
        .order_by(SubcategoriaGrupo.nombre_categoria, SubcategoriaGrupo.nombre_subcategoria)
    )
    for subcat_id, nombre, categoria in rows:
        if nombre:
            grouped[categoria or NO_CATEGORY_LABEL].append(SubcategoriaOption(id=subcat_id, nombre=nombre))
    return [
        SubcategoriaGroup(nombre=categoria, subcategorias=subs).model_dump()
        for categoria, subs in sorted(grouped.items())
    ]


def _pm_options(db: Session, pm_ids: Set[int]) -> List[Dict[str, Any]]:
    if not pm_ids:
        return []
    rows = db.execute(select(Usuario.id, Usuario.nombre).where(Usuario.id.in_(pm_ids)).order_by(Usuario.nombre))
    return [PmOption(id=user_id, nombre=nombre or str(user_id)).model_dump() for user_id, nombre in rows]
