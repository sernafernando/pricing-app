"""Postgres coverage for Gestión Full assign / hard-lock / Sumar (#1979).

Unit tests mock the session; these prove real FOR UPDATE + pm_ready deletes.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.models.gestion_full_package import (
    PACKAGE_STATUS_EXPORTED,
    PACKAGE_STATUS_LOCKED,
    GestionFullPackage,
    GestionFullPackageLine,
    GestionFullQtyExportAudit,
)
from app.models.gestion_full_pm_ready import GestionFullPmReady
from app.models.producto import ProductoERP
from app.services.gestion_full.assign_inbound import assign_inbound_to_lines, maybe_hard_lock
from app.services.gestion_full.package import add_all_ready_lines_to_package, set_qty_export
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
    GestionFullPmReady.__table__,
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
    schema = f"gf_assign_{uuid.uuid4().hex[:8]}"
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


def _seed_product(
    db: Session,
    *,
    item_id: int = 101,
    codigo: str = "SKU-101",
    descripcion: str = "Producto test",
    stock: int = 50,
) -> None:
    db.execute(
        text(
            "INSERT INTO productos_erp (item_id, codigo, descripcion, stock) "
            "VALUES (:id, :codigo, :desc, :stock)"
        ),
        {"id": item_id, "codigo": codigo, "desc": descripcion, "stock": stock},
    )


def _seed_exported_package(
    db: Session,
    *,
    item_id: int = 101,
    user_product_id: str = "MLAU1",
    inventory_id: str = "INV-1",
    qty_export: int = 5,
    inbound_id: str | None = None,
) -> GestionFullPackage:
    pkg = GestionFullPackage(
        week_monday=date(2026, 10, 26),
        status=PACKAGE_STATUS_EXPORTED,
        exported_at=datetime(2026, 10, 27, tzinfo=UTC),
    )
    db.add(pkg)
    db.flush()
    db.add(
        GestionFullPackageLine(
            package_id=pkg.id,
            producto_item_id=item_id,
            user_product_id=user_product_id,
            inventory_id=inventory_id,
            qty_pm=qty_export,
            qty_export=qty_export,
            inbound_id=inbound_id,
        )
    )
    db.flush()
    db.refresh(pkg)
    return pkg


@pytest.mark.postgres
class TestHardLockConsumesPmReady:
    def test_maybe_hard_lock_deletes_pm_ready_rows(self, pg_engine: Engine) -> None:
        """#1979: locking the package must consume pm_ready for its lines."""
        db = _session(pg_engine)
        try:
            _seed_product(db)
            pkg = _seed_exported_package(db, inbound_id="INB-LOCK")
            db.add(
                GestionFullPmReady(
                    producto_item_id=101,
                    user_product_id="MLAU1",
                    inventory_id="INV-1",
                    qty_pm=5,
                )
            )
            db.commit()
            db.refresh(pkg)

            assert db.get(GestionFullPmReady, (101, "MLAU1")) is not None
            out = maybe_hard_lock(db, pkg)
            assert out is not None
            assert out.status == PACKAGE_STATUS_LOCKED
            assert db.get(GestionFullPmReady, (101, "MLAU1")) is None
        finally:
            db.close()

    def test_assign_inbound_hard_lock_consumes_pm_ready(self, pg_engine: Engine) -> None:
        db = _session(pg_engine)
        try:
            _seed_product(db)
            pkg = _seed_exported_package(db, inbound_id=None)
            line_id = pkg.lines[0].id
            db.add(
                GestionFullPmReady(
                    producto_item_id=101,
                    user_product_id="MLAU1",
                    inventory_id="INV-1",
                    qty_pm=5,
                )
            )
            db.commit()
            db.refresh(pkg)

            # Before #1981 reconcile is missing — assign already no-ops ensure_envio.
            assign_inbound_to_lines(db, pkg, line_ids=[line_id], inbound_id="INB-ASSIGN")
            db.refresh(pkg)

            assert pkg.status == PACKAGE_STATUS_LOCKED
            assert pkg.lines[0].inbound_id == "INB-ASSIGN"
            assert db.get(GestionFullPmReady, (101, "MLAU1")) is None
        finally:
            db.close()


