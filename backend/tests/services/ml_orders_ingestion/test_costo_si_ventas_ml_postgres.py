"""ML sale costs at costo SI (sell-in-costo-si T3 PR 7): a new sale freezes the cost in force on its sale date (ART)
through THE reader (S13, L14, L18, Q1, S11/L19), and a costo SI change re-freezes the product's sales from that date,
its combos included, with a backup first (L15, §12), in bounded `sell.drain` passes. Invented data; L1's numbers
(23.817 then 22.757)."""

from __future__ import annotations

import logging

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Iterator, Optional

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from app.services.costo_si import despues
from app.services.costo_si.despues import ml_ventas
from app.services.ml_orders_ingestion import costeo_service, recongelar_costo_si as rc
from app.services.ml_orders_ingestion.costeo_service import congelar, fecha_venta_de
from app.services.ml_orders_ingestion.mapper import OrderItemOpsDTO
from tests.services.costo_si import _world as w

pytestmark = pytest.mark.postgres

D = Decimal
A, ARSP, SIN, COMBO, OTRO = 7101, 7102, 7103, 7104, 7105
MLA = {A: "MLA7101", ARSP: "MLA7102", SIN: "MLA7103", COMBO: "MLA7104", OTRO: "MLA7105"}
_orders = iter(range(910_000, 990_000))


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with w.world("ml_costo_si") as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    yield
    w.clean(engine)


def _paso(engine: Engine, item_id: int, orden: int, fecha: date, promedio: str, moneda: str = "USD") -> None:
    w.run(
        engine,
        "INSERT INTO costo_si_pasos (item_id, orden, tipo, fecha, cantidad, stock_antes, stock_base, stock_despues,"
        " promedio_usd, moneda) VALUES (:i, :o, :t, :f, 0, 0, 0, 0, :p, :m)",
        i=item_id,
        o=orden,
        t="inicio" if orden == 0 else "compra",
        f=fecha,
        p=promedio,
        m=moneda,
    )


def _mundo(engine: Engine) -> None:
    """A (USD, list 30): costo SI 23.817 from 10-01, 22.757 from 10-13. ARSP (ARS): costo SI 15000 from 10-01.
    SIN (USD): no costo SI, list 40. COMBO = 2 x A (no cost of its own). OTRO (USD): costo SI 9.5 from 10-01.
    USD rate 1000 from 10-01, 1200 from 10-12."""
    for item_id, moneda, costo in ((A, "USD", "30"), (ARSP, "ARS", "14000"), (SIN, "USD", "40"), (OTRO, "USD", "9")):
        w.producto(engine, item_id, moneda=moneda, costo=costo)
    w.producto(engine, COMBO, costo="0")
    w.run(engine, "UPDATE productos_erp SET iva = 21")
    for item_id, mla in MLA.items():
        w.run(engine, "INSERT INTO publicaciones_ml (mla, item_id, activo) VALUES (:m, :i, true)", m=mla, i=item_id)
    w.run(
        engine,
        "INSERT INTO combo_componentes (combo_item_id, componente_item_id, cantidad) VALUES (:c, :a, 2)",
        c=COMBO,
        a=A,
    )
    _paso(engine, A, 0, date(2026, 10, 1), "23.81700")
    _paso(engine, A, 1, date(2026, 10, 13), "22.75700")
    _paso(engine, ARSP, 0, date(2026, 10, 1), "15000.00000", moneda="ARS")
    _paso(engine, OTRO, 0, date(2026, 10, 1), "9.50000")
    w.tipo_cambio(engine, date(2026, 10, 1), 1000)
    w.tipo_cambio(engine, date(2026, 10, 12), 1200)


def _item(item_id: int, precio: float = 100000.0) -> OrderItemOpsDTO:
    return OrderItemOpsDTO(
        item_id=MLA[item_id],
        variation_id=None,
        seller_sku=None,
        title="Producto de prueba",
        quantity=1,
        unit_price=precio,
        full_unit_price=precio,
        sale_fee=0.0,
        listing_type_id="gold_special",
    )


def _vender(engine: Engine, item_id: int, cuando: datetime) -> int:
    """An ML sale of `item_id` at `cuando` (UTC) as ingestion stores it, frozen by `congelar`."""
    order_id = next(_orders)
    w.run(
        engine,
        "INSERT INTO ml_orders_ops (order_id, status, date_created) VALUES (:o, 'paid', :c)",
        o=order_id,
        c=cuando,
    )
    with sessionmaker(bind=engine)() as db:
        congelar(db, order_id, [_item(item_id)], fecha_venta_de(cuando))
        db.commit()
    return order_id


