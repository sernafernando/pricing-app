"""Publicaciones ML T6: `productos_propios` (the manual SKU and EAN of an ERP product) and the
`ml_publicaciones.editar_producto` permission ship in one migration on the single alembic line; the permission is
granted to ADMIN and the downgrade removes both. Run for real on a throwaway Postgres schema."""

# ruff: noqa: F811 -- the fixture is imported from the pausar migration test and used by name

from __future__ import annotations

from sqlalchemy import inspect, text

from tests.unit.test_migration_ml_publicaciones_pausar_perm import _run, _script, pg_schema  # noqa: F401

_REVISION = "20261127_productos_propios"
CODIGO = "ml_publicaciones.editar_producto"

PERMISSION_TABLES_DDL = (
    "CREATE TABLE roles (id serial PRIMARY KEY, codigo varchar(50) UNIQUE NOT NULL)",
    "CREATE TABLE permisos (id serial PRIMARY KEY, codigo varchar(100) UNIQUE NOT NULL, nombre varchar(255) NOT NULL, "
    "descripcion text, categoria varchar(50) NOT NULL, orden integer, es_critico boolean, "
    "created_at timestamptz DEFAULT now())",
    "CREATE TABLE roles_permisos_base (id serial PRIMARY KEY, rol_id integer NOT NULL, permiso_id integer NOT NULL, "
    "UNIQUE (rol_id, permiso_id))",
    "CREATE TABLE usuarios_permisos_override (id serial PRIMARY KEY, usuario_id integer NOT NULL, "
    "permiso_id integer NOT NULL)",
    "INSERT INTO roles (codigo) VALUES ('ADMIN'), ('GERENTE'), ('VENTAS')",
)


def test_the_revision_is_on_the_single_line() -> None:
    script = _script()
    assert script.get_revision(_REVISION).down_revision == "20261126_ml_publicaciones_pausar_perm"
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

    columns = {column["name"]: column for column in inspect(eng).get_columns("productos_propios")}
    assert set(columns) == {"item_id", "sku", "ean", "updated_by", "updated_at"}
    assert columns["sku"]["nullable"] and columns["ean"]["nullable"]
    assert inspect(eng).get_pk_constraint("productos_propios")["constrained_columns"] == ["item_id"]
    assert inspect(eng).get_foreign_keys("productos_propios") == []  # never blocks the ERP sync
    with eng.connect() as conn:
        row = conn.execute(text("SELECT categoria, orden FROM permisos WHERE codigo = :c"), {"c": CODIGO}).one()
        assert tuple(row) == ("ml_ops", 207)
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

    assert not inspect(eng).has_table("productos_propios")
    with eng.connect() as conn:
        for table in ("permisos", "roles_permisos_base", "usuarios_permisos_override"):
            assert conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() == 0, table
