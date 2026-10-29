"""Independent verifier probes for sell-in-sell-out T24 (shared cap of a sell-in bonus).

Each probe drives the public reconcile (`bonos.reconciliar`) the way the `sell_in.bono` worker does: with the keys
the live triggers queued (`sell_in_bono_dirty`), never with hand-picked ids, unless the probe says so.

Postgres only, in a throwaway schema (`_bono_world`).
"""

from __future__ import annotations

import threading
from datetime import date
from decimal import Decimal
from typing import Iterator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from app.services.sell_in import bonos
from tests.services.sell_in import _bono_world as b

D = date
pytestmark = pytest.mark.postgres


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with b.world("t24_verify") as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    yield
    b.clean(engine)


def _reconciliar(engine: Engine, **kwargs) -> bonos.ReconcileResult:
    with sessionmaker(bind=engine)() as db:
        result = bonos.reconciliar(db, **kwargs)
        db.commit()
    return result


def _drain(engine: Engine) -> bonos.ReconcileResult:
    """What the worker does: reconcile exactly the queued keys, then clear them."""
    keys = b.queued(engine)
    result = _reconciliar(
        engine,
        bono_ids=[r for t, r in keys if t == "bono"],
        pedido_ids=[r for t, r in keys if t == "pedido"],
    )
    b.clear_queue(engine)
    return result


def _activas(engine: Engine, bono_id: int) -> dict:
    """pedido -> (units, amount) of the ACTIVE purchases generated for `bono_id`."""
    out = {}
    for g in b.generadas(engine):
        if g[0] == bono_id and g[2] == "activa":
            out[g[1]] = (sum(c for _, c, _ in b.items_de(engine, bono_id, g[1])), g[4])
    return out


def _snapshot(engine: Engine) -> list:
    with engine.connect() as conn:
        return [
            tuple(r)
            for r in conn.execute(
                text(
                    "SELECT c.id, c.bono_id, c.bono_pedido_id, c.estado, c.monto_total, i.item_id, i.cantidad, "
                    "i.monto_asignado FROM sell_in_compras c LEFT JOIN sell_in_compra_items i ON i.compra_id = c.id "
                    "ORDER BY c.id, i.item_id"
                )
            )
        ]


def _capped(engine, **kw) -> int:
    tope = {k: kw.pop(k) for k in ("tope_unidades", "tope_monto") if k in kw}
    bono = b.bono(engine, **kw)
    b.update_bono(engine, bono, **tope)
    b.clear_queue(engine)
    return bono


# ---------------------------------------------------------------- 1. chronological shared cap (owner's example)


def test_p1_owner_example_two_models_per_model_amounts_shared_cap_in_invoice_order(engine) -> None:
    # "tablets y notebooks lenovo que aplica hasta 3000 USD entre los dos": two models, own amounts, one cap.
    bono = b.bono_alcance(engine, "modelos", modelos=(2964, 2270), monto="2.00")
    b.valor_de_modelo(engine, bono, 2964, monto="7.00")
    b.update_bono(engine, bono, tope_monto="30.00")
    b.clear_queue(engine)
    # Created out of date order: ids do not decide, the invoice date does.
    tardio = b.pedido(engine, {2964: 3}, D(2026, 10, 20))  # 21.00 desired
    temprano = b.pedido(engine, {2270: 5, 2964: 1}, D(2026, 10, 5))  # 10.00 + 7.00
    ultimo = b.pedido(engine, {2270: 2}, D(2026, 10, 25))  # 4.00 desired

    result = _drain(engine)

    assert result.fallidas == {}
    assert b.items_de(engine, bono, temprano) == [(2270, 5, Decimal("10.00")), (2964, 1, Decimal("7.00"))]
    # 13.00 left; 7.00 per unit -> 2 units, capped at 13.00.
    assert b.items_de(engine, bono, tardio) == [(2964, 2, Decimal("13.00"))]
    assert b.items_de(engine, bono, ultimo) == []
    assert sum(v[1] for v in _activas(engine, bono).values()) == Decimal("30.00")


