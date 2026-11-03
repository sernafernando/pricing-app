"""Two-session Postgres pin for ``populate_existing`` on set_qty_export (#1979).

Mock chains only prove the call exists; this proves a concurrent commit is visible
as ``old_qty`` in the audit row when session A still holds a stale identity-map line.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

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
    schema = f"gf_pop_{uuid.uuid4().hex[:8]}"
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
class TestPopulateExistingTwoSessions:
    def test_set_qty_export_sees_concurrent_commit_as_old_qty(self, pg_engine: Engine) -> None:
        """Session B commits qty=2; A's set_qty must audit old_qty=2 (not stale 5)."""
        seed = _session(pg_engine)
        try:
            seed.execute(
                text(
                    "INSERT INTO productos_erp (item_id, codigo, descripcion, stock) "
                    "VALUES (101, 'SKU-101', 'Producto test', 50)"
                )
            )
            pkg = GestionFullPackage(week_monday=date(2026, 10, 26), status="open")
            seed.add(pkg)
            seed.flush()
            line = GestionFullPackageLine(
                package_id=pkg.id,
                producto_item_id=101,
                user_product_id="MLAU1",
                inventory_id="INV-1",
                qty_pm=10,
                qty_export=5,
            )
            seed.add(line)
            seed.execute(text("INSERT INTO usuarios (id, nombre) VALUES (1, 'gestor')"))
            seed.commit()
            line_id = line.id
        finally:
            seed.close()

        db_a = _session(pg_engine)
        db_b = _session(pg_engine)
        try:
            # A loads the line into its identity map at qty_export=5.
            line_a = db_a.get(GestionFullPackageLine, line_id)
            assert line_a is not None
            assert line_a.qty_export == 5

            # Concurrent B writes qty_export=2 and commits.
            line_b = db_b.get(GestionFullPackageLine, line_id)
            assert line_b is not None
            line_b.qty_export = 2
            db_b.commit()

            # Stale identity map still says 5 until populate_existing reloads under lock.
            assert line_a.qty_export == 5

            set_qty_export(
                db_a,
                line=line_a,
                qty_export=4,
                usuario=SimpleNamespace(id=1),
            )

            audit = (
                db_a.query(GestionFullQtyExportAudit)
                .filter_by(package_line_id=line_id)
                .order_by(GestionFullQtyExportAudit.id.desc())
                .one()
            )
            assert audit.old_qty == 2, (
                "populate_existing missing: audit would keep stale identity-map old_qty=5"
            )
            assert audit.new_qty == 4
        finally:
            db_a.close()
            db_b.close()
