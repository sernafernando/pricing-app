"""Migration `20261017_ml_items_installments_campaign`: a typed column for the installments campaign.

The markup of every publication needs the `INSTALLMENTS_CAMPAIGN` sale term when the item has no campaign tag.
It was extracted per request from the whole `raw` body (TOASTed, about 7 KB per item), which read ~190 MB through
the buffer cache on every set-wide request. The migration adds the column and backfills it from `raw`, in
batches that commit on their own, so a live store is never locked for the whole table. The backfill must produce
exactly what the item mapper produces at ingest (`mappers.installments_campaign`), which the equivalence test pins
on the captured bodies.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import uuid

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text

from app.services.ml_publications.mappers import map_item
from tests.services.ml_publications.conftest import ITEM_SAMPLES, load_fixture

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_REVISION = "20261017_ml_items_installments_campaign"
_PATH = os.path.join(_BACKEND_ROOT, "alembic", "versions", f"{_REVISION}.py")
_CORE = os.path.join(_BACKEND_ROOT, "alembic", "versions", "20261006_ml_publications_core.py")
_CASES = load_fixture("listing_prices_cases.json")["cases"]


def _load(path: str, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _migration():
    return _load(_PATH, "installments_campaign_migration")


def _script_directory() -> ScriptDirectory:
    config = Config(os.path.join(_BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(_BACKEND_ROOT, "alembic"))
    return ScriptDirectory.from_config(config)


class TestMigrationGraph:
    def test_single_head_that_contains_this_revision(self) -> None:
        script = _script_directory()
        heads = script.get_heads()
        assert len(heads) == 1, heads
        chain = {r.revision for r in script.walk_revisions(base="base", head=heads[0])}
        assert _REVISION in chain

    def test_has_exactly_one_parent(self) -> None:
        assert isinstance(_script_directory().get_revision(_REVISION).down_revision, str)


class TestModelMirror:
    def test_the_model_declares_the_column_like_the_migration(self) -> None:
        from sqlalchemy import Text

        from app.models.ml_publications import MlItem

        column = MlItem.__table__.c.installments_campaign
        assert isinstance(column.type, Text) and column.nullable is True


@pytest.fixture
def store():
    """Throwaway schema holding the REAL `ml_items` of the core migration, before this one."""
    from tests.conftest import POSTGRES_TEST_URL, _postgres_reachable

    if not _postgres_reachable():
        pytest.skip(f"PostgreSQL not reachable at {POSTGRES_TEST_URL}")
    schema = f"inst_camp_t_{uuid.uuid4().hex[:8]}"
    admin = create_engine(POSTGRES_TEST_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f"CREATE SCHEMA {schema}"))
    eng = create_engine(POSTGRES_TEST_URL, connect_args={"options": f"-csearch_path={schema}"})
    core = _load(_CORE, "core_for_installments_campaign")
    with eng.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with ctx.begin_transaction(), Operations.context(ctx):
            core.upgrade()
    try:
        yield eng
    finally:
        eng.dispose()
        with admin.connect() as conn:
            conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        admin.dispose()


def _terms(*values) -> dict:
    return {"sale_terms": [{"id": "INSTALLMENTS_CAMPAIGN", "value_name": v} for v in values]}


def _insert(eng, item_id: str, raw) -> None:
    with eng.begin() as conn:
        conn.execute(
            text("INSERT INTO ml_items (item_id, raw) VALUES (:i, CAST(:r AS jsonb))"),
            {"i": item_id, "r": None if raw is None else json.dumps(raw)},
        )


def _run_upgrade(eng, module=None) -> None:
    module = module or _migration()
    with eng.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx), ctx.begin_transaction():
            module.upgrade()


def _columns(eng) -> dict:
    with eng.connect() as conn:
        return {
            row[0]: (row[1], row[2])
            for row in conn.exec_driver_sql(
                "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
                "WHERE table_name = 'ml_items' AND table_schema = current_schema()"
            )
        }


def _values(eng) -> dict:
    with eng.connect() as conn:
        return dict(conn.execute(text("SELECT item_id, installments_campaign FROM ml_items")).all())


@pytest.mark.postgres
class TestUpgrade:
    def test_adds_a_nullable_text_column_and_downgrade_drops_it(self, store) -> None:
        module = _migration()
        assert "installments_campaign" not in _columns(store)
        _run_upgrade(store, module)
        assert _columns(store)["installments_campaign"] == ("text", "YES")
        with store.connect() as conn:
            ctx = MigrationContext.configure(conn)
            with Operations.context(ctx), ctx.begin_transaction():
                module.downgrade()
        assert "installments_campaign" not in _columns(store)

    def test_backfills_the_campaign_of_every_row_that_has_one(self, store) -> None:
        _insert(store, "MLA1", _terms("9x_campaign"))
        _insert(store, "MLA2", {"sale_terms": []})
        _insert(store, "MLA3", {"title": "no sale terms at all"})
        _insert(store, "MLA4", None)  # state row never fetched: no raw
        _insert(store, "MLA5", _terms("3x_campaign", "12x_campaign"))  # the first result wins
        _insert(store, "MLA6", _terms(None))  # a null value is no campaign
        _insert(store, "MLA7", {"sale_terms": _terms("6x_campaign")["sale_terms"][0]})  # an object, not a list
        _run_upgrade(store)
        assert _values(store) == {
            "MLA1": "9x_campaign",
            "MLA2": None,
            "MLA3": None,
            "MLA4": None,
            "MLA5": "3x_campaign",
            "MLA6": None,
            "MLA7": "6x_campaign",
        }

    def test_the_batches_cover_every_row_whatever_their_size(self, store, monkeypatch) -> None:
        module = _migration()
        monkeypatch.setattr(module, "BATCH_SIZE", 3)
        for n in range(10):
            _insert(store, f"MLA{n:02d}", _terms("12x_campaign") if n % 2 == 0 else {"sale_terms": []})
        _run_upgrade(store, module)
        assert sorted(item for item, value in _values(store).items() if value == "12x_campaign") == [
            f"MLA{n:02d}" for n in range(0, 10, 2)
        ]

    def test_each_batch_commits_on_its_own(self, store, monkeypatch) -> None:
        """A failure in the last batch must not undo the first ones: the batches are not one transaction."""
        module = _migration()
        monkeypatch.setattr(module, "BATCH_SIZE", 2)
        for n in range(6):
            _insert(store, f"MLA{n}", _terms("3x_campaign"))
        real = module._update_batch
        calls = []

        def boom(bind, after, last):
            calls.append((after, last))
            if len(calls) == 3:
                raise RuntimeError("stop in the last batch")
            real(bind, after, last)

        monkeypatch.setattr(module, "_update_batch", boom)
        with pytest.raises(RuntimeError):
            _run_upgrade(store, module)
        done = [item for item, value in _values(store).items() if value == "3x_campaign"]
        assert sorted(done) == ["MLA0", "MLA1", "MLA2", "MLA3"]

    def test_rerunning_it_is_a_no_op(self, store) -> None:
        _insert(store, "MLA1", _terms("9x_campaign"))
        _run_upgrade(store)
        _run_upgrade(store)
        assert _values(store) == {"MLA1": "9x_campaign"}

    def test_an_empty_store_upgrades(self, store) -> None:
        _run_upgrade(store)
        assert _values(store) == {}


@pytest.mark.postgres
class TestBackfillEqualsTheMapper:
    """The backfill (SQL over `raw`) and the ingest (`map_item`) must agree on every captured body."""

    def test_the_sixteen_captured_items_and_every_captured_full_body(self, store) -> None:
        bodies = {c["item_id"]: {"sale_terms": c["sale_terms"], "tags": c["tags"]} for c in _CASES}
        for element in load_fixture(ITEM_SAMPLES)["elements"]:
            if isinstance(element.get("body"), dict):
                bodies[element["id"]] = copy.deepcopy(element["body"])
        for item_id, body in bodies.items():
            _insert(store, item_id, body)
        _run_upgrade(store)
        stored = _values(store)
        assert {item_id: map_item(body)["installments_campaign"] for item_id, body in bodies.items()} == stored
        assert any(stored.values()) and not all(stored.values())
