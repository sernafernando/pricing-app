"""Publicaciones ML presets S4: the layouts/presets tables and the `ml_publicaciones.presets_compartidos` permission
ship in one migration on the single alembic line. The upgrade creates both tables with their per-owner unique names,
grants the permission to ADMIN only, and the downgrade removes everything. The upgrade/downgrade run for real on a
throwaway Postgres schema holding the real permission tables."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from tests.unit.test_migration_ml_publicaciones_pausar_perm import _run, _script, pg_schema  # noqa: F401

_REVISION = "20261123_ml_publicaciones_presets"
CODIGO = "ml_publicaciones.presets_compartidos"
TABLES = ("ml_publicaciones_presets", "ml_publicaciones_layouts")


def test_the_revision_is_on_the_single_line() -> None:
    # One head (alembic did not fork) that descends from this revision; not
    # "this revision IS the head", so a later migration on top keeps it green.
    script = _script()
    assert script.get_revision(_REVISION).down_revision == "20261122_mcp_oauth"
    heads = script.get_heads()
    assert len(heads) == 1, f"alembic forked: {heads}"
    assert any(rev.revision == _REVISION for rev in script.walk_revisions("base", heads[0]))


def test_declares_the_catalog_row_next_to_the_other_ml_ops_permissions() -> None:
    module = _script().get_revision(_REVISION).module
    assert module.PERMISO["codigo"] == CODIGO
    assert module.PERMISO["categoria"] == "ml_ops"
    assert module.PERMISO["orden"] == 210  # 200-209 are taken by the other ml_ops permissions


def _base_tables(eng) -> None:
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
        conn.execute(text("INSERT INTO usuarios DEFAULT VALUES"))
        conn.execute(text("INSERT INTO usuarios DEFAULT VALUES"))


def _insert_preset(eng, usuario_id: int | None, nombre: str, vista: str = "publicacion") -> None:
    with eng.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO ml_publicaciones_presets (usuario_id, vista, nombre, payload) "
                "VALUES (:u, :v, :n, CAST('{}' AS jsonb))"
            ),
            {"u": usuario_id, "v": vista, "n": nombre},
        )


def test_upgrade_creates_the_tables_and_grants_admin_only_and_downgrade_removes_everything(pg_schema) -> None:  # noqa: F811
    eng = pg_schema
    module = _script().get_revision(_REVISION).module
    _base_tables(eng)

    _run(eng, module, "upgrade")

    with eng.connect() as conn:
        row = conn.execute(
            text("SELECT categoria, orden, es_critico FROM permisos WHERE codigo = :c"), {"c": CODIGO}
        ).one()
        assert tuple(row) == ("ml_ops", 210, False)
        granted = conn.execute(
            text(
                "SELECT r.codigo FROM roles_permisos_base b JOIN roles r ON r.id = b.rol_id "
                "JOIN permisos p ON p.id = b.permiso_id WHERE p.codigo = :c"
            ),
            {"c": CODIGO},
        ).all()
    assert [r[0] for r in granted] == ["ADMIN"]

    # Unique name per owner + view, case-insensitive; personal and shared names live apart.
    _insert_preset(eng, 1, "Mis activas")
    with pytest.raises(IntegrityError):
        _insert_preset(eng, 1, "MIS ACTIVAS")
    _insert_preset(eng, 2, "Mis activas")  # another owner
    _insert_preset(eng, 1, "Mis activas", vista="precios")  # another view
    _insert_preset(eng, None, "Mis activas")  # shared next to a personal one
    with pytest.raises(IntegrityError):
        _insert_preset(eng, None, "mis activas")

    # One layout per user and view; deleting its preset forgets it, deleting the user removes the user's rows.
    with eng.begin() as conn:
        preset_id = conn.execute(
            text("SELECT id FROM ml_publicaciones_presets WHERE usuario_id = 1 AND vista = 'publicacion'")
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO ml_publicaciones_layouts (usuario_id, vista, preset_activo_id) VALUES (1, 'publicacion', :p)"
            ),
            {"p": preset_id},
        )
    with pytest.raises(IntegrityError):
        with eng.begin() as conn:
            conn.execute(text("INSERT INTO ml_publicaciones_layouts (usuario_id, vista) VALUES (1, 'publicacion')"))
    with eng.begin() as conn:
        conn.execute(text("DELETE FROM ml_publicaciones_presets WHERE id = :p"), {"p": preset_id})
        assert conn.execute(text("SELECT preset_activo_id FROM ml_publicaciones_layouts")).scalar_one() is None
        conn.execute(text("DELETE FROM usuarios WHERE id = 1"))
        assert conn.execute(text("SELECT count(*) FROM ml_publicaciones_layouts")).scalar_one() == 0
        assert (
            conn.execute(text("SELECT count(*) FROM ml_publicaciones_presets WHERE usuario_id = 1")).scalar_one() == 0
        )

    with eng.begin() as conn:
        pid = conn.execute(text("SELECT id FROM permisos WHERE codigo = :c"), {"c": CODIGO}).scalar_one()
        conn.execute(text("INSERT INTO usuarios_permisos_override (usuario_id, permiso_id) VALUES (7, :p)"), {"p": pid})

    _run(eng, module, "downgrade")
    with eng.connect() as conn:
        for table in ("permisos", "roles_permisos_base", "usuarios_permisos_override"):
            assert conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() == 0, table
        for table in TABLES:
            assert conn.execute(text("SELECT to_regclass(:t)"), {"t": table}).scalar_one() is None, table
