"""ODD `metricas-ml-filtros-dinamicos` T1: the shared cross-filter rule behind
the marca / categoría / subcategoría / PM option lists of Métricas ML and
Ventas ML.

Every facet is computed with ALL the active selections except its own, so
choosing anything narrows every OTHER list (in both directions) while the list
being edited can still switch within itself.
"""

from __future__ import annotations

import pytest

from sqlalchemy import select

from app.models.comision_config import SubcategoriaGrupo
from app.models.marca_pm import MarcaPM
from app.models.producto import ProductoERP
from app.models.usuario import Usuario
from app.services.product_facets import ProductSelection, product_combo_rows, product_facet_options

# (marca, categoria, subcategoria_id): the distinct combinations of a screen's
# universe. Epson/Impresoras has two subcategories; HP prints too; Logitech
# sells Perifericos; "Gauss" has no PM at all.
COMBOS = [
    ("Epson", "Impresoras", 10),
    ("Epson", "Impresoras", 11),
    ("Epson", "Insumos", 20),
    ("HP", "Impresoras", 10),
    ("Logitech", "Perifericos", 30),
    ("Gauss", "Perifericos", 31),
]


def _options(db, combos, selection):
    """The way a screen uses the helper: one statement over its universe (here, products)."""
    db.query(ProductoERP).delete()
    for n, (marca, categoria, subcat) in enumerate(combos):
        db.add(ProductoERP(item_id=1000 + n, codigo=f"S{n}", marca=marca, categoria=categoria, subcategoria_id=subcat))
    db.flush()
    rows = product_combo_rows(db, select(ProductoERP.marca, ProductoERP.categoria, ProductoERP.subcategoria_id))
    return product_facet_options(db, rows, selection)


@pytest.fixture()
def seeded(db):
    ana = Usuario(username="ana", email="ana@x.com", nombre="Ana", password_hash="x", activo=True)
    beto = Usuario(username="beto", email="beto@x.com", nombre="Beto", password_hash="x", activo=True)
    db.add_all([ana, beto])
    db.flush()
    db.add_all(
        [
            # Case differs from the product's on purpose: pairs match case-insensitively.
            MarcaPM(marca="EPSON", categoria="IMPRESORAS", usuario_id=ana.id),
            MarcaPM(marca="Epson", categoria="Insumos", usuario_id=ana.id),
            MarcaPM(marca="HP", categoria="Impresoras", usuario_id=beto.id),
            MarcaPM(marca="Logitech", categoria="Perifericos", usuario_id=beto.id),
        ]
    )
    for subcat_id, nombre, categoria in (
        (10, "Laser", "Impresoras"),
        (11, "Tinta", "Impresoras"),
        (20, "Toner", "Insumos"),
        (30, "Mouse", "Perifericos"),
        (31, "Teclado", "Perifericos"),
    ):
        db.add(
            SubcategoriaGrupo(subcat_id=subcat_id, nombre_subcategoria=nombre, nombre_categoria=categoria, grupo_id=1)
        )
    db.commit()
    return {"ana": ana.id, "beto": beto.id}


def _names(options):
    return {
        "marcas": options.marcas,
        "categorias": options.categorias,
        "subcategorias": sorted(s["id"] for g in options.subcategorias for s in g["subcategorias"]),
        "pms": sorted(p["id"] for p in options.pms),
    }


def test_no_selection_offers_everything(db, seeded) -> None:
    options = _options(db, COMBOS, ProductSelection())
    assert _names(options) == {
        "marcas": ["Epson", "Gauss", "HP", "Logitech"],
        "categorias": ["Impresoras", "Insumos", "Perifericos"],
        "subcategorias": [10, 11, 20, 30, 31],
        "pms": sorted(seeded.values()),
    }
    # Subcategories keep the grouped shape the panel already renders.
    assert [g["nombre"] for g in options.subcategorias] == ["Impresoras", "Insumos", "Perifericos"]
    assert {p["id"]: p["nombre"] for p in options.pms} == {seeded["ana"]: "Ana", seeded["beto"]: "Beto"}


def test_marca_narrows_categorias_subcategorias_and_pms(db, seeded) -> None:
    options = _options(db, COMBOS, ProductSelection(marcas=("epson",)))
    assert _names(options) == {
        "marcas": ["Epson", "Gauss", "HP", "Logitech"],  # own facet is not self-restricted
        "categorias": ["Impresoras", "Insumos"],
        "subcategorias": [10, 11, 20],
        "pms": [seeded["ana"]],
    }


