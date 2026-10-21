"""Brand bonus reconcile (sell-in-sell-out T3c-3): one generated sell-in
purchase per (bonus, Compras operation), from the operation's INVOICED units of
the bonus's brand (owner 2026-10-19: "es sobre lo facturado"; invoiced 100 with
a credit note of 10 → "sobre 90"), kept in step and never touching manual ones.

Postgres only: the reconcile takes advisory locks and the consumptions are
recomputed by the FIFO strategy. Runs in a throwaway schema (`_bono_world`).
"""

from __future__ import annotations

import threading
import time
from datetime import date
from decimal import Decimal
from typing import Iterator, List

import pytest
from sqlalchemy import Engine, event, text
from sqlalchemy.orm import sessionmaker

from app.models.sell_in import SellInBonoMarca
from app.services.sell_in import bonos
from tests.services.sell_in import _bono_world as b
from tests.services.sell_in import _world as w

D = date


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with b.world("sell_in_bonos") as engine:
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


def _counts(result: bonos.ReconcileResult) -> tuple:
    return (result.creadas, result.actualizadas, result.anuladas)


@pytest.mark.postgres
class TestGeneration:
    def test_a_bonus_generates_one_purchase_per_invoiced_operation_of_its_brand(self, engine: Engine) -> None:
        bono = b.bono(engine, monto="2.50", moneda="USD")
        pedido = b.pedido(engine, {2964: 90, 2270: 10, 950: 40}, D(2026, 10, 10), tipo_cambio="1450.000000")

        result = _reconciliar(engine, bono_ids=[bono])

        assert _counts(result) == (1, 0, 0)
        assert b.generadas(engine) == [
            (bono, pedido, "activa", "USD", Decimal("250.00"), Decimal("1450.000000"), D(2026, 10, 10), 31)
        ]
        # Only the brand's items (950 is another brand), each units x amount per unit.
        assert b.items_de(engine, bono, pedido) == [(2270, 10, Decimal("25.00")), (2964, 90, Decimal("225.00"))]

    def test_the_generated_purchase_is_linked_to_its_operation_and_split_per_unit(self, engine: Engine) -> None:
        bono = b.bono(engine)
        pedido = b.pedido(engine, {2964: 5})

        _reconciliar(engine, pedido_ids=[pedido])

        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT c.origen, c.formula, c.pedido_compra_id, c.usuario_id, c.cuenta_desde, l.pedido_compra_id "
                    "FROM sell_in_compras c JOIN sell_in_compra_pedidos l ON l.compra_id = c.id WHERE c.bono_id = :b"
                ),
                {"b": bono},
            ).one()
        assert tuple(row) == ("bono_marca", "por_unidad", pedido, 7, "compra", pedido)

    def test_operations_outside_the_range_cancelled_or_rejected_get_nothing(self, engine: Engine) -> None:
        bono = b.bono(engine, desde=D(2026, 10, 1), hasta=D(2026, 10, 31))
        dentro = b.pedido(engine, {2964: 1}, D(2026, 10, 31))  # the range is inclusive
        b.pedido(engine, {2964: 1}, D(2026, 11, 1))
        b.pedido(engine, {2964: 1}, D(2026, 9, 30))
        b.pedido(engine, {2964: 1}, None)  # not invoiced yet
        b.pedido(engine, {2964: 1}, D(2026, 10, 5), estado="cancelado")
        b.pedido(engine, {2964: 1}, D(2026, 10, 5), estado="rechazado")

        _reconciliar(engine, bono_ids=[bono])

        assert [(g[0], g[1]) for g in b.generadas(engine)] == [(bono, dentro)]

    def test_an_operation_without_items_of_the_brand_gets_nothing(self, engine: Engine) -> None:
        bono = b.bono(engine, marca=b.TPLINK)
        b.pedido(engine, {950: 10})

        result = _reconciliar(engine, bono_ids=[bono])

        assert _counts(result) == (0, 0, 0)
        assert b.generadas(engine) == []

    def test_an_ars_bonus_keeps_its_currency(self, engine: Engine) -> None:
        bono = b.bono(engine, monto="1000.00", moneda="ARS")
        b.pedido(engine, {2270: 3}, moneda="ARS", tipo_cambio=None)

        _reconciliar(engine, bono_ids=[bono])

        assert b.generadas(engine)[0][2:6] == ("activa", "ARS", Decimal("3000.00"), None)

    def test_two_bonuses_on_one_operation_stack(self, engine: Engine) -> None:
        uno, otro = b.bono(engine, monto="1.00"), b.bono(engine, monto="3.00")
        pedido = b.pedido(engine, {2964: 4})

        _reconciliar(engine, pedido_ids=[pedido])

        assert [(g[0], g[4]) for g in b.generadas(engine)] == [(uno, Decimal("4.00")), (otro, Decimal("12.00"))]

    def test_an_audit_row_is_written_per_generated_line(self, engine: Engine) -> None:
        b.bono(engine)
        pedido = b.pedido(engine, {2964: 1, 2270: 1})

        _reconciliar(engine, pedido_ids=[pedido])

        assert b.auditoria(engine) == ["SELL_IN_COMPRA_CREADA", "SELL_IN_COMPRA_CREADA"]


