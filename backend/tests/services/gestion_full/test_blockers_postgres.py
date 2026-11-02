"""Postgres integration coverage for Fernando's three Gestión Full blockers.

Unit tests mock around these paths; these prove the real session lifecycle:
session close before reconcile (#1982), hard-lock deletes pm_ready (#1979/#1980),
and Excel cells stay strings under formula-looking SKUs/EANs (#1978).
"""

from __future__ import annotations

import io
import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from openpyxl import load_workbook
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.models.gestion_full_envio import GestionFullEnvio, GestionFullInboundReceptionOp
from app.models.gestion_full_package import (
    PACKAGE_STATUS_EXPORTED,
    PACKAGE_STATUS_LOCKED,
    GestionFullPackage,
    GestionFullPackageLine,
)
from app.models.gestion_full_pm_ready import GestionFullPmReady
from app.models.gestion_full_unidades_caja import GestionFullUnidadesCaja
from app.services.gestion_full.assign_inbound import assign_inbound_to_lines, maybe_hard_lock
from app.services.gestion_full.excel_export import build_ml_full_xlsx, build_ops_ean_xlsx
from app.workers.context import WorkerContext
from app.workers.handlers.gestion_full_reconcile import GestionFullReconcileHandler
from tests.conftest import (
    POSTGRES_TEST_URL,
    _patch_pg_types_for_sqlite,
    _postgres_reachable,
    _restore_pristine_pg_types,
)

_ORM_TABLES = [
    GestionFullPackage.__table__,
    GestionFullPackageLine.__table__,
    GestionFullPmReady.__table__,
    GestionFullUnidadesCaja.__table__,
    GestionFullEnvio.__table__,
    GestionFullInboundReceptionOp.__table__,
]

_STUB_DDL = (
    """
    CREATE TABLE usuarios (
      id SERIAL PRIMARY KEY,
      nombre TEXT NOT NULL DEFAULT 't'
    )
    """,
    """
    CREATE TABLE productos_erp (
      item_id INTEGER PRIMARY KEY,
      codigo TEXT,
      descripcion TEXT,
      stock INTEGER DEFAULT 0
    )
    """,
    """
    CREATE TABLE ml_items (
      item_id TEXT PRIMARY KEY,
      inventory_id TEXT,
      seller_sku TEXT,
      never_existed BOOLEAN DEFAULT FALSE,
      gone_at TIMESTAMPTZ
    )
    """,
)


@pytest.fixture()
def pg_engine(monkeypatch: pytest.MonkeyPatch) -> Iterator[Engine]:
    if not _postgres_reachable():
        pytest.skip(f"PostgreSQL not reachable at {POSTGRES_TEST_URL}")

    _restore_pristine_pg_types(_ORM_TABLES)
    schema = f"gf_blockers_{uuid.uuid4().hex[:8]}"
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
        # get_background_db() always uses SessionLocal / DATABASE_URL — point it here.
        monkeypatch.setattr("app.core.database.SessionLocal", sessionmaker(bind=engine))
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        admin.dispose()
        _patch_pg_types_for_sqlite()


def _session(engine: Engine) -> Session:
    return sessionmaker(bind=engine)()


def _seed_product(
    db: Session,
    *,
    item_id: int = 101,
    codigo: str = "SKU-101",
    descripcion: str = "Producto test",
    stock: int = 50,
) -> None:
    db.execute(
        text("INSERT INTO productos_erp (item_id, codigo, descripcion, stock) VALUES (:id, :codigo, :desc, :stock)"),
        {"id": item_id, "codigo": codigo, "desc": descripcion, "stock": stock},
    )


