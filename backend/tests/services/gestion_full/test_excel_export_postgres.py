"""Postgres coverage for Gestión Full Excel export (#1978).

Pins formula-looking SKU/EAN text cells and the hard stock gate on prepare.
"""

from __future__ import annotations

import io
import uuid
from collections.abc import Iterator
from datetime import date

import pytest
from openpyxl import load_workbook
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.models.gestion_full_package import GestionFullPackage, GestionFullPackageLine
from app.models.gestion_full_unidades_caja import GestionFullUnidadesCaja
from app.models.producto import ProductoERP
from app.services.gestion_full.excel_export import (
    build_ml_full_xlsx,
    build_ops_ean_xlsx,
    prepare_package_for_export,
)
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
    GestionFullUnidadesCaja.__table__,
]

_STUB_DDL = (
    """
    CREATE TABLE usuarios (
      id SERIAL PRIMARY KEY,
      nombre TEXT NOT NULL DEFAULT 't'
    )
    """,
    """
    CREATE TABLE ml_items (
      item_id TEXT PRIMARY KEY,
      inventory_id TEXT,
      user_product_id TEXT,
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
    schema = f"gf_xlsx_{uuid.uuid4().hex[:8]}"
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
        text("INSERT INTO productos_erp (item_id, codigo, descripcion, stock) VALUES (:id, :codigo, :desc, :stock)"),
        {"id": item_id, "codigo": codigo, "desc": descripcion, "stock": stock},
    )


def _seed_ml_item(
    db: Session,
    *,
    item_id: str = "MLA999",
    inventory_id: str | None = "INV-1",
    user_product_id: str = "MLAU1",
    seller_sku: str = "SKU-101",
) -> None:
    db.execute(
        text(
            "INSERT INTO ml_items (item_id, inventory_id, user_product_id, seller_sku, "
            "never_existed, gone_at) VALUES (:item_id, :inv, :mlau, :sku, FALSE, NULL)"
        ),
        {
            "item_id": item_id,
            "inv": inventory_id,
            "mlau": user_product_id,
            "sku": seller_sku,
        },
    )


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

    def test_ml_full_xlsx_synthetic_line_fills_live_codigo_when_available(self, pg_engine: Engine) -> None:
        """NOINV package key still exports live Código ML if Melí assigned it later."""
        db = _session(pg_engine)
        try:
            _seed_product(db, codigo="EAN-NOINV")
            _seed_ml_item(
                db,
                item_id="MLA1914044247",
                inventory_id="XYZ-NEW",
                user_product_id="MLAU4380845993",
                seller_sku="EAN-NOINV",
            )
            db.add(GestionFullUnidadesCaja(producto_item_id=101, unidades=1))
            pkg = GestionFullPackage(week_monday=date(2026, 10, 26), status="open")
            db.add(pkg)
            db.flush()
            db.add(
                GestionFullPackageLine(
                    package_id=pkg.id,
                    producto_item_id=101,
                    user_product_id="MLAU4380845993",
                    inventory_id="NOINV:MLAU4380845993",
                    qty_pm=2,
                    qty_export=2,
                )
            )
            db.commit()
            db.refresh(pkg)

            raw = build_ml_full_xlsx(db, pkg)
            wb = load_workbook(io.BytesIO(raw))
            ws = wb[" Selección de productos"]
            assert ws.cell(6, 1).value == "EAN-NOINV"
            assert ws.cell(6, 3).value == "XYZ-NEW"
            assert ws.cell(6, 4).value == "1914044247"
            assert ws.cell(6, 6).value == "2"
        finally:
            db.close()

    def test_ml_full_xlsx_synthetic_line_leaves_codigo_blank_when_still_missing(self, pg_engine: Engine) -> None:
        db = _session(pg_engine)
        try:
            _seed_product(db, codigo="EAN-NOINV")
            _seed_ml_item(
                db,
                item_id="MLA1914044247",
                inventory_id=None,
                user_product_id="MLAU4380845993",
                seller_sku="EAN-NOINV",
            )
            db.add(GestionFullUnidadesCaja(producto_item_id=101, unidades=1))
            pkg = GestionFullPackage(week_monday=date(2026, 10, 26), status="open")
            db.add(pkg)
            db.flush()
            db.add(
                GestionFullPackageLine(
                    package_id=pkg.id,
                    producto_item_id=101,
                    user_product_id="MLAU4380845993",
                    inventory_id="NOINV:MLAU4380845993",
                    qty_pm=2,
                    qty_export=2,
                )
            )
            db.commit()
            db.refresh(pkg)

            raw = build_ml_full_xlsx(db, pkg)
            wb = load_workbook(io.BytesIO(raw))
            ws = wb[" Selección de productos"]
            assert ws.cell(6, 1).value == "EAN-NOINV"
            # openpyxl may round-trip an empty string cell as None.
            assert (ws.cell(6, 3).value or "") == ""
            assert ws.cell(6, 4).value == "1914044247"
        finally:
            db.close()


@pytest.mark.postgres
class TestExcelStockGate:
    def test_first_export_excel_uses_stock_cap(self, pg_engine: Engine) -> None:
        """Export prepare refuses when stock < qty_export (gestor must fix package)."""
        db = _session(pg_engine)
        try:
            _seed_product(db, stock=3)
            _seed_ml_item(db)
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
                    qty_pm=20,
                    qty_export=20,
                )
            )
            db.commit()
            db.refresh(pkg)

            with pytest.raises(ValueError, match="stock ERP insuficiente"):
                prepare_package_for_export(db, pkg)

            db.rollback()
            db.refresh(pkg)
            pkg.lines[0].qty_export = 3
            db.commit()
            db.refresh(pkg)
            pkg = prepare_package_for_export(db, pkg)
            raw = build_ml_full_xlsx(db, pkg)
            wb = load_workbook(io.BytesIO(raw))
            ws = wb[" Selección de productos"]
            assert ws.cell(6, 6).value == "3"
        finally:
            db.close()
