"""abm-productos delivery 2+3: `producto_categorias`, `producto_subcategorias` and `producto_marcas` seeded from GBP
with the same ids, plus `productos.editar_categorias` for ADMIN, in one migration on the single alembic line; the
downgrade removes everything. Run for real on a throwaway Postgres schema."""

# ruff: noqa: F811 -- the fixture is imported from the pausar migration test and used by name

from __future__ import annotations

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from app.models.producto_categoria import ProductoCategoria, ProductoSubcategoria
from app.models.producto_marca import ProductoMarca
from app.services.producto_categorias import SEED_SQL
from tests.unit.test_migration_ml_publicaciones_pausar_perm import _run, _script, pg_schema  # noqa: F401
from tests.unit.test_migration_productos_propios import PERMISSION_TABLES_DDL

_REVISION = "20261117_producto_categorias_marcas"
CODIGO = "productos.editar_categorias"
GBP_DDL = (
    "CREATE TABLE tb_category (comp_id int, cat_id int, cat_desc varchar(255), PRIMARY KEY (comp_id, cat_id))",
    "CREATE TABLE tb_subcategory (comp_id int, cat_id int, subcat_id int, subcat_desc varchar(255), "
    "PRIMARY KEY (comp_id, cat_id, subcat_id))",
    "CREATE TABLE tb_brand (comp_id int, brand_id int, bra_id int, brand_desc varchar(255), "
    "PRIMARY KEY (comp_id, brand_id))",
    "INSERT INTO tb_category VALUES (1, 46, 'CONECTIVIDAD'), (1, 47, 'NOTEBOOKS')",
    "INSERT INTO tb_subcategory VALUES (1, 46, 300, 'ROUTERS'), (1, 46, 301, 'SWITCHES')",
    "INSERT INTO tb_brand VALUES (1, 10, NULL, 'TP-LINK')",
)


def test_the_revision_is_on_the_single_line() -> None:
    script = _script()
    assert script.get_revision(_REVISION).down_revision == "20261116_producto_specs"
    heads = script.get_heads()
    assert len(heads) == 1, f"alembic forked: {heads}"
    assert any(rev.revision == _REVISION for rev in script.walk_revisions("base", heads[0]))


def test_the_migration_matches_the_models_and_the_service_seed() -> None:
    module = _script().get_revision(_REVISION).module
    assert module.SEED_SQL == SEED_SQL
    common = {"id", "nombre", "activa", "propia", "updated_by", "updated_at"}
    assert {c.name for c in ProductoCategoria.__table__.columns} == common | {"tn_category_id"}
    assert {c.name for c in ProductoSubcategoria.__table__.columns} == common | {"tn_category_id", "categoria_id"}
    assert {c.name for c in ProductoMarca.__table__.columns} == common


def test_upgrade_creates_seeds_and_grants_admin_and_downgrade_removes_all(pg_schema) -> None:
    eng = pg_schema
    module = _script().get_revision(_REVISION).module
    with eng.begin() as conn:
        for statement in (*PERMISSION_TABLES_DDL, *GBP_DDL):
            conn.execute(text(statement))

    _run(eng, module, "upgrade")

    insp = inspect(eng)
    assert [fk["referred_table"] for fk in insp.get_foreign_keys("producto_subcategorias")] == ["producto_categorias"]
    assert ("categoria_id",) in {tuple(ix["column_names"]) for ix in insp.get_indexes("producto_subcategorias")}
    with eng.connect() as conn:
        cats = conn.execute(text("SELECT id, nombre, activa, propia FROM producto_categorias ORDER BY id")).all()
        assert [tuple(r) for r in cats] == [(46, None, True, False), (47, None, True, False)]
        subs = conn.execute(text("SELECT id, categoria_id FROM producto_subcategorias ORDER BY id")).all()
        assert [tuple(r) for r in subs] == [(300, 46), (301, 46)]
        assert conn.execute(text("SELECT id FROM producto_marcas")).scalars().all() == [10]
        row = conn.execute(text("SELECT categoria, orden FROM permisos WHERE codigo = :c"), {"c": CODIGO}).one()
        assert tuple(row) == ("productos", 86)
        granted = conn.execute(
            text(
                "SELECT r.codigo FROM roles_permisos_base b JOIN roles r ON r.id = b.rol_id "
                "JOIN permisos p ON p.id = b.permiso_id WHERE p.codigo = :c"
            ),
            {"c": CODIGO},
        ).all()
    assert [r[0] for r in granted] == ["ADMIN"]
    with pytest.raises(IntegrityError), eng.begin() as conn:
        conn.execute(text("INSERT INTO producto_subcategorias (id, categoria_id) VALUES (999, 12345)"))

    _run(eng, module, "downgrade")

    insp = inspect(eng)
    for table in ("producto_categorias", "producto_subcategorias", "producto_marcas"):
        assert not insp.has_table(table)
    with eng.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM permisos")).scalar_one() == 0
