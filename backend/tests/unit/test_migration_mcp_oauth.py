"""MCP OAuth tables + `mcp.conectar` (S4, S9): on the single alembic line, ADMIN only, clean downgrade."""

from __future__ import annotations

from sqlalchemy import inspect, text

from tests.unit.test_migration_ml_publicaciones_pausar_perm import _run, _script, pg_schema  # noqa: F401

_REVISION = "20261122_mcp_oauth"
CODIGO = "mcp.conectar"
TABLES = {"mcp_connections", "mcp_oauth_requests", "mcp_tokens", "mcp_tool_calls"}


def test_the_revision_is_on_the_single_line() -> None:
    script = _script()
    assert script.get_revision(_REVISION).down_revision == "20261121_ml_publicaciones_auditoria_stock_perm"
    heads = script.get_heads()
    assert len(heads) == 1, f"alembic forked: {heads}"
    assert any(rev.revision == _REVISION for rev in script.walk_revisions("base", heads[0]))


def test_upgrade_creates_tables_grants_admin_only_and_downgrade_removes_everything(pg_schema) -> None:  # noqa: F811
    eng = pg_schema
    module = _script().get_revision(_REVISION).module
    with eng.begin() as conn:
        conn.execute(text("CREATE TABLE usuarios (id serial PRIMARY KEY)"))
        conn.execute(text("CREATE TABLE roles (id serial PRIMARY KEY, codigo varchar(50) UNIQUE NOT NULL)"))
        conn.execute(
            text(
                "CREATE TABLE permisos (id serial PRIMARY KEY, codigo varchar(100) UNIQUE NOT NULL, "
                "nombre varchar(255) NOT NULL, descripcion text, categoria varchar(50) NOT NULL, "
                "orden integer, es_critico boolean, created_at timestamptz DEFAULT now())"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE roles_permisos_base (id serial PRIMARY KEY, rol_id integer NOT NULL, "
                "permiso_id integer NOT NULL, UNIQUE (rol_id, permiso_id))"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE usuarios_permisos_override (id serial PRIMARY KEY, usuario_id integer NOT NULL, "
                "permiso_id integer NOT NULL)"
            )
        )
        conn.execute(text("INSERT INTO roles (codigo) VALUES ('ADMIN'), ('GERENTE'), ('VENTAS')"))

    _run(eng, module, "upgrade")
    assert TABLES <= set(inspect(eng).get_table_names())
    with eng.connect() as conn:
        row = conn.execute(text("SELECT categoria, es_critico FROM permisos WHERE codigo = :c"), {"c": CODIGO}).one()
        assert tuple(row) == ("administracion", True)  # it hands the user's data to an outside app
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
    assert not (TABLES & set(inspect(eng).get_table_names()))
    with eng.connect() as conn:
        for table in ("permisos", "roles_permisos_base", "usuarios_permisos_override"):
            assert conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() == 0, table
