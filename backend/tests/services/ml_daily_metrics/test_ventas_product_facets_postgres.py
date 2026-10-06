"""ODD `metricas-ml-filtros-dinamicos` T3 on real Postgres: Ventas ML's product
option lists cascade through the real scope (accreditation, switches, store
EXISTS, pack siblings) -- every filter narrows every other list, never its own."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.services.ml_sales_query.filters import SalesFilter, build_scope, sales_product_options, store_facet_counts

WHEN = datetime(2026, 9, 1, tzinfo=timezone.utc)
ALL_ON = dict(include_unknown=True, include_in_dispute=True, include_mixed=True, include_provisional=True)


@pytest.fixture(autouse=True)
def _seller(monkeypatch):
    monkeypatch.setattr(settings, "ML_USER_ID", 999)


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
    # Four lone sales and one pack (Epson + Logitech items) sold in Gauss / TP-Link stores.
    sales = (
        (2000012345679001, 21, 57997, None),
        (2000012345679002, 22, 2645, None),
        (2000012345679003, 23, 57997, None),
        (2000012345679004, 24, 2645, None),
        (2000012345679005, 21, 57997, 2000099999999001),
        (2000012345679006, 24, 57997, 2000099999999001),
    )
    for order_id, product, store, pack in sales:
        mla = f"MLA{order_id % 10**9}"
        db.execute(
            text(
                "INSERT INTO ml_orders_ops (order_id, seller_id, status, ml_last_updated, date_created, pack_id, "
                "total_amount, paid_amount, currency_id) VALUES (:o, 999, 'paid', :d, :d, :p, 100, 100, 'ARS')"
            ),
            {"o": order_id, "d": WHEN, "p": pack},
        )
        db.execute(
            text("INSERT INTO ml_order_items_ops (order_id, item_id, quantity) VALUES (:o, :mla, 1)"),
            {"o": order_id, "mla": mla},
        )
        db.execute(
            text(
                "INSERT INTO ml_order_item_costos (order_id, item_id, costo_origen, moneda, costo_unitario_ars, "
                "iva_pct, precio_unitario, fuente, producto_item_id, congelado_at) "
                "VALUES (:o, :mla, 1, 'ARS', 1, 21, 10, 't', :p, now())"
            ),
            {"o": order_id, "mla": mla, "p": product},
        )
        db.execute(
            text(
                "INSERT INTO tb_mercadolibre_items_publicados (mlp_id, mlp_publicationid, mlp_official_store_id) "
                "VALUES (:id, :mla, :store)"
            ),
            {"id": order_id % 10**9, "mla": mla, "store": store},
        )
    db.flush()
    return db


def _options(db, **filters):
    f = SalesFilter(**ALL_ON, **filters)
    scope = build_scope(db, f)
    p = sales_product_options(db, f, scope)
    stores, _total = store_facet_counts(scope)
    return {
        "marcas": p.marcas,
        "categorias": p.categorias,
        "subcategorias": sorted(s["id"] for g in p.subcategorias for s in g["subcategorias"]),
        "pms": sorted(x["id"] for x in p.pms),
        "stores": stores,
    }


@pytest.mark.postgres
def test_every_filter_narrows_every_other_list_on_postgres(catalog) -> None:
    db = catalog

    brand = _options(db, marcas=("epson",))
    assert brand["marcas"] == ["Epson", "HP", "Logitech"]
    assert (brand["categorias"], brand["subcategorias"], brand["pms"]) == (["Impresoras", "Insumos"], [10, 20], [901])
    # The pack (Epson + Logitech, Gauss) counts once under its store, the lone Epson sales once each.
    assert brand["stores"] == {"57997": 2, "2645": 1}

    subcat = _options(db, subcategorias=(10,))
    assert (subcat["marcas"], subcat["categorias"], subcat["pms"]) == (["Epson", "HP"], ["Impresoras"], [901, 902])

    pm = _options(db, pms=(902,))
    assert (pm["marcas"], pm["categorias"], pm["subcategorias"]) == (
        ["HP", "Logitech"],
        ["Impresoras", "Perifericos"],
        [10, 30],
    )

    store = _options(db, stores=("2645",))
    assert (store["marcas"], store["categorias"], store["subcategorias"]) == (
        ["Epson", "Logitech"],
        ["Insumos", "Perifericos"],
        [20, 30],
    )

    category = _options(db, categorias=("INSUMOS",))
    assert (category["marcas"], category["subcategorias"], category["pms"]) == (["Epson"], [20], [901])
    assert category["categorias"] == ["Impresoras", "Insumos", "Perifericos"]