@pytest.mark.postgres
class TestSetQtyHardLock:
    def test_set_qty_export_zero_triggers_hard_lock(self, pg_engine: Engine) -> None:
        """Zeroing the last unassigned shippable line hard-locks."""
        db = _session(pg_engine)
        try:
            _seed_product(db, item_id=101, stock=50)
            _seed_product(db, item_id=102, codigo="SKU-102", stock=50)
            pkg = GestionFullPackage(
                week_monday=date(2026, 10, 26),
                status=PACKAGE_STATUS_EXPORTED,
                exported_at=datetime(2026, 10, 27, tzinfo=UTC),
            )
            db.add(pkg)
            db.flush()
            ln1 = GestionFullPackageLine(
                package_id=pkg.id,
                producto_item_id=101,
                user_product_id="MLAU1",
                inventory_id="INV-1",
                qty_pm=5,
                qty_export=5,
                inbound_id="INB-1",
            )
            ln2 = GestionFullPackageLine(
                package_id=pkg.id,
                producto_item_id=102,
                user_product_id="MLAU2",
                inventory_id="INV-2",
                qty_pm=5,
                qty_export=5,
                inbound_id=None,
            )
            db.add_all([ln1, ln2])
            db.add(
                GestionFullPmReady(
                    producto_item_id=101,
                    user_product_id="MLAU1",
                    inventory_id="INV-1",
                    qty_pm=5,
                )
            )
            db.add(
                GestionFullPmReady(
                    producto_item_id=102,
                    user_product_id="MLAU2",
                    inventory_id="INV-2",
                    qty_pm=5,
                )
            )
            db.execute(text("INSERT INTO usuarios (id, nombre) VALUES (9, 'gestor')"))
            db.commit()
            db.refresh(pkg)
            db.refresh(ln2)

            set_qty_export(
                db,
                line=ln2,
                qty_export=0,
                usuario=SimpleNamespace(id=9),
            )
            db.refresh(pkg)
            assert pkg.status == PACKAGE_STATUS_LOCKED
            assert db.get(GestionFullPmReady, (101, "MLAU1")) is None
            assert db.get(GestionFullPmReady, (102, "MLAU2")) is None
        finally:
            db.close()


