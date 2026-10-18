"""Migration `20261101_combo_componentes` (combos-propios C1): graph, DDL and
the initial fill from the ERP mirror, upgrade/downgrade on a real Postgres."""

from __future__ import annotations

import importlib.util
import os
import uuid
from decimal import Decimal
from typing import Iterator

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from app.models.combo_componente import ComboComponente
from app.models.tb_item_association import TbItemAssociation
from tests.conftest import POSTGRES_TEST_URL, _postgres_reachable, _restore_pristine_pg_types

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_REVISION = "20261101_combo_componentes"
_PATH = os.path.join(_BACKEND_ROOT, "alembic", "versions", f"{_REVISION}.py")
_SOURCES = [TbItemAssociation.__table__]


def _script_directory() -> ScriptDirectory:
    config = Config(os.path.join(_BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(_BACKEND_ROOT, "alembic"))
    return ScriptDirectory.from_config(config)


def _module():
    spec = importlib.util.spec_from_file_location("combo_componentes_migration", _PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestMigrationGraph:
    def test_single_head_descends_from_this_revision(self) -> None:
        scripts = _script_directory()
        heads = scripts.get_heads()
        assert len(heads) == 1
        lineage = {rev.revision for rev in scripts.iterate_revisions(heads[0], "base")}
        assert _REVISION in lineage

    def test_chains_on_the_previous_head(self) -> None:
        assert _script_directory().get_revision(_REVISION).down_revision == "20261031_sell_dirty_queue"


@pytest.fixture()
def pg_engine() -> Iterator[Engine]:
    """A throwaway schema (first on `search_path`) holding only the ERP mirror,
    so leftovers in the shared test database never hide the real upgrade."""
    if not _postgres_reachable():
        pytest.skip(f"PostgreSQL not reachable at {POSTGRES_TEST_URL}")
    _restore_pristine_pg_types(_SOURCES)
    schema = f"combo_comp_mig_{uuid.uuid4().hex[:8]}"
    admin = create_engine(POSTGRES_TEST_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f"CREATE SCHEMA {schema}"))
    engine = create_engine(POSTGRES_TEST_URL, connect_args={"options": f"-csearch_path={schema}"})
    try:
        with engine.begin() as conn:
            assert conn.execute(text("SELECT current_schema()")).scalar() == schema
            for table in _SOURCES:
                table.create(bind=conn)
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        admin.dispose()


def _association(conn, itema_id: int, combo: int | None, componente: int | None, qty, comp_id: int = 1) -> None:
    conn.execute(
        text(
            "INSERT INTO tb_item_association (comp_id, itema_id, item_id, item_id_1, iasso_qty) "
            "VALUES (:comp_id, :itema_id, :combo, :componente, :qty)"
        ),
        {"comp_id": comp_id, "itema_id": itema_id, "combo": combo, "componente": componente, "qty": qty},
    )


def _filled(engine: Engine) -> list[tuple]:
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT combo_item_id, componente_item_id, cantidad FROM combo_componentes "
                "ORDER BY combo_item_id, componente_item_id"
            )
        ).all()
    return [tuple(r) for r in rows]


def _upgrade(engine: Engine) -> None:
    with engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            _module().upgrade()


@pytest.mark.postgres
class TestMigrationDdl:
    def test_upgrade_creates_the_table_and_downgrade_drops_it(self, pg_engine: Engine) -> None:
        _upgrade(pg_engine)
        with pg_engine.begin() as conn:
            columns = {c["name"] for c in inspect(conn).get_columns("combo_componentes")}
            assert columns == {c.name for c in ComboComponente.__table__.columns}
            indexes = {tuple(i["column_names"]) for i in inspect(conn).get_indexes("combo_componentes")}
            assert ("componente_item_id",) in indexes
            assert inspect(conn).get_foreign_keys("combo_componentes") == []

        with pg_engine.begin() as conn:
            with Operations.context(MigrationContext.configure(conn)):
                _module().downgrade()
            assert not inspect(conn).has_table("combo_componentes")

    def test_quantity_must_be_positive(self, pg_engine: Engine) -> None:
        _upgrade(pg_engine)
        with pytest.raises(IntegrityError):
            with pg_engine.begin() as conn:
                conn.execute(
                    text("INSERT INTO combo_componentes (combo_item_id, componente_item_id, cantidad) VALUES (1, 2, 0)")
                )

    def test_a_pair_is_stored_once(self, pg_engine: Engine) -> None:
        _upgrade(pg_engine)
        with pytest.raises(IntegrityError):
            with pg_engine.begin() as conn:
                for _ in range(2):
                    conn.execute(
                        text(
                            "INSERT INTO combo_componentes (combo_item_id, componente_item_id, cantidad) "
                            "VALUES (1, 2, 1)"
                        )
                    )