@pytest.mark.postgres
class TestExchangeRate:
    def test_a_usd_bonus_uses_the_operations_own_rate(self, engine: Engine) -> None:
        bono = b.bono(engine, moneda="USD")
        b.tipo_cambio(engine, D(2026, 10, 10), 999.0)  # never used while the operation has its rate
        b.pedido(engine, {2964: 1}, tipo_cambio="1510.250000")

        _reconciliar(engine, bono_ids=[bono])

        assert b.generadas(engine)[0][5] == Decimal("1510.250000")

    def test_without_a_rate_of_its_own_the_bna_rate_of_the_invoice_date_is_used(self, engine: Engine) -> None:
        bono = b.bono(engine, moneda="USD")
        b.tipo_cambio(engine, D(2026, 10, 8), 1400.0)
        b.tipo_cambio(engine, D(2026, 10, 9), 1425.5)  # the latest on or before the invoice date
        b.tipo_cambio(engine, D(2026, 10, 11), 1499.0)  # after it: never
        b.pedido(engine, {2964: 1}, D(2026, 10, 10), moneda="ARS", tipo_cambio=None)

        _reconciliar(engine, bono_ids=[bono])

        assert b.generadas(engine)[0][5] == Decimal("1425.500000")

    def test_no_rate_at_all_fails_that_operation_and_writes_nothing_for_it(self, engine: Engine) -> None:
        bono = b.bono(engine, moneda="USD")
        sin_tc = b.pedido(engine, {2964: 1}, moneda="ARS", tipo_cambio=None)
        con_tc = b.pedido(engine, {2964: 2})

        result = _reconciliar(engine, bono_ids=[bono])

        assert [(g[0], g[1]) for g in b.generadas(engine)] == [(bono, con_tc)]
        assert list(result.fallidas) == [(bono, sin_tc)]
        assert "tipo de cambio" in result.fallidas[(bono, sin_tc)]


@pytest.mark.postgres
class TestIdempotence:
    def test_a_rerun_changes_nothing(self, engine: Engine) -> None:
        bono = b.bono(engine)
        pedido = b.pedido(engine, {2964: 3, 2270: 2})
        _reconciliar(engine, bono_ids=[bono])
        antes = (b.generadas(engine), b.items_de(engine, bono, pedido), b.auditoria(engine))

        result = _reconciliar(engine, bono_ids=[bono], pedido_ids=[pedido])

        assert _counts(result) == (0, 0, 0)
        assert (b.generadas(engine), b.items_de(engine, bono, pedido), b.auditoria(engine)) == antes

    def test_a_product_cost_change_does_not_rewrite_the_frozen_base_cost(self, engine: Engine) -> None:
        bono = b.bono(engine)
        b.pedido(engine, {2964: 3})
        _reconciliar(engine, bono_ids=[bono])
        with engine.begin() as conn:
            conn.execute(text("UPDATE productos_erp SET costo = 99 WHERE item_id = 2964"))

        result = _reconciliar(engine, bono_ids=[bono])

        assert _counts(result) == (0, 0, 0)
        with engine.connect() as conn:
            assert conn.execute(text("SELECT costo_base_unit FROM sell_in_compra_items")).scalar() == Decimal(
                "41.500000"
            )


