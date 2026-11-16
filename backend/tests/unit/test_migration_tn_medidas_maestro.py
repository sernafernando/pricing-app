"""abm-productos T7 (delivery 5, L8 Q3): the TN publisher's stored measurements (`tn_publish_override`, one row per
EAN and field, in TN units) are copied once into the product master (`productos_propios`), found by the GBP `Código`
(`productos_erp.codigo`), in the master's units: weight kg -> `peso_g`; TN width = GBP large -> `largo_cm`; TN depth =
GBP wide -> `ancho_cm`; height -> `alto_cm`. A value the master already holds is kept, a value equal to GBP is not
stored (NULL = follow GBP), and a value that is not a positive number in range is skipped. The old table is left as it
is (a later PR drops it). Run for real on a throwaway Postgres schema."""

# ruff: noqa: F811 -- the fixture is imported from the pausar migration test and used by name

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import text

from app.models.producto_propio import ProductoPropio
from tests.unit.test_migration_ml_publicaciones_pausar_perm import _run, _script, pg_schema  # noqa: F401

_REVISION = "20261118_tn_medidas_maestro"

_DDL = (
    "CREATE TABLE productos_erp (item_id integer PRIMARY KEY, codigo varchar(100))",
    "CREATE TABLE tb_item (comp_id integer, item_id integer, item_weight numeric(18, 9), item_wide numeric(18, 9), "
    "item_large numeric(18, 9), item_higth numeric(18, 9), PRIMARY KEY (comp_id, item_id))",
    "CREATE TABLE tn_publish_override (id serial PRIMARY KEY, ean varchar(100) NOT NULL, campo varchar(50) NOT NULL, "
    "valor text NOT NULL, usuario_id integer NOT NULL, fecha_actualizacion timestamptz DEFAULT now())",
)


def test_the_revision_is_on_the_single_line() -> None:
    script = _script()
    assert script.get_revision(_REVISION).down_revision == "20261116_producto_tn_vinculos"
    heads = script.get_heads()
    assert len(heads) == 1, f"alembic forked: {heads}"
    assert any(rev.revision == _REVISION for rev in script.walk_revisions("base", heads[0]))


def _override(conn, ean: str, campo: str, valor: str, usuario_id: int = 5) -> None:
    conn.execute(
        text("INSERT INTO tn_publish_override (ean, campo, valor, usuario_id) VALUES (:e, :c, :v, :u)"),
        {"e": ean, "c": campo, "v": valor, "u": usuario_id},
    )


def _seed(eng) -> None:
    ProductoPropio.__table__.create(bind=eng)
    with eng.begin() as conn:
        for statement in _DDL:
            conn.execute(text(statement))
        conn.execute(
            text(
                "INSERT INTO productos_erp (item_id, codigo) VALUES (1, 'A'), (2, 'B'), (3, 'C'), (4, 'D'), (5, 'F'), (7, 'G'), (8, 'H')"
            )
        )
        conn.execute(text("INSERT INTO tb_item (comp_id, item_id, item_weight, item_large) VALUES (1, 3, 1500, 20)"))
        # B already has a weight set in the master (the ABM): it is kept.
        conn.execute(text("INSERT INTO productos_propios (item_id, peso_g, titulo) VALUES (2, 500, 'own')"))
        # G's master row already holds everything the copy brings: the row is not touched at all.
        conn.execute(
            text("INSERT INTO productos_propios (item_id, peso_g, updated_at) VALUES (7, 300, '2020-01-01T00:00:00Z')")
        )
        for campo, valor in (("weight", "1.2"), ("width", "13"), ("depth", "2.0"), ("height", "3")):
            _override(conn, "A", campo, valor, usuario_id=9)
        _override(conn, "B", "weight", "0.9")
        _override(conn, "B", "height", "10")
        _override(conn, "C", "weight", "1.5")  # = GBP 1500 g
        _override(conn, "C", "width", "20.000")  # = GBP large
        _override(conn, "D", "weight", "N/A")
        _override(conn, "D", "width", "-3")
        _override(conn, "D", "depth", "1e20")
        _override(conn, "D", "height", "0")
        _override(conn, "E", "weight", "2")  # no product with that code
        _override(conn, "F", "weight", "99999999")  # 99,999,999 kg: out of range
        _override(conn, "G", "weight", "1")
        # Rounded to the column scale (2 decimals) first: below 0.01 is skipped, never stored as 0.00.
        _override(conn, "H", "depth", "0.001")
        _override(conn, "H", "weight", "0.000001")  # 0.001 g
        _override(conn, "H", "height", "0.005")  # rounds up to 0.01: stored


def _master_rows(eng) -> list:
    with eng.connect() as conn:
        return [
            tuple(r)
            for r in conn.execute(
                text(
                    "SELECT item_id, peso_g, largo_cm, ancho_cm, alto_cm, updated_by, titulo, updated_at "
                    "FROM productos_propios ORDER BY item_id"
                )
            )
        ]


def test_upgrade_copies_the_measurements_into_the_master_in_its_units(pg_schema) -> None:
    eng = pg_schema
    module = _script().get_revision(_REVISION).module
    _seed(eng)

    _run(eng, module, "upgrade")

    with eng.connect() as conn:
        rows = {
            r.item_id: r
            for r in conn.execute(
                text(
                    "SELECT item_id, peso_g, largo_cm, ancho_cm, alto_cm, updated_by, titulo, updated_at FROM productos_propios"
                )
            )
        }
    assert set(rows) == {1, 2, 7, 8}
    a = rows[1]
    assert (a.peso_g, a.largo_cm, a.ancho_cm, a.alto_cm) == (Decimal("1200"), Decimal("13"), Decimal("2"), Decimal("3"))
    assert a.updated_by == 9
    b = rows[2]
    assert (b.peso_g, b.alto_cm, b.largo_cm, b.titulo) == (Decimal("500"), Decimal("10"), None, "own")
    g = rows[7]
    assert (g.peso_g, g.updated_at.year) == (Decimal("300"), 2020)
    h = rows[8]
    assert (h.peso_g, h.ancho_cm, h.alto_cm) == (None, None, Decimal("0.01"))

    _run(eng, module, "downgrade")

    with eng.connect() as conn:
        # The copy stays (the master owns it now) and the old table is untouched.
        assert conn.execute(text("SELECT count(*) FROM productos_propios")).scalar() == 4
        assert conn.execute(text("SELECT count(*) FROM tn_publish_override")).scalar() == 18


def test_upgrade_twice_changes_nothing(pg_schema) -> None:
    eng = pg_schema
    module = _script().get_revision(_REVISION).module
    _seed(eng)

    _run(eng, module, "upgrade")
    primera = _master_rows(eng)
    _run(eng, module, "upgrade")

    assert _master_rows(eng) == primera
