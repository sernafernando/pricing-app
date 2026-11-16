"""A throwaway Postgres schema with the tables the Tienda Nube catalog sync and the product <-> TN link read and write
(abm-productos T6), and `get_background_db()` pointed at it. Imported by the sync, handler and router tests."""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import sessionmaker

from app.models.producto import ProductoERP
from app.models.producto_propio import ProductoPropio
from app.models.producto_tn_vinculo import ProductoTnVinculo
from app.models.tienda_nube_producto import TiendaNubeProducto
from app.models.tienda_nube_producto_texto import TiendaNubeProductoTexto
from tests.conftest import (
    POSTGRES_TEST_URL,
    _patch_pg_types_for_sqlite,
    _postgres_reachable,
    _restore_pristine_pg_types,
)

TABLES = [
    ProductoERP.__table__,
    ProductoPropio.__table__,
    TiendaNubeProducto.__table__,
    TiendaNubeProductoTexto.__table__,
    ProductoTnVinculo.__table__,
]


@pytest.fixture()
def tn_pg(monkeypatch: pytest.MonkeyPatch) -> Iterator[Engine]:
    if not _postgres_reachable():
        pytest.skip(f"PostgreSQL not reachable at {POSTGRES_TEST_URL}")
    _restore_pristine_pg_types(TABLES)
    schema = f"tn_vinc_{uuid.uuid4().hex[:8]}"
    admin = create_engine(POSTGRES_TEST_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f"CREATE SCHEMA {schema}"))
    engine = create_engine(POSTGRES_TEST_URL, connect_args={"options": f"-csearch_path={schema}"})
    try:
        with engine.begin() as conn:
            for table in TABLES:
                table.create(bind=conn)
            # The unique key the sync upserts on: production has it from its migration, the model does not declare it.
            conn.execute(text("CREATE UNIQUE INDEX ON tienda_nube_productos (product_id, variant_id)"))
        monkeypatch.setattr("app.core.database.SessionLocal", sessionmaker(bind=engine, autoflush=False))
        yield engine
    finally:
        _patch_pg_types_for_sqlite()
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        admin.dispose()


def erp(conn, item_id: int, codigo: str, descripcion: str) -> None:
    conn.execute(
        text("INSERT INTO productos_erp (item_id, codigo, descripcion) VALUES (:i, :c, :d)"),
        {"i": item_id, "c": codigo, "d": descripcion},
    )


def tn_product(
    product_id: int,
    name: str,
    skus: list[str],
    *,
    description: str | None = None,
    published: bool = True,
    price: str = "100.00",
) -> dict:
    """One entry of TN's `GET /v1/{store}/products`, the shape the sync reads: `name` and `description` per language,
    product-level `published`, one variant per SKU."""
    product: dict = {
        "id": product_id,
        "name": {"es": name},
        "published": published,
        "variants": [
            {"id": product_id * 10 + n, "sku": sku, "price": price, "compare_at_price": None, "promotional_price": None}
            for n, sku in enumerate(skus)
        ],
    }
    if description is not None:
        product["description"] = {"es": description}
    return product


def links(conn) -> dict[int, int | None]:
    """TN product id -> the `item_id` its variants carry (all variants of a product carry the same one)."""
    rows = conn.execute(text("SELECT DISTINCT product_id, item_id FROM tienda_nube_productos")).all()
    return {product_id: item_id for product_id, item_id in rows}