@pytest.mark.postgres
class TestChanges:
    def test_invoiced_units_net_of_a_credit_note_update_the_purchase_in_place(self, engine: Engine) -> None:
        bono = b.bono(engine, monto="2.00")
        pedido = b.pedido(engine, {2964: 100})
        _reconciliar(engine, bono_ids=[bono])
        compra = b.compra_id(engine, bono, pedido)

        b.set_lineas(engine, pedido, {2964: 90, 2270: 5})  # a credit note returned 10; a new line appeared
        result = _reconciliar(engine, pedido_ids=[pedido])

        assert _counts(result) == (0, 1, 0)
        assert b.compra_id(engine, bono, pedido) == compra
        assert b.items_de(engine, bono, pedido) == [(2270, 5, Decimal("10.00")), (2964, 90, Decimal("180.00"))]
        assert b.generadas(engine)[0][4] == Decimal("190.00")
        assert b.auditoria(engine)[-1] == "SELL_IN_COMPRA_BONO_ACTUALIZADA"

    def test_a_line_that_leaves_the_invoice_leaves_the_purchase(self, engine: Engine) -> None:
        bono = b.bono(engine)
        pedido = b.pedido(engine, {2964: 1, 2270: 1})
        _reconciliar(engine, bono_ids=[bono])

        b.set_lineas(engine, pedido, {2964: 1})
        _reconciliar(engine, pedido_ids=[pedido])

        assert b.items_de(engine, bono, pedido) == [(2964, 1, Decimal("2.00"))]

    def test_units_of_a_product_removed_from_the_catalog_no_longer_match_the_brand(self, engine: Engine) -> None:
        """A product still referenced by a sell-in item cannot be deleted (FK); one deleted before its
        operation is reconciled leaves its invoiced units out of the bonus."""
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO productos_erp (item_id, codigo, descripcion, marca, costo, moneda_costo) "
                    "VALUES (4005, 'C4005', 'Producto', 'TP-LINK', 10, 'USD')"
                )
            )
        bono = b.bono(engine)
        pedido = b.pedido(engine, {4005: 3, 2964: 1})
        b.pedido(engine, {4005: 2})  # only the removed product: generates nothing

        with engine.begin() as conn:
            conn.execute(text("DELETE FROM productos_erp WHERE item_id = 4005"))
        result = _reconciliar(engine, bono_ids=[bono])

        assert _counts(result) == (1, 0, 0)
        assert b.items_de(engine, bono, pedido) == [(2964, 1, Decimal("2.00"))]
        assert [g[1] for g in b.generadas(engine)] == [pedido]

    def test_an_operation_that_leaves_the_range_is_voided_and_comes_back_when_it_returns(self, engine: Engine) -> None:
        bono = b.bono(engine)
        pedido = b.pedido(engine, {2964: 1}, D(2026, 10, 10))
        _reconciliar(engine, bono_ids=[bono])
        compra = b.compra_id(engine, bono, pedido)

        b.update_pedido(engine, pedido, fecha_factura=D(2026, 11, 2))
        assert _counts(_reconciliar(engine, pedido_ids=[pedido])) == (0, 0, 1)
        assert b.generadas(engine)[0][2] == "anulada"

        b.update_pedido(engine, pedido, fecha_factura=D(2026, 10, 12))
        assert _counts(_reconciliar(engine, pedido_ids=[pedido])) == (0, 1, 0)
        assert b.generadas(engine)[0][2] == "activa"
        assert b.generadas(engine)[0][6] == D(2026, 10, 12)
        assert b.compra_id(engine, bono, pedido) == compra  # the same purchase, never a second one

    @pytest.mark.parametrize("cambio", [{"estado": "cancelado"}, {"fecha_factura": None}])
    def test_a_cancelled_or_unlinked_operation_voids_its_purchase(self, engine: Engine, cambio: dict) -> None:
        bono = b.bono(engine)
        pedido = b.pedido(engine, {2964: 1})
        _reconciliar(engine, bono_ids=[bono])

        b.update_pedido(engine, pedido, **cambio)
        if cambio.get("fecha_factura", 1) is None:
            b.set_lineas(engine, pedido, {})  # unlinking the invoice empties the snapshot too
        _reconciliar(engine, pedido_ids=[pedido])

        assert b.generadas(engine)[0][2] == "anulada"
        assert b.auditoria(engine)[-1] == "SELL_IN_COMPRA_ANULADA"

    def test_a_deleted_operation_voids_its_orphan_purchase(self, engine: Engine) -> None:
        bono = b.bono(engine)
        pedido = b.pedido(engine, {2964: 1})
        _reconciliar(engine, bono_ids=[bono])
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM pedidos_compra WHERE id = :p"), {"p": pedido})

        result = _reconciliar(engine, pedido_ids=[pedido])

        assert _counts(result) == (0, 0, 1)
        assert b.generadas(engine) == [
            (bono, None, "anulada", "USD", Decimal("2.00"), Decimal("1450.000000"), D(2026, 10, 10), 31)
        ]

    def test_a_voided_bonus_voids_every_purchase_it_generated(self, engine: Engine) -> None:
        bono = b.bono(engine)
        uno, otro = b.pedido(engine, {2964: 1}), b.pedido(engine, {2270: 1})
        _reconciliar(engine, bono_ids=[bono])

        b.update_bono(engine, bono, estado="anulada")
        result = _reconciliar(engine, bono_ids=[bono])

        assert _counts(result) == (0, 0, 2)
        assert [(g[1], g[2]) for g in b.generadas(engine)] == [(uno, "anulada"), (otro, "anulada")]

    def test_an_edited_bonus_reconciles_its_purchases(self, engine: Engine) -> None:
        bono = b.bono(engine, monto="2.00", hasta=D(2026, 10, 31))
        dentro = b.pedido(engine, {2964: 10}, D(2026, 10, 5))
        fuera = b.pedido(engine, {2964: 1}, D(2026, 10, 25))
        _reconciliar(engine, bono_ids=[bono])

        b.update_bono(engine, bono, monto_unit=Decimal("3.00"), fecha_hasta=D(2026, 10, 20))
        result = _reconciliar(engine, bono_ids=[bono])

        assert _counts(result) == (0, 1, 1)
        assert [(g[1], g[2], g[4]) for g in b.generadas(engine)] == [
            (dentro, "activa", Decimal("30.00")),
            (fuera, "anulada", Decimal("2.00")),
        ]

    def test_a_brand_change_swaps_the_items(self, engine: Engine) -> None:
        bono = b.bono(engine, marca=b.TPLINK)
        pedido = b.pedido(engine, {2964: 1, 950: 4})
        _reconciliar(engine, bono_ids=[bono])

        b.update_bono(engine, bono, marca=b.MERCUSYS)
        _reconciliar(engine, bono_ids=[bono])

        assert b.items_de(engine, bono, pedido) == [(950, 4, Decimal("8.00"))]

    def test_manual_purchases_are_never_touched(self, engine: Engine) -> None:
        manual = w.compra(engine, [(2964, 5, "100.00")])
        bono = b.bono(engine)
        b.pedido(engine, {2964: 1})
        _reconciliar(engine, bono_ids=[bono])
        b.update_bono(engine, bono, estado="anulada")

        _reconciliar(engine, bono_ids=[bono])

        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT c.origen, c.estado, i.cantidad, i.monto_asignado FROM sell_in_compras c "
                    "JOIN sell_in_compra_items i ON i.compra_id = c.id WHERE i.id = :i"
                ),
                {"i": manual[0]},
            ).one()
        assert tuple(row) == ("manual", "activa", 5, Decimal("100.00"))


