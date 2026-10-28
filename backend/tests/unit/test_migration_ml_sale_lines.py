"""The `ml_sale_lines` migration agrees with the model, on a single Alembic head."""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from app.models.ml_sale_line import MlSaleLine

_REVISION = "20261018_ml_sale_lines"


def _script() -> ScriptDirectory:
    backend = Path(__file__).resolve().parents[2]
    config = Config(str(backend / "alembic.ini"))
    config.set_main_option("script_location", str(backend / "alembic"))
    return ScriptDirectory.from_config(config)


def test_the_migration_is_the_only_head() -> None:
    script = _script()
    heads = script.get_heads()
    assert len(heads) == 1, f"alembic forked: {heads}"
    assert any(rev.revision == _REVISION for rev in script.walk_revisions("base", heads[0]))


def test_the_migration_creates_the_columns_and_indexes_of_the_model() -> None:
    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    module = _script().get_revision(_REVISION).module
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            module.upgrade()
        inspector = sa.inspect(conn)
        columns = {c["name"] for c in inspector.get_columns("ml_sale_lines")}
        indexes = {ix["name"]: ix["column_names"] for ix in inspector.get_indexes("ml_sale_lines")}

    table = MlSaleLine.__table__
    # The TP-Link shares are added later by 20261027_tp_metrics_columns (checked
    # by test_migration_tp_metrics_columns.py), and `tg_known` by
    # 20261208_ml_sale_lines_tg_unknown (test_sale_lines_tg_known_migration.py),
    # not by this migration.
    added_later = {"tg_tp", "mtg_tp", "mcosto_tp", "tg_known"}
    assert columns == {c.name for c in table.columns} - added_later
    assert indexes == {ix.name: [c.name for c in ix.columns] for ix in table.indexes}