def test_p1b_late_operation_dated_earlier_displaces_later_ones_through_its_own_pedido_key(engine) -> None:
    bono = _capped(engine, monto="10.00", tope_monto="25.00")
    x = b.pedido(engine, {2964: 2}, D(2026, 10, 10))
    y = b.pedido(engine, {2964: 2}, D(2026, 10, 12))
    _drain(engine)
    assert _activas(engine, bono) == {x: (2, Decimal("20.00")), y: (1, Decimal("5.00"))}

    z = b.pedido(engine, {2964: 2}, D(2026, 10, 5))  # queues only ('pedido', z)
    assert b.queued(engine) == [("pedido", z)]
    _drain(engine)

    assert _activas(engine, bono) == {z: (2, Decimal("20.00")), x: (1, Decimal("5.00"))}
    estados = {g[1]: g[2] for g in b.generadas(engine) if g[0] == bono}
    assert estados[y] == "anulada"


def test_p1c_same_invoice_date_breaks_ties_by_operation_id(engine) -> None:
    bono = _capped(engine, monto="10.00", tope_unidades=3)
    a = b.pedido(engine, {2964: 2}, D(2026, 10, 10))
    c = b.pedido(engine, {2964: 2}, D(2026, 10, 10))
    _drain(engine)
    assert _activas(engine, bono) == {a: (2, Decimal("20.00")), c: (1, Decimal("10.00"))}


# ---------------------------------------------------------------- 2. recompute on edit / cancel / delete / bonus edits


def test_p2a_credit_note_shrinks_an_earlier_operation_and_frees_the_cap(engine) -> None:
    bono = _capped(engine, monto="10.00", tope_monto="25.00")
    x = b.pedido(engine, {2964: 2}, D(2026, 10, 10))
    y = b.pedido(engine, {2964: 2}, D(2026, 10, 12))
    w = b.pedido(engine, {2964: 2}, D(2026, 10, 14))
    _drain(engine)

    b.set_lineas(engine, x, {2964: 1})  # NC: 1 unit back
    _drain(engine)

    # 10.00 + 15.00 (y: 2 units capped at the 15.00 left), w nothing.
    assert _activas(engine, bono) == {x: (1, Decimal("10.00")), y: (2, Decimal("15.00"))}
    assert w not in _activas(engine, bono)


def test_p2b_cancelled_operation_frees_its_share(engine) -> None:
    bono = _capped(engine, monto="10.00", tope_monto="25.00")
    x = b.pedido(engine, {2964: 2}, D(2026, 10, 10))
    y = b.pedido(engine, {2964: 2}, D(2026, 10, 12))
    w = b.pedido(engine, {2964: 2}, D(2026, 10, 14))
    _drain(engine)

    b.update_pedido(engine, x, estado="cancelado")
    _drain(engine)

    assert _activas(engine, bono) == {y: (2, Decimal("20.00")), w: (1, Decimal("5.00"))}


def test_p2c_deleted_operation_frees_its_share(engine) -> None:
    bono = _capped(engine, monto="10.00", tope_monto="25.00")
    x = b.pedido(engine, {2964: 2}, D(2026, 10, 10))
    y = b.pedido(engine, {2964: 2}, D(2026, 10, 12))
    w = b.pedido(engine, {2964: 2}, D(2026, 10, 14))
    _drain(engine)
    assert _activas(engine, bono) == {x: (2, Decimal("20.00")), y: (1, Decimal("5.00"))}

    with engine.begin() as conn:
        conn.execute(text("DELETE FROM pedido_compra_lineas_facturadas WHERE pedido_id = :p"), {"p": x})
        conn.execute(text("DELETE FROM pedidos_compra WHERE id = :p"), {"p": x})
    queued = b.queued(engine)
    _drain(engine)

    # The deleted operation's purchase is voided; its 20.00 go to y (whole) and w (5.00).
    assert _activas(engine, bono) == {y: (2, Decimal("20.00")), w: (1, Decimal("5.00"))}, queued


def test_p2d0_the_live_definition_queues_a_cap_change(engine) -> None:
    """A1: `bono_queue.UPGRADE_SQL` (what the test world installs) queues a cap change, as migration 20261211 does."""
    bono = _capped(engine, monto="10.00", tope_monto="25.00")
    b.clear_queue(engine)
    b.update_bono(engine, bono, tope_monto="45.00")
    assert b.queued(engine) == [("bono", bono)]