@pytest.mark.postgres
class TestConcurrency:
    def test_a_bonus_rows_loaded_before_the_lock_are_read_again(self, engine: Engine) -> None:
        """A worker batch shares one session: a bonus loaded by an earlier call must not be reused stale."""
        bono = b.bono(engine, monto="2.00")
        pedido = b.pedido(engine, {2964: 3})
        with sessionmaker(bind=engine)() as db:
            cargado = db.get(SellInBonoMarca, bono)  # held: the identity map is weak
            assert cargado.monto_unit == Decimal("2.00")
            with engine.begin() as other:
                other.execute(text("UPDATE sell_in_bonos_marca SET monto_unit = 5 WHERE id = :b"), {"b": bono})
            bonos.reconciliar(db, pedido_ids=[pedido])
            db.commit()

        assert b.items_de(engine, bono, pedido) == [(2964, 3, Decimal("15.00"))]

    def test_a_bonus_that_appears_while_waiting_for_the_lock_is_left_to_its_own_key(self, engine: Engine) -> None:
        """Only the bonuses locked before the re-read are written: a bonus activated while this call
        waited is unlocked here, and its own trigger has queued it for a call that will lock it."""
        uno = b.bono(engine)
        otro = b.bono(engine, estado="anulada")
        pedido = b.pedido(engine, {2964: 1})
        b.clear_queue(engine)
        resultado: dict = {}

        def reconcile() -> None:
            try:
                with sessionmaker(bind=engine)() as db:
                    resultado["r"] = bonos.reconciliar(db, pedido_ids=[pedido])
                    db.commit()
            except Exception as exc:  # surfaced by the assertion below
                resultado["error"] = exc

        holder = engine.connect()
        try:
            holder.execute(text("SELECT pg_advisory_xact_lock(:ns, :b)"), {"ns": bonos.LOCK_NAMESPACE, "b": uno})
            worker = threading.Thread(target=reconcile)
            worker.start()
            _wait_for_lock_waiter(engine, uno)
            with engine.begin() as conn:
                conn.execute(text("UPDATE sell_in_bonos_marca SET estado = 'activa' WHERE id = :b"), {"b": otro})
            holder.rollback()  # releases the lock: the call re-reads and finds `otro` too
            worker.join(timeout=30)
        finally:
            holder.close()

        assert "error" not in resultado, resultado.get("error")
        assert [(g[0], g[1]) for g in b.generadas(engine)] == [(uno, pedido)]
        assert ("bono", otro) in b.queued(engine)

    def test_an_orphan_of_another_bonus_that_appears_while_waiting_is_left_to_its_own_key(self, engine: Engine) -> None:
        """`mercusys` covers another month, so a call for `propio` never locks it; its orphan is
        voided by the call its own key (the deleted operation) triggers."""
        tplink = b.bono(engine, marca=b.TPLINK)
        mercusys = b.bono(engine, marca=b.MERCUSYS, desde=D(2026, 11, 1), hasta=D(2026, 11, 30))
        propio, ajeno = b.pedido(engine, {2964: 1}), b.pedido(engine, {950: 1}, D(2026, 11, 10))
        _reconciliar(engine, bono_ids=[tplink, mercusys])
        b.clear_queue(engine)
        resultado: dict = {}

        def reconcile() -> None:
            try:
                with sessionmaker(bind=engine)() as db:
                    resultado["r"] = bonos.reconciliar(db, pedido_ids=[propio])
                    db.commit()
            except Exception as exc:  # surfaced by the assertion below
                resultado["error"] = exc

        holder = engine.connect()
        try:
            holder.execute(text("SELECT pg_advisory_xact_lock(:ns, :b)"), {"ns": bonos.LOCK_NAMESPACE, "b": tplink})
            worker = threading.Thread(target=reconcile)
            worker.start()
            _wait_for_lock_waiter(engine, tplink)
            with engine.begin() as conn:
                conn.execute(text("DELETE FROM pedidos_compra WHERE id = :p"), {"p": ajeno})
            holder.rollback()
            worker.join(timeout=30)
        finally:
            holder.close()

        assert "error" not in resultado, resultado.get("error")
        assert [(g[0], g[2]) for g in b.generadas(engine) if g[1] is None] == [(mercusys, "activa")]
        assert ("pedido", ajeno) in b.queued(engine)


