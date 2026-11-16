"""abm-productos T6: `producto_tn_vinculos` (links set by hand, one per product, a TN product linked by hand to one
product at most) and `tienda_nube_producto_textos` (TN name and description, one row per TN product) ship in one
migration on the single alembic line, with `productos.editar_maestro` for ADMIN. Run for real on a throwaway Postgres
schema."""

# ruff: noqa: F811 -- the fixture is imported from the pausar migration test and used by name

from __future__ import annotations

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from app.models.producto_tn_vinculo import ProductoTnVinculo
from app.models.tienda_nube_producto_texto import TiendaNubeProductoTexto
from tests.unit.test_migration_ml_publicaciones_pausar_perm import _run, _script, pg_schema  # noqa: F401
from tests.unit.test_migration_productos_propios import PERMISSION_TABLES_DDL

_REVISION = "20261116_producto_tn_vinculos"
CODIGO = "productos.editar_maestro"


def test_the_revision_is_on_the_single_line() -> None:
    script = _script()
    assert script.get_revision(_REVISION).down_revision == "20261117_producto_maestro"
    heads = script.get_heads()
    assert len(heads) == 1, f"alembic forked: {heads}"
    assert any(rev.revision == _REVISION for rev in script.walk_revisions("base", heads[0]))


def test_upgrade_creates_both_tables_and_grants_admin_and_downgrade_drops_the_tables(pg_schema) -> None:
    eng = pg_schema
    module = _script().get_revision(_REVISION).module
    with eng.begin() as conn:
        for statement in PERMISSION_TABLES_DDL:
            conn.execute(text(statement))
        # The product master migration (T4) may seed the same permission first: the seed must not fail on it.
        conn.execute(
            text("INSERT INTO permisos (codigo, nombre, categoria) VALUES (:c, 'Editar maestro', 'productos')"),
            {"c": CODIGO},
        )

    _run(eng, module, "upgrade")

    insp = inspect(eng)
    assert {c["name"] for c in insp.get_columns("producto_tn_vinculos")} == {
        c.name for c in ProductoTnVinculo.__table__.columns
    }
    assert {c["name"] for c in insp.get_columns("tienda_nube_producto_textos")} == {
        c.name for c in TiendaNubeProductoTexto.__table__.columns
    }
    assert insp.get_pk_constraint("producto_tn_vinculos")["constrained_columns"] == ["item_id"]
    assert insp.get_pk_constraint("tienda_nube_producto_textos")["constrained_columns"] == ["product_id"]
    assert insp.get_foreign_keys("producto_tn_vinculos") == []  # never blocks the ERP or TN sync
    with eng.begin() as conn:
        conn.execute(text("INSERT INTO producto_tn_vinculos (item_id, tn_product_id) VALUES (1, NULL), (2, NULL)"))
        conn.execute(text("INSERT INTO producto_tn_vinculos (item_id, tn_product_id) VALUES (3, 77)"))
    with pytest.raises(IntegrityError, match="uq_producto_tn_vinculos_tn_product_id"), eng.begin() as conn:
        conn.execute(text("INSERT INTO producto_tn_vinculos (item_id, tn_product_id) VALUES (4, 77)"))
    with eng.connect() as conn:
        granted = conn.execute(
            text(
                "SELECT r.codigo FROM roles_permisos_base b JOIN roles r ON r.id = b.rol_id "
                "JOIN permisos p ON p.id = b.permiso_id WHERE p.codigo = :c"
            ),
            {"c": CODIGO},
        ).all()
    assert [r[0] for r in granted] == ["ADMIN"]

    _run(eng, module, "downgrade")

    insp = inspect(eng)
    assert not insp.has_table("producto_tn_vinculos") and not insp.has_table("tienda_nube_producto_textos")
