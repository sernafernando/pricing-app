"""Postgres upgrade/downgrade for `ml_hay_mejores_audit`."""

# ruff: noqa: F811 -- pg_schema imported for the fixture name

from __future__ import annotations

from sqlalchemy import inspect, text

from tests.unit.test_migration_ml_publicaciones_pausar_perm import _run, _script, pg_schema  # noqa: F401

_REVISION = "20261117_ml_hay_mejores_audit"
_EXPECTED_COLUMNS = {"id", "item_id", "kind", "usuario_id", "payload", "created_at"}


def test_the_revision_is_on_the_single_line() -> None:
    script = _script()
    assert script.get_revision(_REVISION).down_revision == "20261117_ml_hay_mejores_criterios"
    heads = script.get_heads()
    assert len(heads) == 1, f"alembic forked: {heads}"
    assert any(rev.revision == _REVISION for rev in script.walk_revisions("base", heads[0]))


def test_upgrade_creates_table_and_downgrade_drops(pg_schema) -> None:
    eng = pg_schema
    module = _script().get_revision(_REVISION).module
    _run(eng, module, "upgrade")

    columns = {column["name"]: column for column in inspect(eng).get_columns("ml_hay_mejores_audit")}
    assert set(columns) == _EXPECTED_COLUMNS
    assert inspect(eng).get_pk_constraint("ml_hay_mejores_audit")["constrained_columns"] == ["id"]
    assert inspect(eng).get_foreign_keys("ml_hay_mejores_audit") == []
    indexes = {idx["name"] for idx in inspect(eng).get_indexes("ml_hay_mejores_audit")}
    assert "ix_ml_hay_mejores_audit_item_created" in indexes

    with eng.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO ml_hay_mejores_audit (item_id, kind, payload) "
                "VALUES ('MLA1', 'flag_transition', '{\"fingerprint\": \"C-1:900\"}'::jsonb)"
            )
        )
        row = conn.execute(
            text("SELECT item_id, kind, usuario_id, payload FROM ml_hay_mejores_audit WHERE item_id = 'MLA1'")
        ).one()
    assert row[0] == "MLA1"
    assert row[1] == "flag_transition"
    assert row[2] is None
    assert row[3]["fingerprint"] == "C-1:900"

    _run(eng, module, "downgrade")
    assert not inspect(eng).has_table("ml_hay_mejores_audit")
