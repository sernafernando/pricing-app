"""ProductoERP against production's `productos_erp` table: `moneda_costo` there is VARCHAR.

The table predates the migrations, so other tests build it from the ORM and never saw
that the model declared `moneda_costo` a native enum: no `tipomoneda` type exists in
production. The column holds 'ARS' or 'USD' (2026-10-27).
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import sessionmaker
from sqlalchemy.schema import CreateTable

from app.models.producto import ProductoERP, TipoMoneda

pytestmark = pytest.mark.postgres

PRODUCTION_DDL = [
    """
    CREATE TABLE productos_erp (
        item_id INTEGER PRIMARY KEY,
        codigo VARCHAR(100),
        descripcion VARCHAR(500),
        marca VARCHAR(100),
        categoria VARCHAR(100),
        subcategoria_id INTEGER,
        costo DOUBLE PRECISION,
        moneda_costo VARCHAR,
        iva DOUBLE PRECISION,
        envio DOUBLE PRECISION,
        stock INTEGER,
        activo BOOLEAN,
        fecha_sync TIMESTAMP WITH TIME ZONE DEFAULT now(),
        updated_at TIMESTAMP WITH TIME ZONE,
        hash_datos VARCHAR(64)
    )
    """,
]


@pytest.fixture()
def Session():
    from tests.conftest import POSTGRES_TEST_URL, _postgres_reachable

    if not _postgres_reachable():
        pytest.skip(f"PostgreSQL not reachable at {POSTGRES_TEST_URL}")
    schema = f"productos_erp_{uuid.uuid4().hex[:8]}"
    admin = create_engine(POSTGRES_TEST_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f"CREATE SCHEMA {schema}"))
    eng = create_engine(POSTGRES_TEST_URL, connect_args={"options": f"-csearch_path={schema}"})
    try:
        with eng.begin() as conn:
            for statement in PRODUCTION_DDL:
                conn.execute(text(statement))
        yield sessionmaker(bind=eng)
    finally:
        eng.dispose()
        with admin.connect() as conn:
            conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        admin.dispose()


def test_the_model_declares_the_currency_as_text_like_production():
    # A native enum makes every schema built from the ORM (tests, a fresh database) create a
    # `tipomoneda` type that production never had.
    ddl = str(CreateTable(ProductoERP.__table__).compile(dialect=postgresql.dialect()))
    assert "moneda_costo VARCHAR(3)" in ddl
    assert "tipomoneda" not in ddl


def test_several_rows_in_one_flush_store_the_currency_as_text(Session):
    # The sync always supplies `item_id`, so a multi-row flush is a plain VALUES list with no cast
    # to an enum type; the stored text must stay 'USD' / 'ARS' and read back as TipoMoneda.
    with Session() as db:
        db.add_all(
            [
                ProductoERP(item_id=1, moneda_costo=TipoMoneda.USD),
                ProductoERP(item_id=2, moneda_costo=TipoMoneda.ARS),
            ]
        )
        db.commit()
    with Session() as db:
        stored = db.execute(text("SELECT moneda_costo FROM productos_erp ORDER BY item_id")).scalars().all()
        assert stored == ["USD", "ARS"]
        assert [p.moneda_costo for p in db.query(ProductoERP).order_by(ProductoERP.item_id)] == [
            TipoMoneda.USD,
            TipoMoneda.ARS,
        ]