def _fila(engine: Engine, order_id: int) -> Optional[tuple]:
    filas = w.rows(
        engine,
        "SELECT costo_origen, moneda, tipo_cambio, tipo_cambio_fecha, costo_unitario_ars, fuente, costo_fecha,"
        " precio_unitario FROM ml_order_item_costos WHERE order_id = :o",
        o=order_id,
    )
    return filas[0] if filas else None


def _recongelar(engine: Engine, item_id: int, desde: Optional[date]) -> int:
    with sessionmaker(bind=engine)() as db:
        n = rc.recongelar(db, item_id, desde, "test")
        db.commit()
    return n


def _art(y: int, m: int, d: int, h: int) -> datetime:
    """`h` o'clock in Buenos Aires (UTC-3), as the UTC instant ML sends."""
    return datetime(y, m, d, h, tzinfo=UTC) + timedelta(hours=3)


# --- A: the freeze at the sale date ---------------------------------------------------------------------------


def test_a_sale_freezes_the_costo_si_in_force_on_its_art_day_at_that_days_rate(engine: Engine) -> None:
    """22:00 ART on 10-12 is 01:00 UTC on 10-13, when 22.757 starts: the sale is of 10-12 and takes 23.817."""
    _mundo(engine)
    order = _vender(engine, A, _art(2026, 10, 12, 22))

    assert _fila(engine, order) == (
        D("23.8170"),
        "USD",
        D("1200.0000"),
        date(2026, 10, 12),
        D("28580.4000"),
        "costo_si_pub",
        date(2026, 10, 12),
        D("100000.00"),
    )
    assert _recongelar(engine, A, None) == 0  # the re-freeze computes the very same row (Python vs SQL parity)


def test_an_ars_cost_product_freezes_its_ars_costo_si_with_no_rate(engine: Engine) -> None:
    _mundo(engine)
    order = _vender(engine, ARSP, _art(2026, 10, 20, 10))

    assert _fila(engine, order)[:6] == (D("15000.0000"), "ARS", None, None, D("15000.0000"), "costo_si_pub")
    assert _recongelar(engine, ARSP, None) == 0


def test_a_product_with_no_costo_si_freezes_the_readers_list_cost_with_its_old_fuente(engine: Engine) -> None:
    _mundo(engine)
    order = _vender(engine, SIN, _art(2026, 10, 20, 10))

    assert _fila(engine, order)[:7] == (
        D("40.0000"),
        "USD",
        D("1200.0000"),
        date(2026, 10, 12),
        D("48000.0000"),
        "erp_publicacion",
        date(2026, 10, 20),
    )


def test_a_combo_sale_freezes_its_components_costo_si_times_quantity(engine: Engine) -> None:
    """L19: an ML combo sale is one line with no component breakdown, so the combo is costed as its components."""
    _mundo(engine)
    order = _vender(engine, COMBO, _art(2026, 10, 12, 10))

    assert _fila(engine, order)[:6] == (
        D("47.6340"),
        "USD",
        D("1200.0000"),
        date(2026, 10, 12),
        D("57160.8000"),
        "costo_si_combo",
    )
    assert _recongelar(engine, COMBO, None) == 0


def test_a_usd_cost_with_no_rate_freezes_no_row_and_is_logged(engine: Engine, caplog) -> None:
    """Interface §7: unknown stays unknown (no row, never 0) and is logged."""
    _mundo(engine)
    w.run(engine, "DELETE FROM tipo_cambio")
    with caplog.at_level(logging.WARNING, logger="app.services.ml_orders_ingestion.costeo_service"):
        order = _vender(engine, A, _art(2026, 10, 20, 10))

    assert _fila(engine, order) is None
    assert any("unknown cost" in r.getMessage() and str(A) in r.getMessage() for r in caplog.records)


def test_a_refreeze_with_no_rate_keeps_the_frozen_row_and_is_logged(engine: Engine, caplog) -> None:
    _mundo(engine)
    order = _vender(engine, A, _art(2026, 10, 20, 10))
    antes = _fila(engine, order)
    w.run(engine, "DELETE FROM tipo_cambio")
    with caplog.at_level(logging.WARNING, logger="app.services.ml_orders_ingestion.recongelar_costo_si"):
        assert _recongelar(engine, A, None) == 0

    assert _fila(engine, order) == antes
    assert any("unknown cost" in r.getMessage() and str(A) in r.getMessage() for r in caplog.records)


def test_a_reingestion_never_rewrites_a_frozen_row(engine: Engine) -> None:
    _mundo(engine)
    cuando = _art(2026, 10, 12, 10)
    order = _vender(engine, A, cuando)
    w.run(engine, "UPDATE costo_si_pasos SET promedio_usd = 1 WHERE item_id = :i", i=A)

    with sessionmaker(bind=engine)() as db:
        congelar(db, order, [_item(A)], fecha_venta_de(cuando))
        db.commit()

    assert _fila(engine, order)[0] == D("23.8170")