@pytest.mark.postgres
class TestInitialFill:
    def test_copies_positive_rows_and_sums_a_repeated_pair(self, pg_engine: Engine) -> None:
        with pg_engine.begin() as conn:
            _association(conn, 1, combo=100, componente=500, qty=2)
            _association(conn, 2, combo=100, componente=600, qty=1)
            # The same pair twice in the ERP: the BOM holds their sum.
            _association(conn, 3, combo=200, componente=500, qty=1)
            _association(conn, 4, combo=200, componente=500, qty=Decimal("0.5"))
            # Not a composition: zero, negative or missing quantity.
            _association(conn, 5, combo=300, componente=700, qty=0)
            _association(conn, 6, combo=300, componente=701, qty=-1)
            _association(conn, 7, combo=300, componente=702, qty=None)

        _upgrade(pg_engine)

        with pg_engine.begin() as conn:
            rows = conn.execute(
                text(
                    "SELECT combo_item_id, componente_item_id, cantidad FROM combo_componentes "
                    "ORDER BY combo_item_id, componente_item_id"
                )
            ).all()
            filled = conn.execute(text("SELECT bool_and(created_at IS NOT NULL) FROM combo_componentes")).scalar()
        assert [tuple(r) for r in rows] == [
            (100, 500, Decimal("2.0000")),
            (100, 600, Decimal("1.0000")),
            (200, 500, Decimal("1.5000")),
        ]
        assert filled is True

    # The fill mirrors `combos.sync` (`fuente_erp.snapshot_desde_registros`), which
    # refuses the whole snapshot (writes nothing) on any of these: the table must
    # come out empty, never a partial or cross-company BOM.
    def test_the_same_pair_under_two_companies_fills_nothing(self, pg_engine: Engine) -> None:
        with pg_engine.begin() as conn:
            _association(conn, 1, combo=100, componente=500, qty=2, comp_id=1)
            _association(conn, 1, combo=100, componente=500, qty=3, comp_id=2)

        _upgrade(pg_engine)

        assert _filled(pg_engine) == []

    @pytest.mark.parametrize(
        ("combo", "componente"), [(None, 500), (100, None)], ids=["null_item_id", "null_item_id_1"]
    )
    def test_a_row_without_combo_or_component_fills_nothing(self, pg_engine: Engine, combo, componente) -> None:
        with pg_engine.begin() as conn:
            _association(conn, 1, combo=200, componente=600, qty=1)
            _association(conn, 2, combo=combo, componente=componente, qty=1)

        _upgrade(pg_engine)

        assert _filled(pg_engine) == []

    def test_an_unreadable_quantity_fills_nothing(self, pg_engine: Engine) -> None:
        with pg_engine.begin() as conn:
            _association(conn, 1, combo=200, componente=600, qty=1)
            _association(conn, 2, combo=200, componente=601, qty=Decimal("NaN"))

        _upgrade(pg_engine)

        assert _filled(pg_engine) == []

    def test_upgrade_without_the_mirror_creates_an_empty_table(self, pg_engine: Engine) -> None:
        with pg_engine.begin() as conn:
            conn.execute(text("DROP TABLE tb_item_association"))

        _upgrade(pg_engine)

        with pg_engine.begin() as conn:
            assert inspect(conn).has_table("combo_componentes")
        assert _filled(pg_engine) == []
