"""Migration `20261024_sell_in_tables`: purchases, their items and consumptions.
Followed by `20261107_sell_in_bonos_marca` (brand bonus, the purchases' origin
columns and the bonus queue) and `20261112_sell_in_compras_porcentaje` (fixed
amount or percentage) and `20261114_sell_in_bonos_alcance` (a bonus's scope and
kind, and its models), so the parity check covers the tables as they are now
(`20261115_sell_in_bono_queue_alcance` only replaces the queue's triggers).

Runs the migration inside a throwaway schema of the Postgres test DB, next to
bare stand-ins of the tables it references (usuarios, proveedores,
pedidos_compra, productos_erp), and proves the CHECK/UNIQUE/CASCADE rules at
the database, which is where they must hold.
"""

from __future__ import annotations

import importlib.util
import uuid
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from app.core.database import Base
from app.models.sell_in import SellInCompra, SellInCompraItem, SellInConsumo

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_MIGRATIONS = [
    _BACKEND_ROOT / "alembic" / "versions" / f"{revision}.py"
    for revision in (
        "20261024_sell_in_tables",
        "20261107_sell_in_bonos_marca",
        "20261112_sell_in_compras_porcentaje",
        "20261114_sell_in_bonos_alcance",
        "20261115_sell_in_bono_queue_alcance",
    )
]
TABLES = {"sell_in_compras", "sell_in_compra_items", "sell_in_consumos"}
BONO_TABLES = {"sell_in_bonos_marca", "sell_in_bono_dirty", "sell_in_bono_items"}

_STUBS = [
    "CREATE TABLE usuarios (id INTEGER PRIMARY KEY)",
    "CREATE TABLE proveedores (id INTEGER PRIMARY KEY)",
    "CREATE TABLE pedidos_compra (id BIGINT PRIMARY KEY, proveedor_id INTEGER, estado VARCHAR(24), "
    "tipo_cambio NUMERIC(18, 6), fecha_factura DATE)",
    "CREATE TABLE productos_erp (item_id INTEGER PRIMARY KEY, marca VARCHAR(100), categoria VARCHAR(100))",
    "CREATE TABLE pedido_compra_lineas_facturadas (id BIGSERIAL PRIMARY KEY, pedido_id BIGINT, item_id INTEGER, "
    "cantidad INTEGER, importe_neto NUMERIC(18, 2), moneda VARCHAR(3))",
    "INSERT INTO usuarios VALUES (7)",
    "INSERT INTO proveedores VALUES (3)",
    "INSERT INTO pedidos_compra (id) VALUES (900)",
    "INSERT INTO productos_erp VALUES (4512), (4513)",
]

_INSERT_COMPRA = (
    "INSERT INTO sell_in_compras (proveedor_id, pedido_compra_id, fecha_compra, fecha_ingreso, cuenta_desde, "
    "moneda, monto_total, tipo_cambio, descripcion, usuario_id) VALUES (:proveedor, :pedido, :fecha, :ingreso, "
    ":desde, :moneda, :monto, :tc, 'Bonificación Q4 switches', 7) RETURNING id"
)
_INSERT_ITEM = (
    "INSERT INTO sell_in_compra_items (compra_id, item_id, cantidad, costo_base_unit, monto_asignado) "
    "VALUES (:compra, :item, :cantidad, :costo, :monto) RETURNING id"
)
_INSERT_CONSUMO = (
    "INSERT INTO sell_in_consumos (compra_item_id, canal, venta_ref, item_id, fecha_venta, unidades, descuento_ars) "
    "VALUES (:compra_item, :canal, :ref, 4512, DATE '2026-10-20', :unidades, 1500.00)"
)


def _compra(**overrides) -> dict:
    row = {
        "proveedor": 3,
        "pedido": 900,
        "fecha": "2026-10-01",
        "ingreso": None,
        "desde": "compra",
        "moneda": "ARS",
        "monto": "250000.00",
        "tc": None,
    }
    row.update(overrides)
    return row