def test_the_sale_date_is_the_art_calendar_day() -> None:
    assert fecha_venta_de(datetime(2026, 10, 13, 1, tzinfo=UTC)) == date(2026, 10, 12)
    assert fecha_venta_de(datetime(2026, 10, 13, 3, tzinfo=UTC)) == date(2026, 10, 13)
    assert fecha_venta_de(None) is None


# --- B: the re-freeze ------------------------------------------------------------------------------------------


def test_a_costo_si_change_from_d_refreezes_only_the_sales_from_d_and_backs_them_up(engine: Engine) -> None:
    _mundo(engine)
    w.run(engine, "DELETE FROM costo_si_pasos WHERE item_id = :i AND orden = 1", i=A)  # only 23.817 for now
    antes = _vender(engine, A, _art(2026, 10, 12, 10))
    despues_d = _vender(engine, A, _art(2026, 10, 20, 10))
    otro = _vender(engine, OTRO, _art(2026, 10, 20, 10))
    fila_antes, fila_otro = _fila(engine, antes), _fila(engine, otro)
    _paso(engine, A, 1, date(2026, 10, 13), "22.75700")  # a late invoice: 22.757 from 10-13
    # Only from d: a sale before it keeps its frozen cost even if the reader would now say otherwise there.
    w.run(engine, "UPDATE costo_si_pasos SET promedio_usd = 20 WHERE item_id = :i AND orden = 0", i=A)

    assert _recongelar(engine, A, date(2026, 10, 13)) == 1

    assert _fila(engine, despues_d) == (
        D("22.7570"),
        "USD",
        D("1200.0000"),
        date(2026, 10, 12),
        D("27308.4000"),
        "costo_si_pub",
        date(2026, 10, 20),
        D("100000.00"),
    )
    assert _fila(engine, antes) == fila_antes
    assert _fila(engine, otro) == fila_otro
    backups = w.rows(
        engine,
        "SELECT order_id, (fila->>'costo_origen')::numeric, (fila->>'precio_unitario')::numeric, motivo, desde"
        " FROM ml_order_item_costos_backups",
    )
    assert backups == [(despues_d, D("23.8170"), D("100000.00"), "test", date(2026, 10, 13))]

    assert _recongelar(engine, A, date(2026, 10, 13)) == 0  # idempotent: T4 may run it again
    assert len(w.rows(engine, "SELECT 1 FROM ml_order_item_costos_backups")) == 1


def test_a_row_whose_costo_si_disappears_goes_back_to_the_list_cost(engine: Engine) -> None:
    _mundo(engine)
    order = _vender(engine, A, _art(2026, 10, 20, 10))
    w.run(engine, "DELETE FROM costo_si_pasos WHERE item_id = :i", i=A)

    assert _recongelar(engine, A, None) == 1
    assert _fila(engine, order)[:6] == (
        D("30.0000"),
        "USD",
        D("1200.0000"),
        date(2026, 10, 12),
        D("36000.0000"),
        "erp_publicacion",
    )


def test_a_list_cost_row_that_stays_list_cost_is_left_as_frozen(engine: Engine) -> None:
    _mundo(engine)
    order = _vender(engine, SIN, _art(2026, 10, 20, 10))
    w.run(engine, "UPDATE productos_erp SET costo = 99 WHERE item_id = :i", i=SIN)

    assert _recongelar(engine, SIN, None) == 0
    assert _fila(engine, order)[0] == D("40.0000")


def test_a_combo_part_costo_si_part_list_cost_is_refrozen_when_its_costo_si_component_changes(
    engine: Engine,
) -> None:
    """The reader labels such a combo 'lista' (one component has no costo SI), but its cost carries the costo SI of
    the other: a change of that one re-costs it (L15). MIX = 1 x A + 1 x SIN."""
    mix = 7106
    _mundo(engine)
    w.run(engine, "DELETE FROM costo_si_pasos WHERE item_id = :i AND orden = 1", i=A)  # A: 23.817 only
    w.producto(engine, mix, costo="0")
    w.run(engine, "UPDATE productos_erp SET iva = 21")
    w.run(engine, "INSERT INTO publicaciones_ml (mla, item_id, activo) VALUES ('MLA7106', :i, true)", i=mix)
    w.run(
        engine,
        "INSERT INTO combo_componentes (combo_item_id, componente_item_id, cantidad) VALUES (:c, :a, 1), (:c, :s, 1)",
        c=mix,
        a=A,
        s=SIN,
    )
    MLA[mix] = "MLA7106"
    try:
        order = _vender(engine, mix, _art(2026, 10, 20, 10))
    finally:
        del MLA[mix]
    assert _fila(engine, order)[4] == D("76580.4000")  # (23.817 + 40) x 1200
    _paso(engine, A, 1, date(2026, 10, 13), "22.75700")  # a late invoice lowers A from 10-13

    assert _recongelar(engine, mix, date(2026, 10, 13)) == 1
    assert _fila(engine, order)[4:6] == (D("75308.4000"), "combo")  # (22.757 + 40) x 1200, still list cost
    assert _recongelar(engine, mix, date(2026, 10, 13)) == 0