@pytest.mark.postgres
class TestQueryCount:
    def test_the_reads_of_a_call_do_not_grow_with_its_bonuses_operations_and_orphans(self, engine: Engine) -> None:
        """Pairs, BNA rates (one per invoice date) and the orphans' items are read in batches."""
        assert _selects_de_un_reconcile(engine, 1) == _selects_de_un_reconcile(engine, 4)


def _selects_de_un_reconcile(engine: Engine, n: int) -> int:
    """SELECTs of one call over `n` bonuses, `n` operations without a rate of their own (BNA rate) and
    `n` orphans; everything else is already in line, so the call only reads (and voids the orphans)."""
    b.clean(engine)
    b.tipo_cambio(engine, D(2026, 10, 1), 1000)
    bono_ids = [b.bono(engine, monto="1.00") for _ in range(n)]
    vivos = [b.pedido(engine, {2964: 1}, tipo_cambio=None) for _ in range(n)]
    muertos = [b.pedido(engine, {2964: 1}, tipo_cambio=None) for _ in range(n)]
    _reconciliar(engine, bono_ids=bono_ids)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM pedidos_compra WHERE id = ANY(:ids)"), {"ids": muertos})

    selects: List[str] = []

    def contar(conn, cursor, statement, parameters, context, executemany) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            selects.append(statement)

    event.listen(engine, "before_cursor_execute", contar)
    try:
        result = _reconciliar(engine, bono_ids=bono_ids, pedido_ids=vivos + muertos)
    finally:
        event.remove(engine, "before_cursor_execute", contar)
    assert (result.creadas, result.actualizadas, result.anuladas) == (0, 0, n * n)
    return len(selects)


