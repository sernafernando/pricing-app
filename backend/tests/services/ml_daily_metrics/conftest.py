"""Real-Postgres fixtures for the Métricas ML board: the tables it reads
(orders, items, frozen costs, stored metrics and their dirty queue, group
rows, the ERP publication mirror, the sync cursors and a minimal
`productos_erp`), plus the payments and deductions Ventas ML's KPI aggregate
reads for the parity checks. Created only if missing and dropped again afterwards; the
seed rows of each test live in a transaction that is rolled back."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, inspect as sa_inspect, text
from sqlalchemy.orm import sessionmaker

PRODUCTOS_MIN_DDL = """
CREATE TABLE productos_erp (
    item_id INTEGER PRIMARY KEY,
    codigo VARCHAR(100),
    descripcion VARCHAR(500),
    marca VARCHAR(100),
    categoria VARCHAR(100),
    subcategoria_id INTEGER,
    stock INTEGER
)
"""


# The product-facet option lists read the PM pairs, the subcategory names and the
# PM user names: minimal copies (only the columns read) when no other fixture
# left the real tables.
FACET_LOOKUPS_DDL = {
    "marcas_pm": "CREATE TABLE marcas_pm (id SERIAL PRIMARY KEY, marca VARCHAR(100), categoria VARCHAR(100), "
    "usuario_id INTEGER)",
    "subcategorias_grupos": "CREATE TABLE subcategorias_grupos (id SERIAL PRIMARY KEY, subcat_id INTEGER, "
    "grupo_id INTEGER, nombre_subcategoria VARCHAR(200), cat_id VARCHAR(10), nombre_categoria VARCHAR(200), "
    "oculta BOOLEAN)",
    "usuarios": "CREATE TABLE usuarios (id SERIAL PRIMARY KEY, nombre VARCHAR(255))",
}


@pytest.fixture(scope="module")
def board_pg_engine():
    from tests.conftest import (
        POSTGRES_TEST_URL,
        _patch_pg_types_for_sqlite,
        _postgres_reachable,
        _restore_pristine_pg_types,
    )

    if not _postgres_reachable():
        pytest.skip(f"PostgreSQL not reachable at {POSTGRES_TEST_URL}")

    from app.models.mercadolibre_item_publicado import MercadoLibreItemPublicado
    from app.models.ml_group_metrics import MlGroupMetrics
    from app.models.ml_order_item_costo import MlOrderItemCosto
    from app.models.ml_order_metrics import MlOrderMetrics, MlOrderMetricsDirty
    from app.models.ml_orders_ops import (
        MlOperationLink,
        MlOpsSyncCursor,
        MlOrderItemOps,
        MlOrdersOps,
        MlShipmentOps,
    )
    from app.models.rma_claim_ml import RmaClaimML
    from app.models.ml_payments import MlPaymentOps
    from app.models.ml_venta_deduccion import MlVentaDeduccion

    tables = [
        MlOrdersOps.__table__,
        MlOrderItemOps.__table__,
        MlOrderItemCosto.__table__,
        MlOrderMetrics.__table__,
        MlOrderMetricsDirty.__table__,
        MlGroupMetrics.__table__,
        MercadoLibreItemPublicado.__table__,
        MlOpsSyncCursor.__table__,
        # Ventas ML's KPI aggregate (the parity checks) reads these too.
        MlPaymentOps.__table__,
        MlVentaDeduccion.__table__,
        # Ventas ML's scope (status, claims) reads these for the product option lists.
        MlShipmentOps.__table__,
        MlOperationLink.__table__,
        RmaClaimML.__table__,
    ]
    _restore_pristine_pg_types(tables)
    engine = create_engine(POSTGRES_TEST_URL)
    created = [t for t in tables if not sa_inspect(engine).has_table(t.name)]
    for table in created:
        table.create(engine)
    created_productos = not sa_inspect(engine).has_table("productos_erp")
    if created_productos:
        with engine.begin() as conn:
            conn.execute(text(PRODUCTOS_MIN_DDL))
    created_lookups = [name for name in FACET_LOOKUPS_DDL if not sa_inspect(engine).has_table(name)]
    with engine.begin() as conn:
        for name in created_lookups:
            conn.execute(text(FACET_LOOKUPS_DDL[name]))
    # Hand the shared Column types back to the SQLite suite (ARRAY -> JSON):
    # leaving them pristine breaks every SQLite test that runs after this
    # module in the same process.
    _patch_pg_types_for_sqlite()
    yield engine
    for table in reversed(created):
        table.drop(engine, checkfirst=True)
    if created_productos:
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS productos_erp"))
    with engine.begin() as conn:
        for name in created_lookups:
            conn.execute(text(f"DROP TABLE IF EXISTS {name}"))
    engine.dispose()


@pytest.fixture()
def board_pg(board_pg_engine):
    """A session inside a transaction that is rolled back after the test."""
    connection = board_pg_engine.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection)()
    yield session
    session.close()
    transaction.rollback()
    connection.close()