def test_after_a_recompute_the_product_and_its_combos_are_queued_then_refrozen(engine: Engine) -> None:
    """End to end from the dispatch `costo_si.queue.drenar` makes (interface §3) to the drain step."""
    _mundo(engine)
    w.run(engine, "DELETE FROM costo_si_pasos WHERE item_id = :i AND orden = 1", i=A)
    venta_a = _vender(engine, A, _art(2026, 10, 20, 10))
    venta_combo = _vender(engine, COMBO, _art(2026, 10, 20, 11))
    _paso(engine, A, 1, date(2026, 10, 13), "22.75700")

    factory = sessionmaker(bind=engine)
    with factory() as db:
        despues.despachar(db, A, date(2026, 10, 13))
        db.commit()
    assert w.rows(engine, "SELECT producto_item_id, desde FROM ml_costo_si_dirty ORDER BY 1") == [
        (A, date(2026, 10, 13)),
        (COMBO, date(2026, 10, 13)),
    ]

    drenado = rc.drenar(factory, datetime.now(UTC) + timedelta(seconds=30), is_transient=lambda e: False)

    assert (drenado.productos, drenado.filas, drenado.fallidos) == (2, 2, {})
    assert _fila(engine, venta_a)[4] == D("27308.4000")
    assert _fila(engine, venta_combo)[4] == D("54616.8000")
    assert w.rows(engine, "SELECT 1 FROM ml_costo_si_dirty") == []


def test_the_earliest_queued_date_wins_and_a_requeue_resets_the_attempts(engine: Engine) -> None:
    _mundo(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        ml_ventas.encolar(db, OTRO, date(2026, 10, 20))
        db.commit()
    w.run(engine, "UPDATE ml_costo_si_dirty SET attempts = 3")
    with factory() as db:
        ml_ventas.encolar(db, OTRO, date(2026, 10, 5))
        ml_ventas.encolar(db, OTRO, date(2026, 10, 25))
        db.commit()

    assert w.rows(engine, "SELECT producto_item_id, desde, attempts FROM ml_costo_si_dirty") == [
        (OTRO, date(2026, 10, 5), 0)
    ]


def test_a_pass_refreezes_at_most_its_limit_and_leaves_the_rest_queued(engine: Engine) -> None:
    _mundo(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        rc.encolar(db, [A, ARSP, OTRO], None)
        db.commit()

    drenado = rc.drenar(factory, datetime.now(UTC) + timedelta(seconds=30), is_transient=lambda e: False, limite=2)

    assert drenado.productos == 2
    assert len(w.rows(engine, "SELECT 1 FROM ml_costo_si_dirty")) == 1


def test_a_failing_product_is_charged_and_the_others_are_refrozen(engine: Engine, monkeypatch) -> None:
    _mundo(engine)
    venta = _vender(engine, OTRO, _art(2026, 10, 20, 10))
    w.run(engine, "UPDATE costo_si_pasos SET promedio_usd = 10 WHERE item_id = :i", i=OTRO)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        rc.encolar(db, [A, OTRO], None)
        db.commit()
    real = rc.recongelar

    def roto(db, item_id, desde, motivo="costo SI"):
        if item_id == A:
            raise RuntimeError("boom")
        return real(db, item_id, desde, motivo)

    monkeypatch.setattr(rc, "recongelar", roto)

    drenado = rc.drenar(factory, datetime.now(UTC) + timedelta(seconds=30), is_transient=lambda e: False)

    assert drenado.productos == 1
    assert drenado.fallidos == {A: "RuntimeError: boom"}
    assert w.rows(engine, "SELECT producto_item_id, attempts, last_error FROM ml_costo_si_dirty") == [
        (A, 1, "RuntimeError: boom")
    ]
    assert _fila(engine, venta)[0] == D("10.0000")


def test_the_callback_module_registers_itself_on_import() -> None:
    despues._cargar()
    assert despues._CALLBACKS["ml_ventas"] is ml_ventas.encolar
    assert costeo_service.FUENTE_COSTO_SI_PUB == "costo_si_pub"
