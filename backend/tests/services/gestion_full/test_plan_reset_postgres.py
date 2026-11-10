"""Postgres coverage for Gestión Full plan reset.

Unit tests mock delete/audit; this proves both tables empty, package lines
untouched, and one masivo audit row in the same transaction.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.models.auditoria import Auditoria, TipoAccion
from app.models.gestion_full_override import GestionFullOverride
from app.models.gestion_full_package import GestionFullPackage, GestionFullPackageLine
from app.models.gestion_full_pm_ready import GestionFullPmReady
from app.models.producto import ProductoERP
from app.services.gestion_full.plan_reset import reset_planificacion
from tests.conftest import (
    POSTGRES_TEST_URL,
    _patch_pg_types_for_sqlite,
    _postgres_reachable,
    _restore_pristine_pg_types,
)

_ORM_TABLES = [
    ProductoERP.__table__,
    GestionFullOverride.__table__,
    GestionFullPmReady.__table__,
    GestionFullPackage.__table__,
    GestionFullPackageLine.__table__,
    Auditoria.__table__,
]

_STUB_DDL = (
    """
    CREATE TABLE usuarios (
      id SERIAL PRIMARY KEY,
      nombre TEXT NOT NULL DEFAULT 't'
    )
    """,
)


@pytest.fixture()
def pg_engine(monkeypatch: pytest.MonkeyPatch) -> Iterator[Engine]:
    if not _postgres_reachable():
        pytest.skip(f"PostgreSQL not reachable at {POSTGRES_TEST_URL}")

    _restore_pristine_pg_types(_ORM_TABLES)
    schema = f"gf_plan_reset_{uuid.uuid4().hex[:8]}"
    admin = create_engine(POSTGRES_TEST_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f"CREATE SCHEMA {schema}"))
    engine = create_engine(
        POSTGRES_TEST_URL,
        connect_args={"options": f"-csearch_path={schema}"},
    )
    try:
        with engine.begin() as conn:
            for ddl in _STUB_DDL:
                conn.execute(text(ddl))
            for table in _ORM_TABLES:
                table.create(bind=conn)
        monkeypatch.setattr(
            "app.core.database.SessionLocal",
            sessionmaker(bind=engine, autocommit=False, autoflush=False),
        )
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        admin.dispose()
        _patch_pg_types_for_sqlite()


def _session(engine: Engine) -> Session:
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)()


@pytest.mark.postgres
class TestPlanResetPostgres:
    def test_reset_empties_overrides_and_pm_ready_keeps_package_and_audits(self, pg_engine: Engine) -> None:
        db = _session(pg_engine)
        try:
            db.execute(text("INSERT INTO usuarios (id, nombre) VALUES (7, 'gestor')"))
            db.execute(
                text(
                    "INSERT INTO productos_erp (item_id, codigo, descripcion, stock) "
                    "VALUES (101, 'SKU-101', 'Producto test', 20)"
                )
            )
            db.add(GestionFullOverride(inventory_id="INV-1", cantidad=4, updated_by_id=7))
            db.add(GestionFullOverride(inventory_id="INV-2", cantidad=9, updated_by_id=7))
            db.add(
                GestionFullPmReady(
                    producto_item_id=101,
                    user_product_id="MLAU1",
                    inventory_id="INV-1",
                    qty_pm=4,
                    ready_by_id=7,
                )
            )
            pkg = GestionFullPackage(week_monday=date(2026, 10, 26), status="open")
            db.add(pkg)
            db.flush()
            db.add(
                GestionFullPackageLine(
                    package_id=pkg.id,
                    producto_item_id=101,
                    user_product_id="MLAU1",
                    inventory_id="INV-1",
                    qty_pm=4,
                    qty_export=4,
                )
            )
            db.commit()

            out = reset_planificacion(db, usuario=SimpleNamespace(id=7))

            assert out == {"overrides_deleted": 2, "pm_ready_deleted": 1}
            assert db.query(GestionFullOverride).count() == 0
            assert db.query(GestionFullPmReady).count() == 0
            line = db.query(GestionFullPackageLine).one()
            assert line.inventory_id == "INV-1"
            assert line.qty_pm == 4
            assert line.qty_export == 4

            audit = db.query(Auditoria).one()
            assert audit.tipo_accion == TipoAccion.GESTION_FULL_PLAN_RESET
            assert audit.usuario_id == 7
            assert audit.es_masivo is True
            assert audit.productos_afectados == 3
            assert audit.valores_nuevos == {
                "overrides_deleted": 2,
                "pm_ready_deleted": 1,
            }
        finally:
            db.close()