def test_p2d00_the_live_update_trigger_is_the_migrations() -> None:
    """A1: the module's bonus update trigger and the latest migration's (20261212, which extends 20261211's list) are
    the same statement."""
    import importlib.util
    from pathlib import Path

    from app.services.sell_in import bono_queue

    path = Path(__file__).resolve().parents[3] / "alembic/versions/20261212_sell_in_bono_costo.py"
    spec = importlib.util.spec_from_file_location("m20261212", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    vivo = [s for s in bono_queue.UPGRADE_SQL if "CREATE TRIGGER trg_sell_in_bono_bonos_update" in s]
    assert len(vivo) == 1
    assert " ".join(vivo[0].split()) == " ".join(mod._trigger(con_costo=True).split())


def test_p2d_raise_lower_remove_cap_and_void_bonus(engine) -> None:
    bono = _capped(engine, monto="10.00", tope_monto="25.00")
    x = b.pedido(engine, {2964: 2}, D(2026, 10, 10))
    y = b.pedido(engine, {2964: 2}, D(2026, 10, 12))
    w = b.pedido(engine, {2964: 2}, D(2026, 10, 14))
    _drain(engine)

    b.update_bono(engine, bono, tope_monto="45.00")
    assert ("bono", bono) in b.queued(engine)
    _drain(engine)
    assert _activas(engine, bono) == {x: (2, Decimal("20.00")), y: (2, Decimal("20.00")), w: (1, Decimal("5.00"))}

    b.update_bono(engine, bono, tope_monto="15.00")
    _drain(engine)
    assert _activas(engine, bono) == {x: (2, Decimal("15.00"))}

    b.update_bono(engine, bono, tope_monto=None)
    assert ("bono", bono) in b.queued(engine)
    _drain(engine)
    assert _activas(engine, bono) == {x: (2, Decimal("20.00")), y: (2, Decimal("20.00")), w: (2, Decimal("20.00"))}

    b.update_bono(engine, bono, tope_unidades=3)
    assert ("bono", bono) in b.queued(engine)
    _drain(engine)
    assert _activas(engine, bono) == {x: (2, Decimal("20.00")), y: (1, Decimal("10.00"))}

    b.update_bono(engine, bono, estado="anulada")
    _drain(engine)
    assert _activas(engine, bono) == {}


def test_p2e_rerun_is_a_no_op(engine) -> None:
    bono = _capped(engine, monto="10.00", tope_monto="25.00")
    b.pedido(engine, {2964: 2}, D(2026, 10, 10))
    b.pedido(engine, {2964: 2}, D(2026, 10, 12))
    _drain(engine)
    antes = _snapshot(engine)
    r = _reconciliar(engine, bono_ids=[bono])
    assert (r.creadas, r.actualizadas, r.anuladas) == (0, 0, 0)
    assert _snapshot(engine) == antes


def test_p2f_operation_moved_out_of_range_frees_the_cap(engine) -> None:
    bono = _capped(engine, monto="10.00", tope_monto="25.00")
    x = b.pedido(engine, {2964: 2}, D(2026, 10, 10))
    y = b.pedido(engine, {2964: 2}, D(2026, 10, 12))
    _drain(engine)
    b.update_pedido(engine, x, fecha_factura=D(2026, 11, 15))  # out of the bonus range
    _drain(engine)
    assert _activas(engine, bono) == {y: (2, Decimal("20.00"))}


# ---------------------------------------------------------------- 3. T23 per-model amounts kept (see p1) + %


def test_p3_percentage_bonus_per_model_percentage_under_the_cap(engine) -> None:
    bono = b.bono_alcance(engine, "modelos", modelos=(2964, 2270), tipo="porcentaje", porcentaje="5")
    b.valor_de_modelo(engine, bono, 2964, porcentaje="10")
    b.update_bono(engine, bono, tope_monto="15.00")
    b.clear_queue(engine)
    p = b.pedido(engine, {2270: 2, 2964: 2}, D(2026, 10, 5))
    b.set_importe(engine, p, 2270, "100.00", "USD")  # 5% = 5.00
    b.set_importe(engine, p, 2964, "200.00", "USD")  # 10% = 20.00 -> 10.00 left: 1 unit (10.00/unit)
    _drain(engine)
    assert b.items_de(engine, bono, p) == [(2270, 2, Decimal("5.00")), (2964, 1, Decimal("10.00"))]


# ---------------------------------------------------------------- 4. units / money caps, currencies, rounding


def test_p4a_unit_cap(engine) -> None:
    bono = _capped(engine, monto="10.00", tope_unidades=3)
    x = b.pedido(engine, {2964: 2}, D(2026, 10, 10))
    y = b.pedido(engine, {2964: 2}, D(2026, 10, 12))
    w = b.pedido(engine, {2964: 2}, D(2026, 10, 14))
    _drain(engine)
    assert _activas(engine, bono) == {x: (2, Decimal("20.00")), y: (1, Decimal("10.00"))}
    assert w not in _activas(engine, bono)


def test_p4b_both_caps_the_tighter_wins(engine) -> None:
    bono = _capped(engine, monto="10.00", tope_unidades=5, tope_monto="25.00")
    x = b.pedido(engine, {2964: 2}, D(2026, 10, 10))
    y = b.pedido(engine, {2964: 4}, D(2026, 10, 12))
    _drain(engine)
    assert _activas(engine, bono) == {x: (2, Decimal("20.00")), y: (1, Decimal("5.00"))}


def test_p4c_ars_cap_on_a_percentage_of_a_usd_invoice(engine) -> None:
    bono = b.bono(engine, moneda="ARS")
    b.update_bono(engine, bono, tipo="porcentaje", monto_unit=None, porcentaje="10", tope_monto="20000.00")
    b.clear_queue(engine)
    x = b.pedido(engine, {2964: 2}, D(2026, 10, 5), tipo_cambio="1450.000000")
    b.set_importe(engine, x, 2964, "100.00", "USD")  # 10 USD -> 14500.00 ARS (7250/unit)
    y = b.pedido(engine, {2964: 2}, D(2026, 10, 6), tipo_cambio="1500.000000")
    b.set_importe(engine, y, 2964, "100.00", "USD")  # 15000.00 ARS (7500/unit) -> 5500 left: 1 unit
    _drain(engine)
    assert b.items_de(engine, bono, x) == [(2964, 2, Decimal("14500.00"))]
    assert b.items_de(engine, bono, y) == [(2964, 1, Decimal("5500.00"))]
    assert {g[1]: g[3] for g in b.generadas(engine)} == {x: "ARS", y: "ARS"}


def test_p4d_usd_cap_on_a_percentage_of_an_ars_invoice(engine) -> None:
    bono = b.bono(engine, moneda="USD")
    b.update_bono(engine, bono, tipo="porcentaje", monto_unit=None, porcentaje="10", tope_monto="15.00")
    b.clear_queue(engine)
    x = b.pedido(engine, {2270: 4}, D(2026, 10, 5), moneda="ARS", tipo_cambio="1450.000000")
    b.set_importe(engine, x, 2270, "145000.00", "ARS")  # 10% = 14500 ARS = 10.00 USD
    y = b.pedido(engine, {2270: 4}, D(2026, 10, 6), moneda="ARS", tipo_cambio="1450.000000")
    b.set_importe(engine, y, 2270, "145000.00", "ARS")  # 10.00 USD (2.50/unit) -> 5.00 left: 2 units
    _drain(engine)
    assert b.items_de(engine, bono, x) == [(2270, 4, Decimal("10.00"))]
    assert b.items_de(engine, bono, y) == [(2270, 2, Decimal("5.00"))]


def test_p4e_uncapped_lines_keep_their_exact_cents_and_an_exact_cap_fits(engine) -> None:
    # Odd amounts that do not divide by units: the cap must not re-round a line it leaves whole.
    bono = b.bono(engine)
    b.update_bono(engine, bono, tipo="porcentaje", monto_unit=None, porcentaje="7", tope_monto="21.49")
    b.clear_queue(engine)
    x = b.pedido(engine, {2964: 3}, D(2026, 10, 5))
    b.set_importe(engine, x, 2964, "100.01", "USD")  # 7.0007 -> 7.00
    y = b.pedido(engine, {2964: 7}, D(2026, 10, 6))
    b.set_importe(engine, y, 2964, "206.99", "USD")  # 14.4893 -> 14.49
    _drain(engine)
    assert b.items_de(engine, bono, x) == [(2964, 3, Decimal("7.00"))]
    assert b.items_de(engine, bono, y) == [(2964, 7, Decimal("14.49"))]


def test_p4f_money_cap_smaller_than_one_unit(engine) -> None:
    bono = _capped(engine, monto="10.00", tope_monto="0.01")
    x = b.pedido(engine, {2964: 2}, D(2026, 10, 10))
    _drain(engine)
    assert b.items_de(engine, bono, x) == [(2964, 1, Decimal("0.01"))]


# ---------------------------------------------------------------- 6. invariants: failure, concurrency


def test_p6a_earlier_failure_leaves_later_operations_as_they_were(engine) -> None:
    bono = _capped(engine, monto="10.00", tope_monto="25.00")
    x = b.pedido(engine, {2964: 2}, D(2026, 10, 10))
    y = b.pedido(engine, {2964: 2}, D(2026, 10, 12))
    _drain(engine)
    antes = _snapshot(engine)
    z = b.pedido(engine, {2964: 2}, D(2026, 10, 5), moneda="ARS", tipo_cambio=None)  # no rate, no BNA
    r = _drain(engine)
    assert (bono, z) in r.fallidas and (bono, x) in r.fallidas and (bono, y) in r.fallidas
    assert _snapshot(engine) == antes


def test_p6b_two_reconciles_of_different_operations_of_one_capped_bonus_serialize(engine) -> None:
    bono = _capped(engine, monto="10.00", tope_monto="25.00")
    x = b.pedido(engine, {2964: 2}, D(2026, 10, 10))
    y = b.pedido(engine, {2964: 2}, D(2026, 10, 12))
    b.clear_queue(engine)
    Session = sessionmaker(bind=engine)
    outcome = {}

    def other():
        with Session() as s2:
            s2.execute(text("SET lock_timeout = '1s'"))
            try:
                bonos.reconciliar(s2, pedido_ids=[y])
                s2.commit()
                outcome["r"] = "ran"
            except OperationalError as exc:
                outcome["r"] = f"blocked: {type(exc.orig).__name__}"
                s2.rollback()
            except Exception as exc:  # reported by the assertion below, not as a KeyError
                outcome["r"] = f"error: {exc!r}"
                s2.rollback()

    with Session() as s1:
        bonos.reconciliar(s1, pedido_ids=[x])  # holds the bonus lock, uncommitted
        t = threading.Thread(target=other)
        t.start()
        t.join(10)
        # Still alive means it waited past its own 1s lock_timeout: it did not fail fast.
        assert not t.is_alive(), "the second reconcile is still waiting on the bonus lock"
        s1.commit()
    assert outcome.get("r", "").startswith("blocked"), outcome
    assert _activas(engine, bono) == {x: (2, Decimal("20.00")), y: (1, Decimal("5.00"))}


def test_p2c2_after_a_delete_a_later_reconcile_of_the_bonus_writes_nothing(engine) -> None:
    """B1 fixed: the worker's ('pedido', deleted) key already redistributes the cap; a later reconcile of the bonus
    (a cap edit, the full script) finds nothing left to change."""
    bono = _capped(engine, monto="10.00", tope_monto="25.00")
    x = b.pedido(engine, {2964: 2}, D(2026, 10, 10))
    y = b.pedido(engine, {2964: 2}, D(2026, 10, 12))
    w = b.pedido(engine, {2964: 2}, D(2026, 10, 14))
    _drain(engine)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM pedido_compra_lineas_facturadas WHERE pedido_id = :p"), {"p": x})
        conn.execute(text("DELETE FROM pedidos_compra WHERE id = :p"), {"p": x})
    _drain(engine)
    assert _activas(engine, bono) == {y: (2, Decimal("20.00")), w: (1, Decimal("5.00"))}
    result = _reconciliar(engine, bono_ids=[bono])
    assert (result.creadas, result.actualizadas, result.anuladas) == (0, 0, 0)
