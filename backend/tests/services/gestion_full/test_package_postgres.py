"""Postgres coverage for Gestión Full package qty_export (#1977).

Unit tests mock stock; this proves the real Session + productos_erp.stock cap.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.models.auditoria import Auditoria
from app.models.gestion_full_package import (
    GestionFullPackage,
    GestionFullPackageLine,
    GestionFullQtyExportAudit,
)
from app.models.producto import ProductoERP
from app.services.gestion_full.package import set_qty_export
from tests.conftest import (
    POSTGRES_TEST_URL,
    _patch_pg_types_for_sqlite,
    _postgres_reachable,
    _restore_pristine_pg_types,
)

_ORM_TABLES = [
    ProductoERP.__table__,
    GestionFullPackage.__table__,
    GestionFullPackageLine.__table__,
    GestionFullQtyExportAudit.__table__,
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
    schema = f"gf_pkg_{uuid.uuid4().hex[:8]}"
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
class TestPackageQtyExportPostgres:
    def test_set_qty_export_caps_to_server_stock(self, pg_engine: Engine) -> None:
        """#1977: client stock_erp is ignored; qty_export never exceeds productos_erp.stock."""
        db = _session(pg_engine)
        try:
            db.execute(
                text(
                    "INSERT INTO productos_erp (item_id, codigo, descripcion, stock) "
                    "VALUES (101, 'SKU-101', 'Producto test', 3)"
                )
            )
            pkg = GestionFullPackage(week_monday=date(2026, 10, 26), status="open")
            db.add(pkg)
            db.flush()
            line = GestionFullPackageLine(
                package_id=pkg.id,
                producto_item_id=101,
                user_product_id="MLAU1",
                inventory_id="INV-1",
                qty_pm=20,
                qty_export=20,
            )
            db.add(line)
            db.execute(text("INSERT INTO usuarios (id, nombre) VALUES (1, 'gestor')"))
            db.commit()
            db.refresh(line)

            out = set_qty_export(
                db,
                line=line,
                qty_export=99,
                usuario=SimpleNamespace(id=1),
                stock_erp=999,  # client lie — must be ignored
            )
            assert out.qty_export == 3
            audit = db.query(GestionFullQtyExportAudit).one()
            assert audit.old_qty == 20
            assert audit.new_qty == 3
        finally:
            db.close()
