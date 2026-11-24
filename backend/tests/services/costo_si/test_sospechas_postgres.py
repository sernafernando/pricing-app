"""Suspicious purchase prices held out of costo SI until reviewed (owner L29), through the real recompute and drain.

Spec: odd/tasks/costo-si-compras-sospechosas.md S1-S3. The case to pin is prod's item 23 / invoice 00128199: an ARS
15.14 unit price on a USD product whose costo SI was ~13.5 (the invoice was loaded wrong). Invented data shaped like
it: a USD product at list cost 13.5355 from a 10 % loyalty starting 10-01, an ARS invoice on 10-27 at 15.14 with that
day's rate 1560, which is USD 0.00971.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Iterator, List, Tuple

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from app.services.costo_si import despues, queue, recompute, sospechas
from tests.services.costo_si import _world as w

pytestmark = pytest.mark.postgres

D = Decimal
ITEM = 5401
ARS = 1


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with w.world("costo_si_sospechas") as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    yield
    w.clean(engine)


def _recalcular(engine: Engine) -> recompute.Resultado:
    with sessionmaker(bind=engine, autoflush=False)() as db:
        resultado = recompute.recalcular(db, ITEM, motivo="test")
        db.commit()
    return resultado


def _caso_item_23(engine: Engine) -> int:
    w.producto(engine, ITEM)
    w.costo_lista(engine, ITEM, datetime(2026, 9, 1), "13.5355")
    w.bono_marca(engine, "10", date(2026, 10, 1), date(2026, 12, 31))
    w.tipo_cambio(engine, date(2026, 10, 27), 1560)
    ct = w.factura(engine, ITEM, date(2026, 10, 27), datetime(2026, 10, 27, 10), 312, "15.14", previo=0, curr_id=ARS)
    w.run(engine, "DELETE FROM costo_si_dirty")
    return ct


def _pasos(engine: Engine) -> List[Tuple]:
    return w.rows(
        engine,
        "SELECT tipo, ct_transaction, cantidad, costo_neto_usd, promedio_usd FROM costo_si_pasos "
        "WHERE item_id = :i ORDER BY orden",
        i=ITEM,
    )


def _revision(engine: Engine) -> List[Tuple]:
    return w.rows(
        engine,
        "SELECT ct_transaction, fecha, cantidad, precio, moneda, referencia, fuente_ref, ratio, estado, revisado_por "
        "FROM costo_si_compras_sospechosas WHERE item_id = :i",
        i=ITEM,
    )


def _decidir(engine: Engine, decision: str, precio: str = "0.00971") -> None:
    w.run(engine, "INSERT INTO usuarios (id) VALUES (7) ON CONFLICT DO NOTHING")
    (sid,) = w.rows(engine, "SELECT id FROM costo_si_compras_sospechosas WHERE item_id = :i", i=ITEM)[0]
    w.run(
        engine,
        "UPDATE costo_si_compras_sospechosas SET estado = :e, revisado_por = 7, revisado_at = now(), "
        "nota = 'test' WHERE id = :id AND precio = :p",
        e=decision,
        id=sid,
        p=D(precio),
    )


def _drenar(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> list:
    llamadas: list = []
    monkeypatch.setitem(despues._CALLBACKS, "probe", lambda db, item, desde: llamadas.append((item, desde)))
    queue.drenar(
        sessionmaker(bind=engine, autoflush=False),
        datetime.now(timezone.utc) + timedelta(minutes=1),
        is_transient=lambda exc: False,
    )
    return llamadas


def test_the_item_23_invoice_is_held_out_listed_and_logged(engine: Engine, caplog: pytest.LogCaptureFixture) -> None:
    ct = _caso_item_23(engine)

    with caplog.at_level(logging.WARNING, logger="app.services.costo_si.sospechas"):
        _recalcular(engine)

    assert _pasos(engine) == [
        # the start: list 13.5355 less the 10 % loyalty in force that day (L39/L40)
        ("inicio", None, 0, D("13.53550"), D("12.18195")),
        ("excluido", ct, 312, D("0.00971"), D("12.18195")),
    ]
    assert _revision(engine) == [
        (ct, date(2026, 10, 27), 312, D("0.00971"), "USD", D("12.18195"), "costo_si", D("0.000797"), "pendiente", None)
    ]
    mensajes = [r.getMessage() for r in caplog.records]
    assert mensajes == [
        f"costo SI: suspicious purchase held out of the average: item {ITEM} invoice {ct} date 2026-10-27 "
        "price 0.00971 USD (invoice ARS 15.140000 at 1560.000000) reference 12.18195 (costo_si)"
    ]
    assert w.encolados(engine) == []  # inserting the row does not requeue the product


def test_the_review_row_keeps_the_price_as_loaded_on_the_invoice_and_its_rate(engine: Engine) -> None:
    """Compras looks for ARS 15,14 on invoice 00128199, not for the USD 0.00971 it converts to at that day's rate."""
    ct = _caso_item_23(engine)
    _recalcular(engine)

    assert w.rows(
        engine,
        "SELECT precio_factura, moneda_factura, tipo_cambio FROM costo_si_compras_sospechosas WHERE ct_transaction = :c",
        c=ct,
    ) == [(D("15.140000"), "ARS", D("1560.000000"))]


