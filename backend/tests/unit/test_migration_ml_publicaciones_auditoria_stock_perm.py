"""Auditoría de stock S8: the `ml_publicaciones.ver_auditoria_stock` permission ships in its own migration on
the single alembic line, is granted to ADMIN only, and downgrades cleanly. The upgrade/downgrade run for real on a
throwaway Postgres schema holding the real permission tables."""

from __future__ import annotations

from sqlalchemy import text

from tests.unit.test_migration_ml_publicaciones_pausar_perm import _run, _script, pg_schema  # noqa: F401

_REVISION = "20261121_ml_publicaciones_auditoria_stock_perm"
CODIGO = "ml_publicaciones.ver_auditoria_stock"


def test_the_revision_is_on_the_single_line() -> None:
    # One head (alembic did not fork) that descends from this revision; not
    # "this revision IS the head", so a later migration on top keeps it green.
    script = _script()
    assert script.get_revision(_REVISION).down_revision == "20261120_tactical_sell_in_usd"
    heads = script.get_heads()
    assert len(heads) == 1, f"alembic forked: {heads}"
    assert any(rev.revision == _REVISION for rev in script.walk_revisions("base", heads[0]))


def test_declares_the_catalog_row_next_to_the_other_ml_ops_permissions() -> None:
    module = _script().get_revision(_REVISION).module
    assert module.PERMISO["codigo"] == CODIGO
    assert module.PERMISO["categoria"] == "ml_ops"
    assert module.PERMISO["orden"] == 209  # 200-208 are taken by the other ml_ops permissions


def test_upgrade_grants_admin_only_and_is_idempotent_and_downgrade_removes_everything(pg_schema) -> None:  # noqa: F811
    eng = pg_schema
    module = _script().get_revision(_REVISION).module
    with eng.begin() as conn:
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
    _run(eng, module, "upgrade")  # ON CONFLICT DO NOTHING: re-running changes nothing

    with eng.connect() as conn:
        row = conn.execute(
            text("SELECT categoria, orden, es_critico FROM permisos WHERE codigo = :c"), {"c": CODIGO}
        ).one()
        assert tuple(row) == ("ml_ops", 209, False)  # read-only view: not critical
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
    with eng.connect() as conn:
        for table in ("permisos", "roles_permisos_base", "usuarios_permisos_override"):
            assert conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() == 0, table