def _load_migration(path: Path):
    spec = importlib.util.spec_from_file_location(f"{path.stem}_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@contextmanager
def _throwaway_schema(prefix: str, build):
    """Yield an engine bound to a fresh schema holding the stubs plus whatever `build` creates."""
    from tests.conftest import POSTGRES_TEST_URL, _postgres_reachable

    if not _postgres_reachable():
        pytest.skip(f"PostgreSQL not reachable at {POSTGRES_TEST_URL}")
    schema = f"{prefix}_{uuid.uuid4().hex[:8]}"
    admin_engine = create_engine(POSTGRES_TEST_URL, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f"CREATE SCHEMA {schema}"))
    eng = create_engine(POSTGRES_TEST_URL, connect_args={"options": f"-csearch_path={schema}"})
    try:
        with eng.begin() as conn:
            for statement in _STUBS:
                conn.execute(text(statement))
        build(eng)
        yield eng
    finally:
        eng.dispose()
        with admin_engine.connect() as conn:
            conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        admin_engine.dispose()


@pytest.fixture()
def engine():
    """Schema built by running the migration."""
    with _throwaway_schema("sell_in", lambda eng: _run(eng, "upgrade")) as eng:
        yield eng


@pytest.fixture()
def orm_engine():
    """Schema built from the ORM metadata (`Base.metadata`), for the parity check.

    The SQLite `engine` fixture patches the shared column types in place (BigInteger PKs become
    Integer), so when any SQLite test ran earlier in the session the DDL would not be production's.
    Build with the real Postgres types, then put back whatever types the columns had, so the
    SQLite tests that run after this one still see their patch.
    """
    from tests.conftest import _restore_pristine_pg_types

    tables = [Base.metadata.tables[name] for name in sorted(TABLES | BONO_TABLES)]
    found = {column: column.type for table in tables for column in table.columns}

    def build(eng) -> None:
        _restore_pristine_pg_types(tables)
        try:
            Base.metadata.create_all(bind=eng, tables=tables)
        finally:
            for column, column_type in found.items():
                column.type = column_type

    with _throwaway_schema("sell_in_orm", build) as eng:
        yield eng


def _run(engine, step: str) -> None:
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext

    for path in _MIGRATIONS if step == "upgrade" else reversed(_MIGRATIONS):
        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            with ctx.begin_transaction(), Operations.context(ctx):
                getattr(_load_migration(path), step)()


def _rejects(engine, statement: str, params: dict) -> None:
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(text(statement), params)


def _new_compra(conn, **overrides) -> int:
    return conn.execute(text(_INSERT_COMPRA), _compra(**overrides)).scalar_one()


def _columns(conn, table: str) -> set[str]:
    rows = conn.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = :t"
        ),
        {"t": table},
    )
    return {r[0] for r in rows}


_CATALOG = {
    "columns": (
        "SELECT table_name, column_name, data_type, character_maximum_length, numeric_precision, numeric_scale, "
        "is_nullable, column_default FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name LIKE 'sell_in%'"
    ),
    "constraints": (
        "SELECT c.conrelid::regclass::text, c.conname, pg_get_constraintdef(c.oid) FROM pg_constraint c "
        "WHERE c.connamespace = current_schema()::regnamespace AND c.conrelid::regclass::text LIKE 'sell_in%'"
    ),
    "indexes": (
        "SELECT tablename, indexname, replace(indexdef, schemaname || '.', '') FROM pg_indexes "
        "WHERE schemaname = current_schema() AND tablename LIKE 'sell_in%'"
    ),
}


def _catalog(engine) -> dict[str, set[tuple]]:
    with engine.connect() as conn:
        return {kind: {tuple(r) for r in conn.execute(text(sql))} for kind, sql in _CATALOG.items()}


