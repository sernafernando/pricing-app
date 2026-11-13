"""Postgres coverage for Gestión Full product filters (marcas/categorias + facets).

Unit tests mock `db.execute` / `product_facet_options`; this runs the real SQL
(`upper(p.marca) = ANY(...)`, cross-filtered facets).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.models.marca_visible_excepcion import MarcaVisibleExcepcion
from app.models.gestion_full_override import GestionFullOverride
from app.models.gestion_full_pm_ready import GestionFullPmReady
from app.models.gestion_full_unidades_caja import GestionFullUnidadesCaja
from app.models.producto import ProductoERP
from app.services.gestion_full.listing import list_gestion_full
from app.services.gestion_full.overrides import clear_override
from tests.conftest import (
    POSTGRES_TEST_URL,
    _patch_pg_types_for_sqlite,
    _postgres_reachable,
    _restore_pristine_pg_types,
)

_ORM_TABLES = [
    ProductoERP.__table__,
    GestionFullOverride.__table__,
    GestionFullUnidadesCaja.__table__,
    GestionFullPmReady.__table__,
    MarcaVisibleExcepcion.__table__,
]

_STUB_DDL = (
    """
    CREATE TABLE usuarios (
      id SERIAL PRIMARY KEY,
      nombre TEXT NOT NULL DEFAULT 't'
    )
    """,
    """
    CREATE TABLE marcas_pm (
      id SERIAL PRIMARY KEY,
      marca TEXT NOT NULL,
      categoria TEXT NOT NULL,
      usuario_id INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE ml_items (
      item_id TEXT PRIMARY KEY,
      inventory_id TEXT,
      user_product_id TEXT,
      family_id BIGINT,
      official_store_id INTEGER,
      never_existed BOOLEAN DEFAULT FALSE,
      gone_at TIMESTAMPTZ
    )
    """,
    """
    CREATE TABLE ml_item_product_links (
      item_id TEXT NOT NULL,
      variation_id INTEGER NOT NULL DEFAULT 0,
      producto_item_id INTEGER,
      PRIMARY KEY (item_id, variation_id)
    )
    """,
    """
    CREATE TABLE ml_user_product_stock (
      user_product_id TEXT PRIMARY KEY,
      full_quantity INTEGER DEFAULT 0
    )
    """,
    """
    CREATE TABLE ml_user_product_replenishment (
      user_product_id TEXT PRIMARY KEY,
      units_7d INTEGER DEFAULT 0,
      units_14d INTEGER DEFAULT 0,
      units_21d INTEGER DEFAULT 0,
      units_30d INTEGER DEFAULT 0
    )
    """,
    """
    CREATE TABLE ml_sale_lines (
      order_id BIGINT NOT NULL,
      product INTEGER,
      qty INTEGER DEFAULT 0,
      day DATE
    )
    """,
    """
    CREATE TABLE ml_orders_ops (
      order_id BIGINT PRIMARY KEY,
      shipping_id BIGINT
    )
    """,
    """
    CREATE TABLE ml_shipments_ops (
      shipment_id BIGINT PRIMARY KEY,
      logistic_type TEXT
    )
    """,
    """
    CREATE TABLE ml_fulfillment_last_inbound (
      inventory_id TEXT PRIMARY KEY,
      cantidad INTEGER
    )
    """,
)


@pytest.fixture()
def pg_engine(monkeypatch: pytest.MonkeyPatch) -> Iterator[Engine]:
    if not _postgres_reachable():
        pytest.skip(f"PostgreSQL not reachable at {POSTGRES_TEST_URL}")

    _restore_pristine_pg_types(_ORM_TABLES)
    schema = f"gf_list_filt_{uuid.uuid4().hex[:8]}"
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


def _seed_linked_row(
    db: Session,
    *,
    producto_item_id: int,
    ean: str,
    marca: str,
    categoria: str,
    mla: str,
    inventory_id: str | None,
    user_product_id: str,
    stock: int = 10,
    full_quantity: int = 5,
    family_id: int | None = None,
) -> None:
    db.execute(
        text(
            "INSERT INTO productos_erp (item_id, codigo, descripcion, marca, categoria, stock) "
            "VALUES (:id, :ean, :desc, :marca, :cat, :stock)"
        ),
        {
            "id": producto_item_id,
            "ean": ean,
            "desc": f"{marca} {categoria}",
            "marca": marca,
            "cat": categoria,
            "stock": stock,
        },
    )
    db.execute(
        text(
            "INSERT INTO ml_items (item_id, inventory_id, user_product_id, family_id, never_existed, gone_at) "
            "VALUES (:mla, :inv, :mlau, :fid, FALSE, NULL)"
        ),
        {"mla": mla, "inv": inventory_id, "mlau": user_product_id, "fid": family_id},
    )
    db.execute(
        text("INSERT INTO ml_item_product_links (item_id, variation_id, producto_item_id) VALUES (:mla, 0, :pid)"),
        {"mla": mla, "pid": producto_item_id},
    )
    db.execute(
        text("INSERT INTO ml_user_product_stock (user_product_id, full_quantity) VALUES (:mlau, :fq)"),
        {"mlau": user_product_id, "fq": full_quantity},
    )
    db.execute(
        text(
            "INSERT INTO ml_user_product_replenishment "
            "(user_product_id, units_7d, units_14d, units_21d, units_30d) "
            "VALUES (:mlau, 0, 0, 0, 0)"
        ),
        {"mlau": user_product_id},
    )


@pytest.mark.postgres
class TestGestionFullListingFiltersPostgres:
    def test_marcas_any_case_insensitive_and_and_with_categorias(self, pg_engine: Engine) -> None:
        db = _session(pg_engine)
        try:
            _seed_linked_row(
                db,
                producto_item_id=1,
                ean="EAN-1",
                marca="TP-LINK",
                categoria="Camaras",
                mla="MLA1",
                inventory_id="INV1",
                user_product_id="MLAU1",
            )
            _seed_linked_row(
                db,
                producto_item_id=2,
                ean="EAN-2",
                marca="tp-link",
                categoria="Redes",
                mla="MLA2",
                inventory_id="INV2",
                user_product_id="MLAU2",
            )
            _seed_linked_row(
                db,
                producto_item_id=3,
                ean="EAN-3",
                marca="EPSON",
                categoria="Camaras",
                mla="MLA3",
                inventory_id="INV3",
                user_product_id="MLAU3",
            )
            db.commit()

            by_marca = list_gestion_full(db, marcas=["tp-link"], full_mode="en", include_zero_stock=False)
            assert sorted(r["inventory_id"] for r in by_marca["items"]) == ["INV1", "INV2"]

            combined = list_gestion_full(
                db,
                marcas=["TP-LINK"],
                categorias=["Camaras"],
                full_mode="en",
            )
            assert [r["inventory_id"] for r in combined["items"]] == ["INV1"]
        finally:
            db.close()

    def test_facets_skip_own_selection(self, pg_engine: Engine) -> None:
        db = _session(pg_engine)
        try:
            _seed_linked_row(
                db,
                producto_item_id=1,
                ean="EAN-1",
                marca="TP-LINK",
                categoria="Camaras",
                mla="MLA1",
                inventory_id="INV1",
                user_product_id="MLAU1",
            )
            _seed_linked_row(
                db,
                producto_item_id=2,
                ean="EAN-2",
                marca="TP-LINK",
                categoria="Redes",
                mla="MLA2",
                inventory_id="INV2",
                user_product_id="MLAU2",
            )
            _seed_linked_row(
                db,
                producto_item_id=3,
                ean="EAN-3",
                marca="EPSON",
                categoria="Camaras",
                mla="MLA3",
                inventory_id="INV3",
                user_product_id="MLAU3",
            )
            db.commit()

            payload = list_gestion_full(db, marcas=["TP-LINK"], full_mode="en")
            facets = payload["facets"]["product"]
            # Categorías narrow to the selected marca.
            assert sorted(facets["categorias"]) == ["Camaras", "Redes"]
            # Marcas list ignores its own selection so EPSON stays available to untick/switch.
            assert "EPSON" in facets["marcas"]
            assert any(m.upper() == "TP-LINK" for m in facets["marcas"])
        finally:
            db.close()

    def test_a_brand_without_stock_is_not_offered_but_its_rows_stay(self, pg_engine: Engine) -> None:
        """marcas-sin-stock S2/S3: the Marca list drops a brand with no product in stock (its rows still list,
        with "include zero stock"); a selected one stays offered; an admin exception brings it back."""
        db = _session(pg_engine)
        try:
            for n, (marca, stock) in enumerate((("EPSON", 10), ("AGOTADA", 0)), start=1):
                _seed_linked_row(
                    db,
                    producto_item_id=n,
                    ean=f"EAN-{n}",
                    marca=marca,
                    categoria="Camaras",
                    mla=f"MLA{n}",
                    inventory_id=f"INV{n}",
                    user_product_id=f"MLAU{n}",
                    stock=stock,
                )
            db.commit()

            payload = list_gestion_full(db, full_mode="en", include_zero_stock=True)
            assert {item["marca"] for item in payload["items"]} == {"EPSON", "AGOTADA"}
            assert payload["facets"]["product"]["marcas"] == ["EPSON"]
            selected = list_gestion_full(db, full_mode="en", include_zero_stock=True, marcas=["AGOTADA"])
            assert [item["marca"] for item in selected["items"]] == ["AGOTADA"]
            assert selected["facets"]["product"]["marcas"] == ["AGOTADA", "EPSON"]
            db.add(MarcaVisibleExcepcion(marca="Agotada"))
            db.commit()
            excepted = list_gestion_full(db, full_mode="en", include_zero_stock=True)
            assert excepted["facets"]["product"]["marcas"] == ["AGOTADA", "EPSON"]
        finally:
            db.close()

    def test_include_facets_false_still_lists(self, pg_engine: Engine) -> None:
        db = _session(pg_engine)
        try:
            _seed_linked_row(
                db,
                producto_item_id=1,
                ean="EAN-1",
                marca="TP-LINK",
                categoria="Camaras",
                mla="MLA1",
                inventory_id="INV1",
                user_product_id="MLAU1",
            )
            db.commit()
            payload = list_gestion_full(db, include_facets=False, full_mode="en")
            assert payload["total"] == 1
            assert payload["facets"]["product"]["marcas"] == []
            assert payload["facets"]["product"]["categorias"] == []
        finally:
            db.close()

    def test_q_matches_exact_family_id(self, pg_engine: Engine) -> None:
        db = _session(pg_engine)
        try:
            _seed_linked_row(
                db,
                producto_item_id=1,
                ean="EAN-1",
                marca="TP-LINK",
                categoria="Camaras",
                mla="MLA1",
                inventory_id="INV1",
                user_product_id="MLAU1",
                family_id=4135291218508008,
            )
            _seed_linked_row(
                db,
                producto_item_id=2,
                ean="EAN-2",
                marca="EPSON",
                categoria="Camaras",
                mla="MLA2",
                inventory_id="INV2",
                user_product_id="MLAU2",
                family_id=999,
            )
            db.commit()

            payload = list_gestion_full(db, q="4135291218508008", full_mode="en")
            assert [r["inventory_id"] for r in payload["items"]] == ["INV1"]
            # Partial / wrong id must not match via family_id.
            assert list_gestion_full(db, q="413529", full_mode="en")["items"] == []
        finally:
            db.close()

    def test_null_inventory_id_appears_fuera_and_keeps_noinv_override(self, pg_engine: Engine) -> None:
        db = _session(pg_engine)
        try:
            _seed_linked_row(
                db,
                producto_item_id=1,
                ean="EAN-1",
                marca="TP-LINK",
                categoria="Camaras",
                mla="MLA1",
                inventory_id=None,
                user_product_id="MLAU4380845993",
                full_quantity=0,
            )
            db.add(
                GestionFullOverride(
                    inventory_id="NOINV:MLAU4380845993",
                    cantidad=4,
                    updated_by_id=None,
                )
            )
            db.commit()

            fuera = list_gestion_full(db, full_mode="fuera", include_facets=False)
            assert len(fuera["items"]) == 1
            row = fuera["items"][0]
            assert row["user_product_id"] == "MLAU4380845993"
            assert row["inventory_id"] is None
            assert row["override"] == 4

            # Melí assigns Código ML on the existing publication (same link).
            db.execute(text("UPDATE ml_items SET inventory_id = 'INV-REAL' WHERE user_product_id = 'MLAU4380845993'"))
            db.commit()
            after = list_gestion_full(db, full_mode="fuera", include_facets=False)
            assert len(after["items"]) == 1
            assert after["items"][0]["inventory_id"] == "INV-REAL"
            # NOINV override still resolves via LATERAL even after Código ML appears.
            assert after["items"][0]["override"] == 4
        finally:
            db.close()

    def test_clear_override_by_real_key_drops_legacy_noinv(
        self,
        pg_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Grid clears by live inventory_id; must also drop NOINV:{MLAU} twin."""
        monkeypatch.setattr(
            "app.services.gestion_full.overrides.registrar",
            lambda *args, **kwargs: None,
        )
        db = _session(pg_engine)
        try:
            _seed_linked_row(
                db,
                producto_item_id=1,
                ean="EAN-1",
                marca="TP-LINK",
                categoria="Camaras",
                mla="MLA1",
                inventory_id=None,
                user_product_id="MLAU4380845993",
                full_quantity=0,
            )
            db.add(
                GestionFullOverride(
                    inventory_id="NOINV:MLAU4380845993",
                    cantidad=4,
                    updated_by_id=None,
                )
            )
            db.commit()
            db.execute(text("UPDATE ml_items SET inventory_id = 'INV-REAL' WHERE user_product_id = 'MLAU4380845993'"))
            db.commit()

            usuario = MagicMock(id=1)
            assert clear_override(db, inventory_id="INV-REAL", usuario=usuario) is True

            after = list_gestion_full(db, full_mode="fuera", include_facets=False)
            assert len(after["items"]) == 1
            assert after["items"][0]["override"] is None
            assert db.get(GestionFullOverride, "NOINV:MLAU4380845993") is None
            assert db.get(GestionFullOverride, "INV-REAL") is None
        finally:
            db.close()
