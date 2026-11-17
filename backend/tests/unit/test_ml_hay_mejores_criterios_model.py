"""Schema-drift guards for `ml_hay_mejores_criterios` (SQLite create_all safety)."""

from app.models.ml_hay_mejores_criterios import MlHayMejoresCriterios


def test_no_server_default_uses_postgres_only_cast_syntax():
    """Same trap as ml_catalog_competition: `::jsonb` in server_default breaks
    Base.metadata.create_all() on SQLite and takes down every db-fixture test.
    Postgres-specific DDL belongs in the migration only.
    """
    offenders = {
        col.name: str(col.server_default.arg)
        for col in MlHayMejoresCriterios.__table__.columns
        if col.server_default is not None and "::" in str(col.server_default.arg)
    }
    assert offenders == {}, (
        f"Postgres-only cast syntax in server_default(s): {offenders}. "
        "Keep model defaults dialect-neutral; the Postgres-specific DDL belongs "
        "in the migration."
    )