def _fk_rule(conn, table: str, column: str) -> str:
    return conn.execute(
        text(
            "SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c JOIN pg_attribute a "
            "ON a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey) "
            "WHERE c.contype = 'f' AND c.conrelid = CAST(:t AS regclass) AND a.attname = :c"
        ),
        {"t": table, "c": column},
    ).scalar_one()


@pytest.mark.postgres
def test_migrated_schema_matches_the_orm_metadata(engine, orm_engine) -> None:
    """Types, nullability, server defaults, CHECK/UNIQUE/FK names and rules, and indexes all agree."""
    migrated, declared = _catalog(engine), _catalog(orm_engine)
    for kind in _CATALOG:
        assert migrated[kind] == declared[kind], kind
    assert migrated["constraints"], "the catalog query must see the constraints"


@pytest.mark.postgres
class TestSellInMigration:
    def test_upgrade_creates_the_three_tables_matching_the_models(self, engine) -> None:
        with engine.connect() as conn:
            tables = {
                r[0] for r in conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = current_schema()"))
            }
            assert TABLES <= tables
            for model in (SellInCompra, SellInCompraItem, SellInConsumo):
                assert _columns(conn, model.__tablename__) == {c.name for c in model.__table__.columns}

    def test_defaults_count_from_purchase_date_proportional_and_active(self, engine) -> None:
        with engine.begin() as conn:
            compra_id = _new_compra(conn)
            row = conn.execute(
                text("SELECT cuenta_desde, formula, estado, created_at, updated_at FROM sell_in_compras WHERE id = :i"),
                {"i": compra_id},
            ).one()
        assert (row.cuenta_desde, row.formula, row.estado) == ("compra", "proporcional", "activa")
        assert row.created_at.tzinfo is not None and row.updated_at.tzinfo is not None

    def test_usd_requires_an_exchange_rate(self, engine) -> None:
        _rejects(engine, _INSERT_COMPRA, _compra(moneda="USD", monto="1800.00"))
        with engine.begin() as conn:
            assert _new_compra(conn, moneda="USD", monto="1800.00", tc="1450.500000")

    def test_counting_from_goods_receipt_requires_its_date(self, engine) -> None:
        _rejects(engine, _INSERT_COMPRA, _compra(desde="ingreso"))
        with engine.begin() as conn:
            assert _new_compra(conn, desde="ingreso", ingreso="2026-10-08")

    @pytest.mark.parametrize(
        "overrides",
        [{"monto": "0"}, {"monto": "-10.00"}, {"moneda": "EUR"}, {"desde": "factura"}],
    )
    def test_purchase_checks(self, engine, overrides) -> None:
        _rejects(engine, _INSERT_COMPRA, _compra(**overrides))

    @pytest.mark.parametrize(("column", "value"), [("formula", "ppp"), ("estado", "borrada")])
    def test_formula_and_state_are_closed_sets(self, engine, column, value) -> None:
        with engine.begin() as conn:
            compra_id = _new_compra(conn)
        _rejects(engine, f"UPDATE sell_in_compras SET {column} = :v WHERE id = :i", {"v": value, "i": compra_id})

    def test_items_are_unique_per_purchase_and_need_positive_quantity(self, engine) -> None:
        with engine.begin() as conn:
            compra_id = _new_compra(conn)
            conn.execute(
                text(_INSERT_ITEM),
                {"compra": compra_id, "item": 4512, "cantidad": 10, "costo": "25000", "monto": "250000.00"},
            )
        item = {"compra": compra_id, "item": 4512, "cantidad": 5, "costo": "25000", "monto": "0"}
        _rejects(engine, _INSERT_ITEM, item)
        _rejects(engine, _INSERT_ITEM, {**item, "item": 4513, "cantidad": 0})
        _rejects(engine, _INSERT_ITEM, {**item, "item": 4513, "monto": "-0.01"})
        _rejects(engine, _INSERT_ITEM, {**item, "item": 99999})  # not in productos_erp

    def test_consumptions_unique_per_channel_sale_and_line(self, engine) -> None:
        with engine.begin() as conn:
            compra_id = _new_compra(conn)
            line = conn.execute(
                text(_INSERT_ITEM),
                {"compra": compra_id, "item": 4512, "cantidad": 10, "costo": "25000", "monto": "250000.00"},
            ).scalar_one()
            # venta_ref has no FK: an ML sale line id that does not exist here is fine.
            conn.execute(
                text(_INSERT_CONSUMO), {"compra_item": line, "canal": "ml", "ref": 2000018265495500, "unidades": 1}
            )
            conn.execute(
                text(_INSERT_CONSUMO), {"compra_item": line, "canal": "tn", "ref": 2000018265495500, "unidades": 1}
            )
        consumo = {"compra_item": line, "canal": "ml", "ref": 2000018265495500, "unidades": 1}
        _rejects(engine, _INSERT_CONSUMO, consumo)
        _rejects(engine, _INSERT_CONSUMO, {**consumo, "canal": "mayor", "ref": 1})
        _rejects(engine, _INSERT_CONSUMO, {**consumo, "ref": 2, "unidades": 0})

    def test_consumption_lookup_index_on_item_and_sale_date(self, engine) -> None:
        with engine.connect() as conn:
            indexdef = conn.execute(
                text(
                    "SELECT indexdef FROM pg_indexes WHERE schemaname = current_schema() "
                    "AND tablename = 'sell_in_consumos' AND indexdef LIKE '%(item_id, fecha_venta)%'"
                )
            ).scalar_one()
        assert "sell_in_consumos" in indexdef

    def test_deleting_a_purchase_cascades_to_items_and_consumptions(self, engine) -> None:
        with engine.begin() as conn:
            compra_id = _new_compra(conn)
            line = conn.execute(
                text(_INSERT_ITEM),
                {"compra": compra_id, "item": 4512, "cantidad": 10, "costo": "25000", "monto": "250000.00"},
            ).scalar_one()
            conn.execute(text(_INSERT_CONSUMO), {"compra_item": line, "canal": "fuera", "ref": 88123, "unidades": 2})
            conn.execute(text("DELETE FROM sell_in_compras WHERE id = :i"), {"i": compra_id})
            assert conn.execute(text("SELECT count(*) FROM sell_in_compra_items")).scalar_one() == 0
            assert conn.execute(text("SELECT count(*) FROM sell_in_consumos")).scalar_one() == 0

    @pytest.mark.parametrize("rate", ["0", "-1450.50"])
    def test_exchange_rate_must_be_positive_when_present(self, engine, rate) -> None:
        _rejects(engine, _INSERT_COMPRA, _compra(moneda="USD", monto="1800.00", tc=rate))
        _rejects(engine, _INSERT_COMPRA, _compra(tc=rate))

    def test_base_cost_cannot_be_negative_but_can_be_zero(self, engine) -> None:
        with engine.begin() as conn:
            compra_id = _new_compra(conn)
            item = {"compra": compra_id, "item": 4512, "cantidad": 2, "costo": "0", "monto": "100.00"}
            assert conn.execute(text(_INSERT_ITEM), item).scalar_one()
        _rejects(engine, _INSERT_ITEM, {**item, "item": 4513, "costo": "-0.000001"})

    def test_consumption_discount_cannot_be_negative(self, engine) -> None:
        statement = (
            "INSERT INTO sell_in_consumos (compra_item_id, canal, venta_ref, item_id, fecha_venta, unidades, "
            "descuento_ars) VALUES (:line, 'ml', :ref, 4512, DATE '2026-10-20', 1, :descuento)"
        )
        with engine.begin() as conn:
            compra_id = _new_compra(conn)
            line = conn.execute(
                text(_INSERT_ITEM),
                {"compra": compra_id, "item": 4512, "cantidad": 10, "costo": "25000", "monto": "250000.00"},
            ).scalar_one()
            conn.execute(text(statement), {"line": line, "ref": 1, "descuento": "0"})
        _rejects(engine, statement, {"line": line, "ref": 2, "descuento": "-0.01"})

    def test_consumption_index_on_purchase_line(self, engine) -> None:
        with engine.connect() as conn:
            found = conn.execute(
                text(
                    "SELECT count(*) FROM pg_indexes WHERE schemaname = current_schema() "
                    "AND tablename = 'sell_in_consumos' AND indexdef LIKE '%btree (compra_item_id)'"
                )
            ).scalar_one()
        assert found == 1

    def test_foreign_key_delete_rules(self, engine) -> None:
        with engine.connect() as conn:
            assert "ON DELETE RESTRICT" in _fk_rule(conn, "sell_in_compras", "proveedor_id")
            assert "ON DELETE RESTRICT" in _fk_rule(conn, "sell_in_compras", "usuario_id")
            assert "ON DELETE SET NULL" in _fk_rule(conn, "sell_in_compras", "pedido_compra_id")
            assert "ON DELETE CASCADE" in _fk_rule(conn, "sell_in_consumos", "compra_item_id")

    @pytest.mark.parametrize("statement", ["DELETE FROM proveedores WHERE id = 3", "DELETE FROM usuarios WHERE id = 7"])
    def test_supplier_and_user_of_a_purchase_cannot_be_deleted(self, engine, statement) -> None:
        with engine.begin() as conn:
            _new_compra(conn)
        _rejects(engine, statement, {})

    def test_deleting_the_purchase_order_unlinks_the_purchase(self, engine) -> None:
        with engine.begin() as conn:
            compra_id = _new_compra(conn)
            conn.execute(text("DELETE FROM pedidos_compra WHERE id = 900"))
            pedido = conn.execute(
                text("SELECT pedido_compra_id FROM sell_in_compras WHERE id = :i"), {"i": compra_id}
            ).scalar_one()
        assert pedido is None

    def test_deleting_a_purchase_line_cascades_to_its_consumptions(self, engine) -> None:
        with engine.begin() as conn:
            compra_id = _new_compra(conn)
            line = conn.execute(
                text(_INSERT_ITEM),
                {"compra": compra_id, "item": 4512, "cantidad": 10, "costo": "25000", "monto": "250000.00"},
            ).scalar_one()
            conn.execute(text(_INSERT_CONSUMO), {"compra_item": line, "canal": "ml", "ref": 5, "unidades": 1})
            conn.execute(text("DELETE FROM sell_in_compra_items WHERE id = :i"), {"i": line})
            assert conn.execute(text("SELECT count(*) FROM sell_in_consumos")).scalar_one() == 0

    def test_raw_update_refreshes_updated_at_in_the_database(self, engine) -> None:
        with engine.begin() as conn:
            compra_id = _new_compra(conn)
        with engine.begin() as conn:
            # Even an explicit stale value is overwritten: the database owns updated_at.
            conn.execute(
                text(
                    "UPDATE sell_in_compras SET descripcion = 'Bonificación Q4 corregida', "
                    "updated_at = TIMESTAMPTZ '2020-01-01 00:00+00' WHERE id = :i"
                ),
                {"i": compra_id},
            )
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT created_at, updated_at FROM sell_in_compras WHERE id = :i"), {"i": compra_id}
            ).one()
        assert row.updated_at > row.created_at

    def test_downgrade_drops_the_three_tables_and_the_trigger_function(self, engine) -> None:
        _run(engine, "downgrade")
        with engine.connect() as conn:
            tables = {
                r[0] for r in conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = current_schema()"))
            }
            functions = conn.execute(
                text(
                    "SELECT count(*) FROM pg_proc WHERE pronamespace = current_schema()::regnamespace "
                    "AND proname = 'sell_in_set_updated_at'"
                )
            ).scalar_one()
        assert not ((TABLES | BONO_TABLES) & tables)
        assert functions == 0
