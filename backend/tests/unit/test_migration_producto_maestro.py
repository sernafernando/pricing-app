"""abm-productos T4 (delivery 1): the product master columns on `productos_propios` and the
`productos.editar_maestro` permission ship in one migration on the single alembic line; every new column is nullable
(NULL = follow GBP), the permission goes to ADMIN, and the downgrade removes both. Run for real on a throwaway
Postgres schema."""

# ruff: noqa: F811 -- the fixture is imported from the pausar migration test and used by name

from __future__ import annotations

from sqlalchemy import inspect, text

from app.models.producto_propio import ProductoPropio
from tests.unit.test_migration_ml_publicaciones_pausar_perm import _run, _script, pg_schema  # noqa: F401
from tests.unit.test_migration_productos_propios import PERMISSION_TABLES_DDL

_REVISION = "20261117_producto_maestro"
CODIGO = "productos.editar_maestro"


def test_the_revision_is_on_the_single_line() -> None:
    script = _script()
    assert script.get_revision(_REVISION).down_revision == "20261117_producto_categorias_marcas"
    heads = script.get_heads()
    assert len(heads) == 1, f"alembic forked: {heads}"
    assert any(rev.revision == _REVISION for rev in script.walk_revisions("base", heads[0]))


def test_the_migrated_columns_are_the_model_columns() -> None:
    module = _script().get_revision(_REVISION).module
    assert {name for name, _ in module.COLUMNS} <= {c.name for c in ProductoPropio.__table__.columns}


def test_upgrade_adds_nullable_columns_and_grants_admin_and_downgrade_removes_both(pg_schema) -> None:
    eng = pg_schema
    module = _script().get_revision(_REVISION).module
    with eng.begin() as conn:
        for statement in PERMISSION_TABLES_DDL:
            conn.execute(text(statement))
        conn.execute(text("CREATE TABLE productos_propios (item_id integer PRIMARY KEY, ean varchar(100))"))
        conn.execute(text("INSERT INTO productos_propios (item_id, ean) VALUES (7, '779')"))

    _run(eng, module, "upgrade")

    columns = {c["name"]: c for c in inspect(eng).get_columns("productos_propios")}
    for name, _ in module.COLUMNS:
        assert columns[name]["nullable"] is True, name
    with eng.connect() as conn:
        row = conn.execute(text("SELECT ean, nombre, peso_g FROM productos_propios WHERE item_id = 7")).one()
        assert tuple(row) == ("779", None, None)  # existing rows keep following GBP
        perm = conn.execute(text("SELECT categoria FROM permisos WHERE codigo = :c"), {"c": CODIGO}).one()
        assert perm[0] == "productos"
        granted = conn.execute(
            text(
                "SELECT r.codigo FROM roles_permisos_base b JOIN roles r ON r.id = b.rol_id "
                "JOIN permisos p ON p.id = b.permiso_id WHERE p.codigo = :c"
            ),
            {"c": CODIGO},
        ).all()
    assert [r[0] for r in granted] == ["ADMIN"]

    _run(eng, module, "downgrade")

    columns = {c["name"] for c in inspect(eng).get_columns("productos_propios")}
    assert columns == {"item_id", "ean"}
    with eng.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM permisos")).scalar_one() == 0
