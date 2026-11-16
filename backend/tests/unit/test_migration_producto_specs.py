"""abm-specs-productos T1: `producto_specs`, `producto_spec_valores` (seeded) and the `productos.editar_specs`
permission ship in one migration on the single alembic line; the permission goes to ADMIN, every filterable column is
indexed, and the downgrade removes everything. Run for real on a throwaway Postgres schema."""

# ruff: noqa: F811 -- the fixture is imported from the pausar migration test and used by name

from __future__ import annotations

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from app.models.producto_spec import INDEXED_COLUMNS, ProductoSpec
from app.services.producto_specs.campos import VALORES_INICIALES
from tests.unit.test_migration_ml_publicaciones_pausar_perm import _run, _script, pg_schema  # noqa: F401
from tests.unit.test_migration_productos_propios import PERMISSION_TABLES_DDL

_REVISION = "20261116_producto_specs"
CODIGO = "productos.editar_specs"


def test_the_revision_is_on_the_single_line() -> None:
    script = _script()
    assert script.get_revision(_REVISION).down_revision == "20261114_hay_mejores_excluido"
    heads = script.get_heads()
    assert len(heads) == 1, f"alembic forked: {heads}"
    assert any(rev.revision == _REVISION for rev in script.walk_revisions("base", heads[0]))


def test_the_migration_matches_the_model_and_the_seeded_lists() -> None:
    module = _script().get_revision(_REVISION).module
    migrated = {"item_id", "tipo", "origenes", "fuente_mla", "precargado_at", "updated_by", "updated_at"}
    migrated |= {name for name, _ in module.NUMERIC_COLUMNS} | set(module.CATEGORICAL_COLUMNS)
    assert migrated == {c.name for c in ProductoSpec.__table__.columns}
    assert set(module.INDEXED) == set(INDEXED_COLUMNS)
    assert module.SEED == VALORES_INICIALES


def test_upgrade_creates_the_tables_seeds_and_grants_admin_and_downgrade_removes_all(pg_schema) -> None:
    eng = pg_schema
    module = _script().get_revision(_REVISION).module
    with eng.begin() as conn:
        for statement in PERMISSION_TABLES_DDL:
            conn.execute(text(statement))

    _run(eng, module, "upgrade")

    insp = inspect(eng)
    assert insp.get_pk_constraint("producto_specs")["constrained_columns"] == ["item_id"]
    assert insp.get_foreign_keys("producto_specs") == []  # never blocks the ERP sync
    indexed = {tuple(ix["column_names"]) for ix in insp.get_indexes("producto_specs")}
    assert {(c,) for c in INDEXED_COLUMNS} <= indexed
    with eng.connect() as conn:
        seeded = conn.execute(text("SELECT count(*) FROM producto_spec_valores")).scalar_one()
        assert seeded == sum(len(v) for v in VALORES_INICIALES.values())
        assert (
            conn.execute(
                text("SELECT valor FROM producto_spec_valores WHERE campo = 'disco_tipo' AND clave = 'híbrido'")
            ).scalar_one()
            == "Híbrido"
        )
        row = conn.execute(text("SELECT categoria, orden FROM permisos WHERE codigo = :c"), {"c": CODIGO}).one()
        assert tuple(row) == ("productos", 85)
        granted = conn.execute(
            text(
                "SELECT r.codigo FROM roles_permisos_base b JOIN roles r ON r.id = b.rol_id "
                "JOIN permisos p ON p.id = b.permiso_id WHERE p.codigo = :c"
            ),
            {"c": CODIGO},
        ).all()
    assert [r[0] for r in granted] == ["ADMIN"]
    with pytest.raises(IntegrityError, match="ck_producto_specs_tipo"), eng.begin() as conn:
        conn.execute(text("INSERT INTO producto_specs (item_id, tipo) VALUES (1, 'tablet')"))

    _run(eng, module, "downgrade")

    insp = inspect(eng)
    assert not insp.has_table("producto_specs") and not insp.has_table("producto_spec_valores")
    with eng.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM permisos")).scalar_one() == 0