def test_subcategoria_narrows_marcas_categorias_and_pms(db, seeded) -> None:
    options = _options(db, COMBOS, ProductSelection(subcategorias=(10,)))
    assert _names(options) == {
        "marcas": ["Epson", "HP"],
        "categorias": ["Impresoras"],
        "subcategorias": [10, 11, 20, 30, 31],
        "pms": sorted(seeded.values()),
    }


def test_pm_narrows_marcas_categorias_and_subcategorias(db, seeded) -> None:
    options = _options(db, COMBOS, ProductSelection(pms=(seeded["beto"],)))
    assert _names(options) == {
        "marcas": ["HP", "Logitech"],
        "categorias": ["Impresoras", "Perifericos"],
        "subcategorias": [10, 30],
        "pms": sorted(seeded.values()),
    }


def test_categoria_narrows_marcas_subcategorias_and_pms(db, seeded) -> None:
    options = _options(db, COMBOS, ProductSelection(categorias=("perifericos",)))
    assert _names(options) == {
        "marcas": ["Gauss", "Logitech"],
        "categorias": ["Impresoras", "Insumos", "Perifericos"],
        "subcategorias": [30, 31],
        "pms": [seeded["beto"]],
    }


def test_selections_combine_and_each_facet_ignores_only_its_own(db, seeded) -> None:
    options = _options(
        db, COMBOS, ProductSelection(marcas=("Epson",), categorias=("Impresoras",), pms=(seeded["ana"],))
    )
    assert _names(options) == {
        "marcas": ["Epson"],  # (Impresoras, Ana) leaves only Epson
        "categorias": ["Impresoras", "Insumos"],  # (Epson, Ana)
        "subcategorias": [10, 11],  # (Epson, Impresoras, Ana)
        "pms": [seeded["ana"]],  # (Epson, Impresoras)
    }


def test_a_pm_without_any_pair_matches_nothing(db, seeded) -> None:
    ghost = Usuario(username="ghost", email="g@x.com", nombre="Sin pares", password_hash="x", activo=True)
    db.add(ghost)
    db.commit()
    options = _options(db, COMBOS, ProductSelection(pms=(ghost.id,)))
    assert _names(options)["marcas"] == []
    assert _names(options)["categorias"] == []
    assert _names(options)["subcategorias"] == []


def test_a_selected_value_stays_offered_even_when_the_others_exclude_it(db, seeded) -> None:
    # Brand and category that never meet: each is still listed so it can be unticked.
    options = _options(db, COMBOS, ProductSelection(marcas=("Logitech",), categorias=("Insumos",)))
    assert "Logitech" in options.marcas
    assert "Insumos" in options.categorias
    # Same for a selected subcategory or PM the others rule out.
    options = _options(db, COMBOS, ProductSelection(marcas=("Logitech",), subcategorias=(10,)))
    assert 10 in _names(options)["subcategorias"]
    options = _options(db, COMBOS, ProductSelection(marcas=("Logitech",), pms=(seeded["ana"],)))
    assert seeded["ana"] in _names(options)["pms"]


def test_duplicate_spellings_collapse_and_blank_values_are_dropped(db, seeded) -> None:
    combos = COMBOS + [("EPSON", "impresoras", 10), (None, "Impresoras", 10), ("", "", None), ("HP", None, None)]
    options = _options(db, combos, ProductSelection())
    # One entry per case-insensitive value, whichever spelling is shown.
    assert [m.upper() for m in options.marcas] == ["EPSON", "GAUSS", "HP", "LOGITECH"]
    assert [c.upper() for c in options.categorias] == ["IMPRESORAS", "INSUMOS", "PERIFERICOS"]


def test_a_selected_id_missing_from_the_universe_is_looked_up_by_name(db, seeded) -> None:
    # Subcategory 11 and the PM "Beto" sell nothing in this universe (Epson only).
    options = _options(db, [("Epson", "Impresoras", 10)], ProductSelection(subcategorias=(11,), pms=(seeded["beto"],)))
    assert [s["nombre"] for g in options.subcategorias for s in g["subcategorias"] if s["id"] == 11] == ["Tinta"]
    assert {p["id"]: p["nombre"] for p in options.pms}[seeded["beto"]] == "Beto"