@pytest.mark.postgres
class TestSumarPostgres:
    def test_sumar_listo_does_not_undo_stock_cap(self, pg_engine: Engine) -> None:
        """From-ready keeps auto qty_export at min(qty_pm, stock) after export."""
        db = _session(pg_engine)
        try:
            _seed_product(db, stock=3)
            pkg = GestionFullPackage(
                week_monday=date(2026, 10, 26),
                status=PACKAGE_STATUS_EXPORTED,
                exported_at=datetime(2026, 10, 27, tzinfo=UTC),
            )
            db.add(pkg)
            db.flush()
            db.add(
                GestionFullPackageLine(
                    package_id=pkg.id,
                    producto_item_id=101,
                    user_product_id="MLAU1",
                    inventory_id="INV-1",
                    qty_pm=20,
                    qty_export=3,
                )
            )
            db.add(
                GestionFullPmReady(
                    producto_item_id=101,
                    user_product_id="MLAU1",
                    inventory_id="INV-1",
                    qty_pm=20,
                )
            )
            db.execute(text("INSERT INTO usuarios (id, nombre) VALUES (1, 'gestor')"))
            db.commit()
            db.refresh(pkg)

            out_pkg, touched = add_all_ready_lines_to_package(
                db, usuario=SimpleNamespace(id=1)
            )
            assert touched == 1
            assert out_pkg.lines[0].qty_export == 3
        finally:
            db.close()

    def test_sumar_stock_zero_hard_locks(self, pg_engine: Engine) -> None:
        """Sumar capping last unassigned line to 0 must hard-lock."""
        db = _session(pg_engine)
        try:
            _seed_product(db, item_id=101, stock=50)
            _seed_product(db, item_id=102, codigo="SKU-102", stock=0)
            pkg = GestionFullPackage(
                week_monday=date(2026, 10, 26),
                status=PACKAGE_STATUS_EXPORTED,
                exported_at=datetime(2026, 10, 27, tzinfo=UTC),
            )
            db.add(pkg)
            db.flush()
            db.add(
                GestionFullPackageLine(
                    package_id=pkg.id,
                    producto_item_id=101,
                    user_product_id="MLAU1",
                    inventory_id="INV-1",
                    qty_pm=5,
                    qty_export=5,
                    inbound_id="INB-1",
                )
            )
            db.add(
                GestionFullPackageLine(
                    package_id=pkg.id,
                    producto_item_id=102,
                    user_product_id="MLAU2",
                    inventory_id="INV-2",
                    qty_pm=5,
                    qty_export=5,
                    inbound_id=None,
                )
            )
            db.add(
                GestionFullPmReady(
                    producto_item_id=101,
                    user_product_id="MLAU1",
                    inventory_id="INV-1",
                    qty_pm=5,
                )
            )
            db.add(
                GestionFullPmReady(
                    producto_item_id=102,
                    user_product_id="MLAU2",
                    inventory_id="INV-2",
                    qty_pm=5,
                )
            )
            db.execute(text("INSERT INTO usuarios (id, nombre) VALUES (3, 'gestor')"))
            db.commit()
            db.refresh(pkg)

            add_all_ready_lines_to_package(db, usuario=SimpleNamespace(id=3))
            db.refresh(pkg)
            assert pkg.status == PACKAGE_STATUS_LOCKED
            assert db.get(GestionFullPmReady, (101, "MLAU1")) is None
        finally:
            db.close()

    def test_sumar_exported_does_not_raise_above_excel(self, pg_engine: Engine) -> None:
        """Stock rise after export must not bump qty_export via Sumar."""
        db = _session(pg_engine)
        try:
            _seed_product(db, stock=10)
            pkg = GestionFullPackage(
                week_monday=date(2026, 10, 26),
                status=PACKAGE_STATUS_EXPORTED,
                exported_at=datetime(2026, 10, 27, tzinfo=UTC),
            )
            db.add(pkg)
            db.flush()
            db.add(
                GestionFullPackageLine(
                    package_id=pkg.id,
                    producto_item_id=101,
                    user_product_id="MLAU1",
                    inventory_id="INV-1",
                    qty_pm=20,
                    qty_export=3,
                )
            )
            db.add(
                GestionFullPmReady(
                    producto_item_id=101,
                    user_product_id="MLAU1",
                    inventory_id="INV-1",
                    qty_pm=20,
                )
            )
            db.execute(text("INSERT INTO usuarios (id, nombre) VALUES (4, 'gestor')"))
            db.commit()
            db.refresh(pkg)

            out_pkg, _ = add_all_ready_lines_to_package(db, usuario=SimpleNamespace(id=4))
            assert out_pkg.lines[0].qty_export == 3
        finally:
            db.close()

    def test_sumar_exported_skips_new_listo_lines(self, pg_engine: Engine) -> None:
        """After Excel download, new PM Listo waits for the next shipment."""
        db = _session(pg_engine)
        try:
            _seed_product(db, item_id=101, stock=50)
            _seed_product(db, item_id=102, codigo="SKU-102", stock=6)
            _seed_product(db, item_id=103, codigo="SKU-103", stock=8)
            pkg = GestionFullPackage(
                week_monday=date(2026, 10, 26),
                status=PACKAGE_STATUS_EXPORTED,
                exported_at=datetime(2026, 10, 27, tzinfo=UTC),
            )
            db.add(pkg)
            db.flush()
            db.add(
                GestionFullPackageLine(
                    package_id=pkg.id,
                    producto_item_id=101,
                    user_product_id="MLAU1",
                    inventory_id="INV-1",
                    qty_pm=5,
                    qty_export=5,
                    inbound_id="INB-1",
                )
            )
            db.add(
                GestionFullPackageLine(
                    package_id=pkg.id,
                    producto_item_id=102,
                    user_product_id="MLAU2",
                    inventory_id="INV-2",
                    qty_pm=4,
                    qty_export=4,
                    inbound_id=None,
                )
            )
            db.add(
                GestionFullPmReady(
                    producto_item_id=101,
                    user_product_id="MLAU1",
                    inventory_id="INV-1",
                    qty_pm=5,
                )
            )
            db.add(
                GestionFullPmReady(
                    producto_item_id=102,
                    user_product_id="MLAU2",
                    inventory_id="INV-2",
                    qty_pm=4,
                )
            )
            db.add(
                GestionFullPmReady(
                    producto_item_id=103,
                    user_product_id="MLAU3",
                    inventory_id="INV-3",
                    qty_pm=8,
                )
            )
            db.execute(text("INSERT INTO usuarios (id, nombre) VALUES (5, 'gestor')"))
            db.commit()
            db.refresh(pkg)

            out_pkg, touched = add_all_ready_lines_to_package(
                db, usuario=SimpleNamespace(id=5)
            )
            db.refresh(out_pkg)
            assert touched == 2
            assert len(out_pkg.lines) == 2
            assert out_pkg.status == PACKAGE_STATUS_EXPORTED
            assert db.get(GestionFullPmReady, (103, "MLAU3")) is not None
        finally:
            db.close()
