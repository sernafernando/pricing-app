"""Postgres upgrade/downgrade for `ml_hay_mejores_criterios`."""

# ruff: noqa: F811 -- pg_schema imported for the fixture name

from __future__ import annotations

from sqlalchemy import inspect, text

from tests.unit.test_migration_ml_publicaciones_pausar_perm import _run, _script, pg_schema  # noqa: F401

_REVISION = "20261117_ml_hay_mejores_criterios"
_EXPECTED_COLUMNS = {
    "item_id",
    "c1_activo",
    "c1_markup_min",
    "c1_markup_max",
    "c2_activo",
    "c2_solo_markup_positivo",
    "auto_aplicacion",
    "sellers_excluidos",
    "updated_by",
    "updated_at",
}


def test_the_revision_is_on_the_single_line() -> None:
    script = _script()
    assert script.get_revision(_REVISION).down_revision == "20261123_ml_publicaciones_presets"
    heads = script.get_heads()
    assert len(heads) == 1, f"alembic forked: {heads}"
    assert any(rev.revision == _REVISION for rev in script.walk_revisions("base", heads[0]))


def test_upgrade_creates_table_defaults_and_downgrade_drops(pg_schema) -> None:
    eng = pg_schema
    module = _script().get_revision(_REVISION).module
    _run(eng, module, "upgrade")

    columns = {column["name"]: column for column in inspect(eng).get_columns("ml_hay_mejores_criterios")}
    assert set(columns) == _EXPECTED_COLUMNS
    assert inspect(eng).get_pk_constraint("ml_hay_mejores_criterios")["constrained_columns"] == ["item_id"]
    assert inspect(eng).get_foreign_keys("ml_hay_mejores_criterios") == []

    with eng.begin() as conn:
        conn.execute(text("INSERT INTO ml_hay_mejores_criterios (item_id) VALUES ('MLA1')"))
        row = conn.execute(
            text(
                "SELECT c1_activo, c2_solo_markup_positivo, auto_aplicacion, sellers_excluidos "
                "FROM ml_hay_mejores_criterios WHERE item_id = 'MLA1'"
            )
        ).one()
    assert tuple(row[:3]) == (False, True, False)
    assert row[3] == []

    _run(eng, module, "downgrade")
    assert not inspect(eng).has_table("ml_hay_mejores_criterios")