def test_a_corrected_invoice_price_is_kept_as_loaded_too(engine: Engine) -> None:
    ct = _caso_item_23(engine)
    _recalcular(engine)

    w.run(engine, "UPDATE tb_item_transactions SET it_price = 16.38 WHERE ct_transaction = :c", c=ct)
    _recalcular(engine)

    assert w.rows(
        engine,
        "SELECT precio_factura, moneda_factura, precio FROM costo_si_compras_sospechosas WHERE item_id = :i",
        i=ITEM,
    ) == [(D("16.380000"), "ARS", D("0.01050"))]


def test_a_second_recompute_changes_nothing(engine: Engine, caplog: pytest.LogCaptureFixture) -> None:
    _caso_item_23(engine)
    _recalcular(engine)
    antes = _revision(engine)
    caplog.clear()

    with caplog.at_level(logging.WARNING, logger="app.services.costo_si.sospechas"):
        resultado = _recalcular(engine)

    assert resultado.desde is None
    assert _revision(engine) == antes
    assert caplog.records == []
    assert w.encolados(engine) == []


def test_accepting_requeues_and_the_purchase_enters_the_average_with_a_backup(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    ct = _caso_item_23(engine)
    _recalcular(engine)

    _decidir(engine, sospechas.ACEPTADA)

    assert w.rows(engine, "SELECT item_id, desde FROM costo_si_dirty") == [(ITEM, date(2026, 10, 27))]
    llamadas = _drenar(engine, monkeypatch)
    # Stock 0 before it: the average restarts at its net-net, 0.0097051 (unrounded) - 10 % loyalty.
    assert _pasos(engine)[1] == ("compra", ct, 312, D("0.00971"), D("0.00873"))
    assert _revision(engine)[0][8:] == ("aceptada", 7)
    assert llamadas == [(ITEM, date(2026, 10, 27))]  # L15: what follows a costo SI change runs
    (backup,) = w.rows(engine, "SELECT pasos FROM costo_si_backups WHERE item_id = :i", i=ITEM)
    assert [p["tipo"] for p in backup[0]] == ["excluido"]


def test_keeping_it_excluded_leaves_the_cost_as_it_was(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    _caso_item_23(engine)
    _recalcular(engine)
    antes = _pasos(engine)

    _decidir(engine, sospechas.EXCLUIDA)
    llamadas = _drenar(engine, monkeypatch)

    assert _pasos(engine) == antes
    assert _revision(engine)[0][8:] == ("excluida", 7)
    assert llamadas == []
    assert w.rows(engine, "SELECT count(*) FROM costo_si_backups") == [(0,)]


def test_a_gbp_correction_to_a_normal_price_drops_the_row_and_the_purchase_enters(engine: Engine) -> None:
    ct = _caso_item_23(engine)
    _recalcular(engine)

    w.run(engine, "UPDATE tb_item_transactions SET it_price = 21114.80 WHERE ct_transaction = :c", c=ct)
    _recalcular(engine)

    assert _pasos(engine)[1] == ("compra", ct, 312, D("13.53513"), D("12.18162"))
    assert _revision(engine) == []


def test_a_corrected_price_on_an_accepted_row_needs_a_new_review(
    engine: Engine, caplog: pytest.LogCaptureFixture
) -> None:
    ct = _caso_item_23(engine)
    _recalcular(engine)
    _decidir(engine, sospechas.ACEPTADA)
    _recalcular(engine)
    assert _pasos(engine)[1][0] == "compra"

    w.run(engine, "UPDATE tb_item_transactions SET it_price = 16.38 WHERE ct_transaction = :c", c=ct)
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="app.services.costo_si.sospechas"):
        _recalcular(engine)

    assert _pasos(engine)[1] == ("excluido", ct, 312, D("0.01050"), D("12.18195"))
    assert _revision(engine) == [
        (ct, date(2026, 10, 27), 312, D("0.01050"), "USD", D("12.18195"), "costo_si", D("0.000862"), "pendiente", None)
    ]
    assert [r.getMessage() for r in caplog.records] == [
        f"costo SI: suspicious purchase changed, back to review: item {ITEM} invoice {ct} date 2026-10-27 "
        "price 0.00971 -> 0.01050 USD reference 12.18195 (costo_si)"
    ]


def test_an_invoice_that_leaves_the_valid_ones_drops_its_row(engine: Engine) -> None:
    ct = _caso_item_23(engine)
    _recalcular(engine)

    w.run(engine, "DELETE FROM v_facturas_compra_vigentes WHERE ct_transaction = :c", c=ct)
    _recalcular(engine)

    assert [p[0] for p in _pasos(engine)] == ["inicio"]
    assert _revision(engine) == []


def test_an_excluded_row_whose_price_changes_goes_back_to_review_and_the_queue_drains(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    ct = _caso_item_23(engine)
    _recalcular(engine)
    _decidir(engine, sospechas.EXCLUIDA)
    _drenar(engine, monkeypatch)

    w.run(engine, "UPDATE tb_item_transactions SET it_price = 16.38 WHERE ct_transaction = :c", c=ct)
    w.run(engine, "SELECT costo_si_encolar(:i, NULL)", i=ITEM)
    _drenar(engine, monkeypatch)

    assert _revision(engine)[0][8:] == ("pendiente", None)
    assert w.encolados(engine) == []  # the reset's requeue lands in the drained row: no loop
    assert _pasos(engine)[1][0] == "excluido"


def test_decidir_refuses_a_stale_price_and_requeues_the_product_on_accept(engine: Engine) -> None:
    _caso_item_23(engine)
    _recalcular(engine)
    w.run(
        engine,
        "INSERT INTO usuarios (id, nombre) VALUES (7, 'Revisor') ON CONFLICT (id) DO UPDATE SET nombre = 'Revisor'",
    )
    (sid,) = w.rows(engine, "SELECT id FROM costo_si_compras_sospechosas WHERE item_id = :i", i=ITEM)[0]

    with sessionmaker(bind=engine, autoflush=False)() as db:
        with pytest.raises(sospechas.PrecioCambiado):
            sospechas.decidir(db, sid, sospechas.ACEPTADA, 7, D("0.0098"))
        db.rollback()
        assert sospechas.decidir(db, 999_999, sospechas.ACEPTADA, 7, D("1")) is None
        db.rollback()
        fila = sospechas.decidir(db, sid, sospechas.ACEPTADA, 7, D("0.009710"), "ok")
        db.commit()

    assert (fila["estado"], fila["revisor"], fila["nota"]) == ("aceptada", "Revisor", "ok")
    assert w.encolados(engine) == [(ITEM, date(2026, 10, 27))]


def test_an_excluded_row_corrected_to_a_normal_price_is_dropped_without_a_requeue(engine: Engine) -> None:
    ct = _caso_item_23(engine)
    _recalcular(engine)
    _decidir(engine, sospechas.EXCLUIDA)
    w.run(engine, "DELETE FROM costo_si_dirty")

    w.run(engine, "UPDATE tb_item_transactions SET it_price = 21114.80 WHERE ct_transaction = :c", c=ct)
    _recalcular(engine)

    assert _revision(engine) == []
    assert _pasos(engine)[1][0] == "compra"
    assert w.encolados(engine) == []
