"""Migration `20261105_sell_out_campanas`: sell-out campaigns, their groups and permissions.

The schema is built by every sell-out migration in order (`_MIGRATIONS`), so the
parity test also covers `20261108_sell_out_consumos`, `20261207_sell_out_campana_items` and
`20261214_sell_out_monto_total`; their own rules are proven
in `tests/unit/test_migration_sell_out_consumos.py` and `tests/migrations/`.

Runs the migration inside a throwaway schema of the Postgres test DB, next to
bare stand-ins of the tables it references, and proves the CHECK/UNIQUE/FK
rules at the database, plus the permission seed and its downgrade.
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

_MIGRATIONS = [
    Path(__file__).resolve().parents[2] / "alembic" / "versions" / f"{revision}.py"
    for revision in (
        "20261105_sell_out_campanas",
        "20261108_sell_out_consumos",
        "20261111_sell_out_offset_origen",
        "20261207_sell_out_campana_items",
        "20261214_sell_out_monto_total",
    )
]
TABLES = (
    "sell_out_campanas",
    "sell_out_campana_grupos",
    "sell_out_campana_items",
    "sell_out_consumos",
    "sell_out_dirty",
)

_STUBS = [
    "CREATE TABLE usuarios (id INTEGER PRIMARY KEY)",
    "CREATE TABLE offset_grupos (id INTEGER PRIMARY KEY)",
    "CREATE TABLE offsets_ganancia (id INTEGER PRIMARY KEY)",
    "CREATE TABLE roles (id SERIAL PRIMARY KEY, codigo VARCHAR(50) UNIQUE)",
    "CREATE TABLE permisos (id SERIAL PRIMARY KEY, codigo VARCHAR(100) UNIQUE, nombre TEXT, descripcion TEXT, "
    "categoria TEXT, orden INTEGER, es_critico BOOLEAN, created_at TIMESTAMPTZ)",
    "CREATE TABLE roles_permisos_base (rol_id INTEGER, permiso_id INTEGER, PRIMARY KEY (rol_id, permiso_id))",
    "CREATE TABLE usuarios_permisos_override (usuario_id INTEGER, permiso_id INTEGER)",
    "INSERT INTO usuarios VALUES (7)",
    "INSERT INTO offset_grupos VALUES (1), (2)",
    "INSERT INTO roles (codigo) VALUES ('ADMIN'), ('VENTAS')",
]

_INSERT = (
    "INSERT INTO sell_out_campanas (nombre, fecha_desde, fecha_hasta, tipo, monto_unit, moneda, tc_modo, tipo_cambio, "
    "porcentaje, tope_unidades, tope_monto, usuario_id) VALUES ('Campaña TP-Link Q4', :desde, :hasta, :tipo, "
    ":monto, :moneda, :modo, :tc, :pct, :tope_u, :tope_m, 7) RETURNING id"
)


def _row(**overrides) -> dict:
    row = {
        "desde": "2026-11-01",
        "hasta": "2026-11-30",
        "tipo": "por_unidad",
        "monto": "1500.00",
        "moneda": "ARS",
        "modo": None,
        "tc": None,
        "pct": None,
        "tope_u": None,
        "tope_m": None,
    }
    row.update(overrides)
    return row


def _load_migration(path: Path):
    spec = importlib.util.spec_from_file_location(f"{path.stem}_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(engine, step: str) -> None:
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext

    for path in _MIGRATIONS if step == "upgrade" else reversed(_MIGRATIONS):
        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            with ctx.begin_transaction(), Operations.context(ctx):
                getattr(_load_migration(path), step)()


@contextmanager
def _throwaway_schema(prefix: str, build):
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
    with _throwaway_schema("sell_out", lambda eng: _run(eng, "upgrade")) as eng:
        yield eng


@pytest.fixture()
def orm_engine():
    """Schema built from the ORM metadata, with the real Postgres types (see the sell-in twin)."""
    from tests.conftest import _restore_pristine_pg_types

    tables = [Base.metadata.tables[name] for name in TABLES]
    found = {column: column.type for table in tables for column in table.columns}

    def build(eng) -> None:
        _restore_pristine_pg_types(tables)
        try:
            Base.metadata.create_all(bind=eng, tables=tables)
        finally:
            for column, column_type in found.items():
                column.type = column_type

    with _throwaway_schema("sell_out_orm", build) as eng:
        yield eng


def _rejects(engine, statement: str, params: dict) -> None:
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(text(statement), params)


def _new(conn, **overrides) -> int:
    return conn.execute(text(_INSERT), _row(**overrides)).scalar_one()


_CATALOG = {
    "columns": (
        "SELECT table_name, column_name, data_type, character_maximum_length, numeric_precision, numeric_scale, "
        "is_nullable, column_default FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name LIKE 'sell_out%'"
    ),
    "constraints": (
        "SELECT c.conrelid::regclass::text, c.conname, pg_get_constraintdef(c.oid) FROM pg_constraint c "
        "WHERE c.connamespace = current_schema()::regnamespace AND c.conrelid::regclass::text LIKE 'sell_out%'"
    ),
    "indexes": (
        "SELECT tablename, indexname, replace(indexdef, schemaname || '.', '') FROM pg_indexes "
        "WHERE schemaname = current_schema() AND tablename LIKE 'sell_out%'"
    ),
}


def _catalog(engine) -> dict[str, set[tuple]]:
    with engine.connect() as conn:
        return {kind: {tuple(r) for r in conn.execute(text(sql))} for kind, sql in _CATALOG.items()}


@pytest.mark.postgres
def test_migrated_schema_matches_the_orm_metadata(engine, orm_engine) -> None:
    migrated, declared = _catalog(engine), _catalog(orm_engine)
    for kind in _CATALOG:
        assert migrated[kind] == declared[kind], kind
    assert migrated["constraints"]


@pytest.mark.postgres
class TestSellOutMigration:
    def test_defaults_stack_on_cost_and_start_active(self, engine) -> None:
        with engine.begin() as conn:
            campana_id = _new(conn)
            row = conn.execute(
                text("SELECT acumulable, base_porcentaje, estado, updated_at FROM sell_out_campanas WHERE id = :i"),
                {"i": campana_id},
            ).one()
        assert (row.acumulable, row.base_porcentaje, row.estado) == (True, "costo", "activa")
        assert row.updated_at.tzinfo is not None

    def test_percentage_campaign_is_accepted_without_unit_amount(self, engine) -> None:
        with engine.begin() as conn:
            assert _new(conn, tipo="porcentaje", monto=None, pct="100")

    @pytest.mark.parametrize(
        "overrides",
        [
            {"monto": None},  # per unit without its amount
            {"monto": "0"},
            {"pct": "5"},  # per unit carrying a percentage too
            {"tipo": "porcentaje", "monto": None, "pct": None},
            {"tipo": "porcentaje", "monto": None, "pct": "0"},
            {"tipo": "porcentaje", "monto": None, "pct": "100.01"},
            {"tipo": "porcentaje", "monto": "10.00", "pct": "5"},  # percentage carrying a unit amount too
            {"tipo": "bono"},
            {"hasta": "2026-10-31"},  # ends before it starts
            {"moneda": "USD"},  # USD without its FX mode
            {"moneda": "USD", "modo": "fijo"},  # fixed mode without its rate
            {"moneda": "USD", "modo": "dia_venta", "tc": "1450"},  # sale-day mode carrying a rate
            {"moneda": "USD", "modo": "otro"},
            {"modo": "fijo", "tc": "1450"},  # ARS carrying an FX mode
            {"tc": "1450"},  # ARS carrying a rate
            {"moneda": "EUR"},
            {"moneda": "USD", "modo": "fijo", "tc": "0"},
            {"tope_u": 0},
            {"tope_m": "0"},
        ],
    )
    def test_campaign_checks(self, engine, overrides) -> None:
        _rejects(engine, _INSERT, _row(**overrides))

    def test_a_one_day_campaign_and_usd_with_rate_are_valid(self, engine) -> None:
        with engine.begin() as conn:
            assert _new(conn, hasta="2026-11-01", moneda="USD", modo="fijo", tc="1450.5", tope_u=500, tope_m="2000.00")
            assert _new(conn, moneda="USD", modo="dia_venta")
            assert _new(conn, moneda="USD", modo="al_cobro")

    def test_currency_defaults_to_usd(self, engine) -> None:
        with engine.begin() as conn:
            campana_id = conn.execute(
                text(
                    "INSERT INTO sell_out_campanas (nombre, fecha_desde, fecha_hasta, tipo, monto_unit, tc_modo, "
                    "usuario_id) VALUES ('X', DATE '2026-11-01', DATE '2026-11-30', 'por_unidad', 3, 'al_cobro', 7) "
                    "RETURNING id"
                )
            ).scalar_one()
            assert (
                conn.execute(text("SELECT moneda FROM sell_out_campanas WHERE id = :i"), {"i": campana_id}).scalar_one()
                == "USD"
            )

    def test_rate_set_at_payment_carries_when_it_was_set(self, engine) -> None:
        """`tc_definido_en` is set exactly when an `al_cobro` campaign has its rate."""
        with engine.begin() as conn:
            campana_id = _new(conn, moneda="USD", modo="al_cobro")
        set_rate = "UPDATE sell_out_campanas SET tipo_cambio = :tc, tc_definido_en = :en WHERE id = :i"
        _rejects(engine, set_rate, {"tc": "1450", "en": None, "i": campana_id})
        _rejects(engine, set_rate, {"tc": None, "en": "2026-12-05T10:00:00+00", "i": campana_id})
        with engine.begin() as conn:
            conn.execute(text(set_rate), {"tc": "1450", "en": "2026-12-05T10:00:00+00", "i": campana_id})
        with engine.begin() as conn:
            fijo = _new(conn, moneda="USD", modo="fijo", tc="1450")
        _rejects(engine, "UPDATE sell_out_campanas SET tc_definido_en = now() WHERE id = :i", {"i": fijo})

    @pytest.mark.parametrize(("column", "value"), [("base_porcentaje", "precio_lista"), ("estado", "borrada")])
    def test_closed_sets(self, engine, column, value) -> None:
        with engine.begin() as conn:
            campana_id = _new(conn)
        _rejects(engine, f"UPDATE sell_out_campanas SET {column} = :v WHERE id = :i", {"v": value, "i": campana_id})

    def test_groups_link_once_cascade_with_the_campaign_and_block_group_delete(self, engine) -> None:
        link = "INSERT INTO sell_out_campana_grupos (campana_id, grupo_id) VALUES (:c, :g)"
        with engine.begin() as conn:
            campana_id = _new(conn)
            conn.execute(text(link), {"c": campana_id, "g": 1})
        _rejects(engine, link, {"c": campana_id, "g": 1})
        _rejects(engine, "DELETE FROM offset_grupos WHERE id = :g", {"g": 1})
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM sell_out_campanas WHERE id = :c"), {"c": campana_id})
            assert conn.execute(text("SELECT count(*) FROM sell_out_campana_grupos")).scalar_one() == 0

    def test_permissions_are_seeded_for_admin_and_removed_on_downgrade(self, engine) -> None:
        granted = (
            "SELECT r.codigo, p.codigo FROM roles_permisos_base rp JOIN roles r ON r.id = rp.rol_id "
            "JOIN permisos p ON p.id = rp.permiso_id ORDER BY 1, 2"
        )
        with engine.connect() as conn:
            assert [tuple(r) for r in conn.execute(text(granted))] == [
                ("ADMIN", "sell_out.gestionar"),
                ("ADMIN", "sell_out.ver"),
            ]
        _run(engine, "downgrade")
        with engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM permisos")).scalar_one() == 0
            tables = {
                r[0] for r in conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = current_schema()"))
            }
        assert not tables & set(TABLES)
        with engine.connect() as conn:
            funciones = "SELECT count(*) FROM pg_proc WHERE proname = 'sell_out_set_updated_at'"
            assert conn.execute(text(funciones)).scalar_one() == 0
            triggers = "SELECT count(*) FROM pg_trigger WHERE tgname = 'sell_out_campanas_updated_at'"
            assert conn.execute(text(triggers)).scalar_one() == 0

    def test_a_raw_sql_update_moves_updated_at(self, engine) -> None:
        """The BEFORE UPDATE trigger, not the ORM, keeps `updated_at` (now() is per transaction: two of them)."""
        with engine.begin() as conn:
            campana_id = _new(conn)
            antes = conn.execute(
                text("SELECT updated_at FROM sell_out_campanas WHERE id = :i"), {"i": campana_id}
            ).scalar_one()
        with engine.begin() as conn:
            conn.execute(text("UPDATE sell_out_campanas SET nombre = 'Renombrada' WHERE id = :i"), {"i": campana_id})
            despues = conn.execute(
                text("SELECT updated_at FROM sell_out_campanas WHERE id = :i"), {"i": campana_id}
            ).scalar_one()
        assert despues > antes
