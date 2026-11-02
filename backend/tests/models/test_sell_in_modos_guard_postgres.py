"""No way around "only a manual mode row carries a negative consumption" nor around append-only modes, on the migrated
schema (#1996 verification): updates, upserts, COPY, DELETE and TRUNCATE are all refused with the data unchanged."""

from __future__ import annotations

import io

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from tests.models.test_sell_in_schema_postgres import (  # noqa: F401
    _INSERT_CONSUMO_MODO,
    _INSERT_ITEM,
    _INSERT_MODO,
    _MANUAL,
    _modo,
    _new_compra,
    _rejects,
    engine,
)

pytestmark = pytest.mark.postgres


def _mundo(engine):  # noqa: F811
    with engine.begin() as conn:
        manual = conn.execute(text(_INSERT_MODO), _modo(**_MANUAL)).scalar_one()
        ponderado = conn.execute(text(_INSERT_MODO), _modo()).scalar_one()
        otro = conn.execute(text(_INSERT_MODO.replace("VALUES (4512,", "VALUES (4513,")), _modo(**_MANUAL)).scalar_one()
        conn.execute(text(_INSERT_CONSUMO_MODO), {"line": None, "modo": manual, "ref": 1, "descuento": "-2000"})
        compra = _new_compra(conn)
        line = conn.execute(
            text(_INSERT_ITEM), {"compra": compra, "item": 4512, "cantidad": 10, "costo": "25000", "monto": "250000.00"}
        ).scalar_one()
        conn.execute(text(_INSERT_CONSUMO_MODO), {"line": line, "modo": None, "ref": 2, "descuento": "100"})
    return manual, ponderado, otro, line


def _foto(engine):  # noqa: F811
    with engine.connect() as conn:
        return (
            conn.execute(text("SELECT * FROM sell_in_consumos ORDER BY id")).all(),
            conn.execute(text("SELECT * FROM sell_in_modos_producto ORDER BY id")).all(),
        )


def test_only_the_two_expected_user_triggers_guard_the_tables(engine) -> None:  # noqa: F811
    with engine.connect() as conn:
        filas = conn.execute(
            text(
                "SELECT c.relname, t.tgname, t.tgenabled FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
                "WHERE NOT t.tgisinternal AND c.relnamespace = current_schema()::regnamespace "
                "AND c.relname IN ('sell_in_consumos', 'sell_in_modos_producto') ORDER BY 1, 2"
            )
        ).all()
    assert [tuple(f) for f in filas] == [
        ("sell_in_consumos", "trg_sell_in_consumos_modo_manual", "O"),
        ("sell_in_modos_producto", "trg_sell_in_modos_producto_append_only", "O"),
        ("sell_in_modos_producto", "trg_sell_in_modos_producto_no_truncate", "O"),
    ]


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE sell_in_consumos SET modo_id = :ponderado WHERE venta_ref = 1",  # non-manual row
        "UPDATE sell_in_consumos SET modo_id = :otro WHERE venta_ref = 1",  # another product's manual row
        "UPDATE sell_in_consumos SET item_id = 4513 WHERE venta_ref = 1",  # moved away from its block
        "UPDATE sell_in_consumos SET modo_id = NULL WHERE venta_ref = 1",  # no source, and negative
        "UPDATE sell_in_consumos SET modo_id = NULL, compra_item_id = :line WHERE venta_ref = 1",  # negative on a line
        "UPDATE sell_in_consumos SET compra_item_id = NULL, modo_id = :ponderado, descuento_ars = -1 "
        "WHERE venta_ref = 2",  # line row onto a non-manual mode
        "UPDATE sell_in_consumos SET descuento_ars = -1 WHERE venta_ref = 2",  # line row goes negative
        "UPDATE sell_in_modos_producto SET modo = 'ponderado', cantidad = NULL, costo_unit = NULL, "
        "costo_base_unit = NULL WHERE id = :manual",
        "UPDATE sell_in_modos_producto SET item_id = 4513 WHERE id = :manual",
        "UPDATE sell_in_modos_producto SET id = 999 WHERE id = :manual",
        "UPDATE sell_in_modos_producto SET desde = desde WHERE id = :manual",  # even a no-op
        "DELETE FROM sell_in_modos_producto WHERE id = :manual",
        "DELETE FROM sell_in_modos_producto WHERE id = :ponderado",
        "INSERT INTO sell_in_consumos (modo_id, canal, venta_ref, item_id, fecha_venta, unidades, descuento_ars) "
        "SELECT :ponderado, 'ml', 50, 4512, DATE '2026-11-03', 1, -5",  # INSERT .. SELECT
    ],
)
def test_refused_and_nothing_changes(engine, sql) -> None:  # noqa: F811
    manual, ponderado, otro, line = _mundo(engine)
    antes = _foto(engine)
    params = {"manual": manual, "ponderado": ponderado, "otro": otro, "line": line}
    params = {k: v for k, v in params.items() if f":{k}" in sql}
    _rejects(engine, sql, params)
    assert _foto(engine) == antes


def test_upsert_cannot_move_a_consumption_onto_a_non_manual_row(engine) -> None:  # noqa: F811
    manual, ponderado, _, _ = _mundo(engine)
    antes = _foto(engine)
    _rejects(
        engine,
        "INSERT INTO sell_in_consumos (modo_id, canal, venta_ref, item_id, fecha_venta, unidades, descuento_ars) "
        "VALUES (:m, 'ml', 1, 4512, DATE '2026-11-03', 1, -2000) "
        "ON CONFLICT (canal, venta_ref, modo_id) WHERE modo_id IS NOT NULL DO UPDATE SET modo_id = :p",
        {"m": manual, "p": ponderado},
    )
    assert _foto(engine) == antes


def test_copy_goes_through_the_trigger_too(engine) -> None:  # noqa: F811
    _, ponderado, _, _ = _mundo(engine)
    raw = engine.raw_connection()
    try:
        with pytest.raises(Exception) as exc:
            with raw.cursor() as cur:
                cur.copy_expert(
                    "COPY sell_in_consumos (modo_id, canal, venta_ref, item_id, fecha_venta, unidades, descuento_ars) "
                    "FROM STDIN WITH CSV",
                    io.StringIO(f"{ponderado},ml,77,4512,2026-11-03,1,-5\n"),
                )
        assert "is not a manual block" in str(exc.value)
    finally:
        raw.rollback()
        raw.close()


def test_truncate_of_the_modes_without_cascade_is_refused(engine) -> None:  # noqa: F811
    _mundo(engine)
    antes = _foto(engine)
    with pytest.raises(DBAPIError):
        with engine.begin() as conn:
            conn.execute(text("TRUNCATE sell_in_modos_producto"))
    assert _foto(engine) == antes


def test_truncate_cascade_of_the_modes_is_refused_too(engine) -> None:  # noqa: F811
    # Row triggers do not see TRUNCATE; a statement trigger does, CASCADE included.
    _mundo(engine)
    antes = _foto(engine)
    with pytest.raises(DBAPIError):
        with engine.begin() as conn:
            conn.execute(text("TRUNCATE sell_in_modos_producto CASCADE"))
    assert _foto(engine) == antes


def test_consumptions_of_a_manual_block_survive_only_with_it(engine) -> None:  # noqa: F811
    manual, _, _, _ = _mundo(engine)
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM sell_in_modos_producto WHERE id = :i"), {"i": manual})