def _wait_for_lock_waiter(engine: Engine, bono_id: int) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        with engine.connect() as conn:
            waiting = conn.execute(
                text(
                    "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND NOT granted "
                    "AND classid = :ns AND objid = :b"
                ),
                {"ns": bonos.LOCK_NAMESPACE, "b": bono_id},
            ).scalar_one()
        if waiting:
            return
        time.sleep(0.05)
    raise AssertionError("the reconcile never waited on the bonus lock")


@pytest.mark.postgres
class TestConsumption:
    def test_sales_after_the_invoice_consume_the_bonus_and_a_void_releases_them(self, engine: Engine) -> None:
        bono = b.bono(engine, monto="2.00", moneda="USD")
        b.pedido(engine, {2964: 10}, D(2026, 10, 10), tipo_cambio="1000.000000")
        antes = w.venta(engine, "fuera", 2964, 1, D(2026, 10, 9))  # before the invoice date: nothing
        despues = w.venta(engine, "fuera", 2964, 3, D(2026, 10, 15))

        _reconciliar(engine, bono_ids=[bono])

        assert [(c[2], c[4], c[5]) for c in w.consumos(engine)] == [(despues, 3, Decimal("6000.00"))]
        assert antes not in [c[2] for c in w.consumos(engine)]

        b.update_bono(engine, bono, estado="anulada")
        _reconciliar(engine, bono_ids=[bono])

        assert w.consumos(engine) == []

    def test_a_deleted_operation_releases_what_its_orphan_purchase_consumed(self, engine: Engine) -> None:
        """Deleting the operation SET NULLs `bono_pedido_id` before the worker runs: the
        `('pedido', id)` key no longer finds the purchase, the orphan sweep voids it and
        the sales it fed are recomputed in the same transaction."""
        bono = b.bono(engine, monto="2.00", moneda="USD")
        pedido = b.pedido(engine, {2964: 10}, D(2026, 10, 10), tipo_cambio="1000.000000")
        w.venta(engine, "fuera", 2964, 3, D(2026, 10, 15))
        _reconciliar(engine, bono_ids=[bono])
        assert [c[4] for c in w.consumos(engine)] == [3]

        with engine.begin() as conn:
            conn.execute(text("DELETE FROM pedidos_compra WHERE id = :p"), {"p": pedido})
        result = _reconciliar(engine, pedido_ids=[pedido])

        assert _counts(result) == (0, 0, 1)
        assert [g[2] for g in b.generadas(engine)] == ["anulada"]
        assert w.consumos(engine) == []

    def test_fewer_invoiced_units_shrink_what_sales_can_consume(self, engine: Engine) -> None:
        bono = b.bono(engine, monto="1.00", moneda="ARS")
        pedido = b.pedido(engine, {2270: 5}, moneda="ARS", tipo_cambio=None)
        w.venta(engine, "fuera", 2270, 4, D(2026, 10, 15))
        _reconciliar(engine, bono_ids=[bono])
        assert [c[4] for c in w.consumos(engine)] == [4]

        b.set_lineas(engine, pedido, {2270: 2})
        _reconciliar(engine, pedido_ids=[pedido])

        assert [(c[4], c[5]) for c in w.consumos(engine)] == [(2, Decimal("2.00"))]
