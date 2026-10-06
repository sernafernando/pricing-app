"""ODD `metricas-ml-filtros-dinamicos` T2 on real Postgres: the product option
lists (marca, categoría, subcategoría, PM) and the store counts cascade through
the board's materialized pair table -- every filter narrows every other list,
never its own -- and the `categorias` filter matches case-insensitively."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.services.ml_daily_metrics import board
from tests.services.ml_daily_metrics.test_board_postgres import _group, _order

NOW = datetime(2026, 9, 30, 18, 0, tzinfo=timezone.utc)
TODAY = date(2026, 9, 30)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setattr(settings, "ML_USER_ID", 999)
    monkeypatch.setattr(board, "now_utc", lambda: NOW)


@pytest.fixture()
def catalog(board_pg):
    db = board_pg
    db.execute(
        text(
            "INSERT INTO usuarios (id, nombre) VALUES (901, 'Ana'), (902, 'Beto');"
            "INSERT INTO marcas_pm (marca, categoria, usuario_id) VALUES "
            "('EPSON', 'IMPRESORAS', 901), ('Epson', 'Insumos', 901), ('HP', 'Impresoras', 902), "
            "('Logitech', 'Perifericos', 902);"
            "INSERT INTO subcategorias_grupos (subcat_id, grupo_id, nombre_subcategoria, nombre_categoria) VALUES "
            "(10, 1, 'Laser', 'Impresoras'), (20, 1, 'Toner', 'Insumos'), (30, 1, 'Mouse', 'Perifericos');"
            "INSERT INTO productos_erp (item_id, codigo, descripcion, marca, categoria, subcategoria_id) VALUES "
            "(21, 'S21', 'Epson L3250', 'Epson', 'Impresoras', 10), (22, 'S22', 'Tinta', 'Epson', 'Insumos', 20), "
            "(23, 'S23', 'HP Laser', 'HP', 'Impresoras', 10), (24, 'S24', 'Mouse', 'Logitech', 'Perifericos', 30);"
        )
    )
    for n, (product, store) in enumerate(((21, 57997), (22, 2645), (23, 57997), (24, 2645))):
        mla = f"MLA70000000{product}"
        db.execute(
            text(
                "INSERT INTO tb_mercadolibre_items_publicados (mlp_id, mlp_publicationid, item_id, mlp_official_store_id) "
                "VALUES (:id, :mla, :item, :store)"
            ),
            {"id": 7000 + product, "mla": mla, "item": product, "store": store},
        )
        order_id = 2000012345678930 + n
        _order(db, order_id, [(product, mla, 1, 10)])
        _group(db, f"o:{order_id}", [order_id], NOW - timedelta(hours=3))
    return db


def _facets(db, **filters):
    f = board.BoardFilter(date_from=TODAY - timedelta(days=29), date_to=TODAY, **filters)
    with board.Board(db, f) as b:
        facets = b.facets()
        rows = {row.key for row in b.page(None)}
    p = facets.product
    return {
        "rows": rows,
        "marcas": p.marcas,
        "categorias": p.categorias,
        "subcategorias": sorted(s["id"] for g in p.subcategorias for s in g["subcategorias"]),
        "pms": sorted(x["id"] for x in p.pms),
        "stores": facets.stores,
    }


@pytest.mark.postgres
def test_every_filter_narrows_every_other_list_on_postgres(catalog) -> None:
    db = catalog
    everything = ["Epson", "HP", "Logitech"]

    brand = _facets(db, marcas=("epson",))
    assert brand["rows"] == {"21", "22"}
    assert brand["marcas"] == everything
    assert (brand["categorias"], brand["subcategorias"], brand["pms"]) == (["Impresoras", "Insumos"], [10, 20], [901])
    assert brand["stores"] == {"57997": 1, "2645": 1}

    subcat = _facets(db, subcategorias=(10,))
    assert (subcat["marcas"], subcat["categorias"], subcat["pms"]) == (["Epson", "HP"], ["Impresoras"], [901, 902])
    assert subcat["subcategorias"] == [10, 20, 30]
    assert subcat["stores"] == {"57997": 2}

    pm = _facets(db, pms=(902,))
    assert (pm["marcas"], pm["categorias"], pm["subcategorias"]) == (
        ["HP", "Logitech"],
        ["Impresoras", "Perifericos"],
        [10, 30],
    )
    assert pm["pms"] == [901, 902]

    store = _facets(db, stores=("2645",))
    assert (store["marcas"], store["categorias"], store["subcategorias"]) == (
        ["Epson", "Logitech"],
        ["Insumos", "Perifericos"],
        [20, 30],
    )
    assert store["stores"] == {"57997": 2, "2645": 2}

    category = _facets(db, categorias=("INSUMOS",))
    assert category["rows"] == {"22"}
    assert (category["marcas"], category["subcategorias"], category["pms"]) == (["Epson"], [20], [901])
    assert category["categorias"] == ["Impresoras", "Insumos", "Perifericos"]
    assert category["stores"] == {"2645": 1}