def _seed_ml_item(
    db: Session,
    *,
    item_id: str = "MLA999",
    inventory_id: str = "INV-1",
    seller_sku: str = "SKU-101",
) -> None:
    db.execute(
        text(
            "INSERT INTO ml_items (item_id, inventory_id, seller_sku, never_existed, gone_at) "
            "VALUES (:item_id, :inv, :sku, FALSE, NULL)"
        ),
        {"item_id": item_id, "inv": inventory_id, "sku": seller_sku},
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
class TestReconcileHandlerDetachedIds:
    def test_handler_run_survives_listing_session_close(
        self, pg_engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """#1982: listing session commits/closes; reconcile must use inbound_id strings."""
        db = _session(pg_engine)
        try:
            _seed_product(db)
            pkg = _seed_exported_package(db, inbound_id="INB-LIVE-1")
            db.add(
                GestionFullEnvio(
                    inbound_id="INB-LIVE-1",
                    package_id=pkg.id,
                    week_monday=pkg.week_monday,
                )
            )
            db.commit()
        finally:
            db.close()

        reception = {
            "id": 4242,
            "type": "INBOUND_RECEPTION",
            "date_created": "2026-10-30T12:00:00Z",
            "detail": {"available_quantity": 2},
            "external_references": [{"type": "inbound_id", "value": "INB-LIVE-1"}],
        }
        client = MagicMock()
        client.get.return_value = SimpleNamespace(status=200, body={"results": [reception]})
        monkeypatch.setattr("app.core.config.settings.ML_USER_ID", "1")

        handler = GestionFullReconcileHandler(
            client_factory=lambda _p: client,
            now=lambda: datetime(2026, 10, 31, tzinfo=UTC),
        )
        result = handler.run(
            WorkerContext(
                deadline=datetime.now(UTC) + timedelta(seconds=30),
                worker_name="test",
            )
        )

        assert result.success is True
        assert result.detail["reconciled"] == 1
        assert result.detail["results"][0].get("error") is not True
        assert result.detail["results"][0]["inserted"] == 1

        verify = _session(pg_engine)
        try:
            op = verify.query(GestionFullInboundReceptionOp).filter_by(operation_id=4242).one()
            assert op.inbound_id == "INB-LIVE-1"
            assert op.cantidad == 2
            envio = verify.get(GestionFullEnvio, "INB-LIVE-1")
            assert envio is not None
            assert envio.last_reception_at is not None
            assert envio.reception_closed_at is None
        finally:
            verify.close()


@pytest.mark.postgres
class TestHardLockConsumesPmReady:
    def test_maybe_hard_lock_deletes_pm_ready_rows(self, pg_engine: Engine) -> None:
        """#1979/#1980: locking the package must consume pm_ready for its lines."""
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

    def test_assign_inbound_hard_lock_consumes_pm_ready(
        self, pg_engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
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

            monkeypatch.setattr(
                "app.services.gestion_full.reconcile.ensure_envio",
                lambda *_a, **_k: None,
            )
            assign_inbound_to_lines(db, pkg, line_ids=[line_id], inbound_id="INB-ASSIGN")
            db.refresh(pkg)

            assert pkg.status == PACKAGE_STATUS_LOCKED
            assert pkg.lines[0].inbound_id == "INB-ASSIGN"
            assert db.get(GestionFullPmReady, (101, "MLAU1")) is None
        finally:
            db.close()


@pytest.mark.postgres
class TestExcelStringCells:
    def test_ops_ean_sheet_keeps_formula_looking_text_as_string(self, pg_engine: Engine) -> None:
        """#1978: ERP codigo/descripcion starting with '=' must not become formulas."""
        dangerous_ean = '=HYPERLINK("http://evil.example","x")'
        dangerous_desc = "=1+1"
        db = _session(pg_engine)
        try:
            _seed_product(db, codigo=dangerous_ean, descripcion=dangerous_desc)
            db.add(GestionFullUnidadesCaja(producto_item_id=101, unidades=1))
            pkg = GestionFullPackage(week_monday=date(2026, 10, 26), status="open")
            db.add(pkg)
            db.flush()
            db.add(
                GestionFullPackageLine(
                    package_id=pkg.id,
                    producto_item_id=101,
                    user_product_id="MLAU1",
                    inventory_id="INV-1",
                    qty_pm=2,
                    qty_export=2,
                )
            )
            db.commit()
            db.refresh(pkg)

            raw = build_ops_ean_xlsx(db, pkg)
            wb = load_workbook(io.BytesIO(raw))
            ws = wb.active
            ean_cell = ws.cell(2, 1)
            desc_cell = ws.cell(2, 2)
            assert ean_cell.value == dangerous_ean
            assert ean_cell.data_type == "s"
            assert desc_cell.value == dangerous_desc
            assert desc_cell.data_type == "s"
        finally:
            db.close()

    def test_ml_full_xlsx_keeps_formula_looking_seller_sku_as_string(self, pg_engine: Engine) -> None:
        """#1978: seller_sku from ml_items must stay a string cell in the ML template."""
        dangerous_sku = '=HYPERLINK("http://evil.example","sku")'
        db = _session(pg_engine)
        try:
            _seed_product(db, codigo="SAFE-EAN")
            _seed_ml_item(db, seller_sku=dangerous_sku)
            db.add(GestionFullUnidadesCaja(producto_item_id=101, unidades=1))
            pkg = GestionFullPackage(week_monday=date(2026, 10, 26), status="open")
            db.add(pkg)
            db.flush()
            db.add(
                GestionFullPackageLine(
                    package_id=pkg.id,
                    producto_item_id=101,
                    user_product_id="MLAU1",
                    inventory_id="INV-1",
                    qty_pm=2,
                    qty_export=2,
                )
            )
            db.commit()
            db.refresh(pkg)

            raw = build_ml_full_xlsx(db, pkg)
            wb = load_workbook(io.BytesIO(raw))
            ws = wb[" Selección de productos"]
            sku_cell = ws.cell(6, 1)
            inv_cell = ws.cell(6, 3)
            assert sku_cell.value == dangerous_sku
            assert sku_cell.data_type == "s"
            assert inv_cell.value == "INV-1"
            assert inv_cell.data_type == "s"
        finally:
            db.close()
