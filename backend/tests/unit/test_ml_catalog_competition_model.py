"""Model registration and schema-drift guards for `ml_catalog_competition`.

`alembic/env.py` builds `target_metadata` from `Base.metadata` after a
`from app.models import *`, so a model that is missing from
`app/models/__init__.py` exists in the database but NOT in the metadata.
The next `alembic revision --autogenerate` then emits a `drop_table` for
it. These tests pin the registration and the index/default declarations
so the model and the migration cannot drift apart silently.
"""

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


def test_no_server_default_uses_postgres_only_cast_syntax():
    """Registering the model puts it in `Base.metadata.create_all()`, which the
    suite runs against SQLite (tests/conftest.py) while production is Postgres.

    conftest remaps the *types* (JSONB -> JSON) via `_patch_pg_types_for_sqlite`,
    but a server_default is emitted verbatim into the CREATE TABLE regardless.
    So `server_default=text("'[]'::jsonb")` compiles to
    `DEFAULT '[]'::jsonb` on SQLite and dies with "unrecognized token: :",
    failing `create_all` and therefore EVERY test that uses the db fixture —
    not just this model's.

    Regression guard: that exact cast took 2438 tests down at once.
    """
    offenders = {
        col.name: str(col.server_default.arg)
        for col in MLCatalogCompetition.__table__.columns
        if col.server_default is not None and "::" in str(col.server_default.arg)
    }
    assert offenders == {}, (
        f"Postgres-only cast syntax in server_default(s): {offenders}. "
        "Keep model defaults dialect-neutral; the Postgres-specific DDL belongs "
        "in the migration, and alembic/env.py does not set compare_server_default."
    )


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


def test_competitors_defaults_to_an_empty_list():
    """The column is NOT NULL, so a default is required for rows written
    without an explicit competitors value (e.g. a not_catalog snapshot)."""
    default = MLCatalogCompetition.__table__.c.competitors.server_default
    assert default is not None, "competitors is NOT NULL and needs a server_default"
    assert "[]" in str(default.arg)
