"""Model registration and schema-drift guards for `ml_catalog_competition`.

`alembic/env.py` builds `target_metadata` from `Base.metadata` after a
`from app.models import *`, so a model that is missing from
`app/models/__init__.py` exists in the database but NOT in the metadata.
The next `alembic revision --autogenerate` then emits a `drop_table` for
it. These tests pin the registration and the index/default declarations
so the model and the migration cannot drift apart silently.
"""

from sqlalchemy import text

import app.models
from app.models.ml_catalog_competition import MLCatalogCompetition

TABLE_NAME = "ml_catalog_competition"


def test_model_is_reexported_by_app_models_package():
    """Guards against autogenerate emitting drop_table for this table.

    Asserted on the package attribute rather than on `Base.metadata`: any
    test that imports the model directly would populate the metadata and
    make a metadata-based assertion pass even while `app/models/__init__.py`
    is missing the import — which is exactly the broken state `env.py`'s
    `from app.models import *` would hit.
    """
    assert hasattr(app.models, "MLCatalogCompetition"), (
        "MLCatalogCompetition is not re-exported by app/models/__init__.py. "
        "alembic/env.py builds target_metadata from `from app.models import *`, "
        "so without it the table is absent from the metadata and the next "
        "`alembic revision --autogenerate` will emit drop_table for it."
    )


def test_model_declares_no_single_column_indexes():
    """The migration deliberately creates only the composite (mla, fecha_consulta DESC).

    `id` is already the primary key, and `mla` is the leading column of the
    composite index, so single-column indexes here would be dead weight that
    autogenerate would keep trying to create.
    """
    table = MLCatalogCompetition.__table__
    declared = {idx.name for idx in table.indexes}
    assert declared == set(), f"Model declares unexpected single-column indexes: {declared}"


def test_competitors_server_default_matches_migration_ddl():
    """Model and migration must render the same default, or autogenerate diffs forever."""
    rendered = str(MLCatalogCompetition.__table__.c.competitors.server_default.arg)
    assert rendered == "'[]'::jsonb", f"expected \"'[]'::jsonb\", got {rendered!r}"


def test_unique_constraint_on_mla_and_fecha():
    """Snapshot-per-fetch: one row per (mla, fecha_consulta), never updated in place."""
    table = MLCatalogCompetition.__table__
    uniques = {
        tuple(c.name for c in uc.columns)
        for uc in table.constraints
        if hasattr(uc, "columns") and uc.name and uc.name.startswith("uq_")
    }
    assert ("mla", "fecha_consulta") in uniques, f"missing unique on (mla, fecha_consulta); found {uniques}"


def test_timestamps_are_timezone_aware():
    """tz-naive timestamps have bitten this repo before; both columns must be TIMESTAMPTZ."""
    table = MLCatalogCompetition.__table__
    for col_name in ("fecha_consulta", "created_at"):
        assert table.c[col_name].type.timezone is True, f"{col_name} must be timezone-aware"


def test_text_default_is_valid_sql_expression():
    """Sanity: the server_default is a SQL expression, not a bare Python string."""
    default = MLCatalogCompetition.__table__.c.competitors.server_default.arg
    assert not isinstance(default, str), "server_default must be sa.text(...), not a plain string"
    assert isinstance(default, type(text("'[]'::jsonb")))
