"""Publicaciones ML T7: the copied-data columns of `productos_propios` ship in their own migration on the single alembic
line, nullable (existing rows mean "no source chosen"), and the downgrade drops them. Run on a throwaway Postgres
schema."""

# ruff: noqa: F811 -- the fixture is imported from the pausar migration test and used by name

from __future__ import annotations

from sqlalchemy import inspect, text

from tests.unit.test_migration_ml_publicaciones_pausar_perm import _run, _script, pg_schema  # noqa: F401

_REVISION = "20261128_productos_propios_fuente"
COPIED = {"fuente_mla", "titulo", "descripcion", "fotos", "atributos", "fuente_copiada_por", "fuente_copiada_at"}


def test_the_revision_is_on_the_single_line() -> None:
    script = _script()
    assert script.get_revision(_REVISION).down_revision == "20261127_productos_propios"
    heads = script.get_heads()
    assert len(heads) == 1, f"alembic forked: {heads}"
    assert any(rev.revision == _REVISION for rev in script.walk_revisions("base", heads[0]))


def test_upgrade_adds_nullable_columns_an_existing_row_keeps_and_downgrade_drops_them(pg_schema) -> None:
    eng = pg_schema
    module = _script().get_revision(_REVISION).module
    with eng.begin() as conn:
        conn.execute(text("CREATE TABLE productos_propios (item_id integer PRIMARY KEY, sku varchar(100))"))
        conn.execute(text("INSERT INTO productos_propios (item_id, sku) VALUES (70, 'MIO')"))

    _run(eng, module, "upgrade")

    columns = {column["name"]: column for column in inspect(eng).get_columns("productos_propios")}
    assert COPIED <= set(columns)
    assert all(columns[name]["nullable"] for name in COPIED)
    with eng.connect() as conn:
        assert conn.execute(text("SELECT sku, fuente_mla FROM productos_propios")).one() == ("MIO", None)

    _run(eng, module, "downgrade")

    assert not COPIED & {column["name"] for column in inspect(eng).get_columns("productos_propios")}
