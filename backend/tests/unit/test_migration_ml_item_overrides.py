"""Publicaciones ML T8: `ml_item_overrides` (a publication's data overridden locally) and the
`ml_publicaciones.editar_publicacion` permission ship in one migration on the single alembic line; the permission is
granted to ADMIN and the downgrade removes both. Run for real on a throwaway Postgres schema."""

# ruff: noqa: F811 -- the fixture is imported from the pausar migration test and used by name

from __future__ import annotations

from sqlalchemy import inspect, text

from tests.unit.test_migration_ml_publicaciones_pausar_perm import _run, _script, pg_schema  # noqa: F401
from tests.unit.test_migration_productos_propios import PERMISSION_TABLES_DDL

_REVISION = "20261129_ml_item_overrides"
CODIGO = "ml_publicaciones.editar_publicacion"
OVERRIDABLE = {"titulo", "descripcion", "fotos", "atributos"}


def test_the_revision_is_on_the_single_line() -> None:
    script = _script()
    assert script.get_revision(_REVISION).down_revision == "20261128_productos_propios_fuente"
    heads = script.get_heads()
    assert len(heads) == 1, f"alembic forked: {heads}"
    assert any(rev.revision == _REVISION for rev in script.walk_revisions("base", heads[0]))


def test_upgrade_creates_the_table_and_grants_admin_and_downgrade_removes_both(pg_schema) -> None:
    eng = pg_schema
    module = _script().get_revision(_REVISION).module
    with eng.begin() as conn:
        for statement in PERMISSION_TABLES_DDL:
            conn.execute(text(statement))

    _run(eng, module, "upgrade")

    columns = {column["name"]: column for column in inspect(eng).get_columns("ml_item_overrides")}
    assert set(columns) == {"item_id", *OVERRIDABLE, "updated_by", "updated_at"}
    assert all(columns[name]["nullable"] for name in OVERRIDABLE)  # NULL: the field follows ML
    assert inspect(eng).get_pk_constraint("ml_item_overrides")["constrained_columns"] == ["item_id"]
    assert inspect(eng).get_foreign_keys("ml_item_overrides") == []  # never blocks the store's sweeps
    with eng.connect() as conn:
        row = conn.execute(text("SELECT categoria, orden FROM permisos WHERE codigo = :c"), {"c": CODIGO}).one()
        assert tuple(row) == ("ml_ops", 208)
        granted = conn.execute(
            text(
                "SELECT r.codigo FROM roles_permisos_base b JOIN roles r ON r.id = b.rol_id "
                "JOIN permisos p ON p.id = b.permiso_id WHERE p.codigo = :c"
            ),
            {"c": CODIGO},
        ).all()
    assert [r[0] for r in granted] == ["ADMIN"]

    with eng.begin() as conn:
        pid = conn.execute(text("SELECT id FROM permisos WHERE codigo = :c"), {"c": CODIGO}).scalar_one()
        conn.execute(text("INSERT INTO usuarios_permisos_override (usuario_id, permiso_id) VALUES (7, :p)"), {"p": pid})

    _run(eng, module, "downgrade")

    assert not inspect(eng).has_table("ml_item_overrides")
    with eng.connect() as conn:
        for table in ("permisos", "roles_permisos_base", "usuarios_permisos_override"):
            assert conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() == 0, table
