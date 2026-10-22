"""Auditoria against production's `auditoria` table: `es_masivo` there is boolean.

The table predates the migrations, so other tests build it from the ORM and never
saw that the model declared `es_masivo` an Integer: every service writing
`es_masivo=0` failed in production with a DatatypeMismatch. The table below is
production's, column by column (information_schema, 2026-10-22).
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.models.auditoria import Auditoria, TipoAccion

pytestmark = pytest.mark.postgres

PRODUCTION_DDL = [
    "CREATE TABLE usuarios (id INTEGER PRIMARY KEY)",
    "INSERT INTO usuarios VALUES (7)",
    """
    CREATE TABLE auditoria (
        id SERIAL PRIMARY KEY,
        item_id INTEGER,
        usuario_id INTEGER NOT NULL REFERENCES usuarios (id),
        tipo_accion VARCHAR NOT NULL,
        valores_anteriores JSONB,
        valores_nuevos JSONB,
        es_masivo BOOLEAN DEFAULT false,
        productos_afectados INTEGER,
        comentario VARCHAR,
        fecha TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now()
    )
    """,
]


@pytest.fixture()
def Session():
    from tests.conftest import POSTGRES_TEST_URL, _postgres_reachable

    if not _postgres_reachable():
        pytest.skip(f"PostgreSQL not reachable at {POSTGRES_TEST_URL}")
    schema = f"auditoria_{uuid.uuid4().hex[:8]}"
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


@pytest.mark.parametrize(("given", "stored"), [(0, False), (1, True), (False, False), (True, True)])
def test_es_masivo_is_stored_as_a_boolean(Session, given, stored):
    with Session() as db:
        db.add(
            Auditoria(usuario_id=7, tipo_accion=TipoAccion.SELL_OUT_CAMPANA_CREADA, valores_nuevos={}, es_masivo=given)
        )
        db.commit()
    with Session() as db:
        assert db.execute(text("SELECT es_masivo FROM auditoria")).scalar_one() is stored
