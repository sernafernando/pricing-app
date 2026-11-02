"""Sell-in cost modes on real tables (#2004 verification): a failed replay keeps the FIFO line, the viewer follows
`en_pool`, nine queries at most, a refused recompute leaves the data alone, future rows, returns, repeated rows."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Iterator

import pytest
from sqlalchemy import Engine, event, text
from sqlalchemy.orm import sessionmaker

from app.models.sell_in import SellInBonoItem
from app.services.productos_sell_in_out import resolver_sell_in_out_batch
from app.services.sell_in import visor_lotes
from app.services.sell_in.costing import get_costing
from tests.services.sell._schema import throwaway_schema
from tests.services.sell_in import _bono_world as bw
from tests.services.sell_in import _world as si
from tests.services.sell_out import _world as so

pytestmark = pytest.mark.postgres

D = date
HOY = D(2026, 11, 10)
ROUTER, SWITCH = 2964, 2270
TABLES = list(dict.fromkeys([*si.TABLES, SellInBonoItem.__table__, *so.TABLES]))
STUBS = [*si.STUBS, so.STUBS[-1]]


def _install(engine: Engine) -> None:
    si.install(engine)
    with engine.begin() as conn:
        for item_id, (marca, categoria, sub, iva) in so.PRODUCTOS.items():
            conn.execute(
                text(
                    "UPDATE productos_erp SET marca = :m, categoria = :c, subcategoria_id = :s, iva = :iva, "
                    "costo = 50000, moneda_costo = 'ARS' WHERE item_id = :i"
                ),
                {"i": item_id, "m": marca, "c": categoria, "s": sub, "iva": iva},
            )


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with throwaway_schema("probe_2004", TABLES, STUBS, after=_install) as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    yield
    si.clean(engine)
    so.clean(engine)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM sell_in_bonos_marca"))


def _sesion(engine: Engine):
    return sessionmaker(bind=engine, autoflush=False)()


def _recompute(engine: Engine, *ids: int):
    with _sesion(engine) as db:
        r = get_costing().recompute(db, ids)
        db.commit()
    return r


def _dos_lotes(engine: Engine) -> tuple[int, int]:
    (diez,) = si.compra(engine, [(ROUTER, 100, "1000.00")], D(2026, 10, 1))
    (ocho,) = si.compra(engine, [(ROUTER, 100, "800.00")], D(2026, 10, 2))
    return diez, ocho


def _manual(engine: Engine) -> int:
    return si.modo(engine, ROUTER, "manual", D(2026, 10, 20), cantidad=30, costo_unit="52000", costo_base_unit="50000")


def test_a_failed_replay_is_never_read_as_used_up_by_the_panels(engine: Engine) -> None:
    diez, _ = _dos_lotes(engine)
    _manual(engine)
    bw.bono_costo(engine, "3.00", desde=D(2026, 11, 1), hasta=D(2026, 11, 30))
    with _sesion(engine) as db:
        batch = resolver_sell_in_out_batch(db, [ROUTER], HOY)
    lote = batch.sell_in[ROUTER]
    assert (lote.compra_item_id, lote.descuento_unit_ars, lote.unidades_restantes, lote.en_pool) == (
        diez,
        Decimal("10.000000"),
        100,
        False,
    )
    assert not batch.bonos_costo.get(ROUTER)


def test_the_viewer_and_the_panels_agree_on_every_mode(engine: Engine) -> None:
    for modo, valor, restantes, en_pool in (
        ("ponderado", Decimal("9.00"), 100, True),
        ("ultimo", Decimal("8.00"), 100, True),
        ("fifo", Decimal("8.00"), 100, False),
    ):
        _dos_lotes(engine)
        si.venta(engine, "fuera", ROUTER, 100, D(2026, 10, 20))
        si.modo(engine, ROUTER, modo, D(2026, 10, 15))
        assert not _recompute(engine, ROUTER).failed
        with _sesion(engine) as db:
            vig = get_costing().vigentes(db, [ROUTER], HOY)[ROUTER]
            prox = visor_lotes.lotes_de_producto(db, ROUTER, HOY).proxima
        assert (vig.descuento_unit_ars, vig.unidades_restantes, vig.en_pool) == (valor, restantes, en_pool), modo
        assert (prox.descuento_unit, prox.restantes) == (valor, restantes), modo
        si.clean(engine)


def test_under_a_pool_only_a_future_lot_comes_after(engine: Engine) -> None:
    _dos_lotes(engine)
    (futuro,) = si.compra(engine, [(ROUTER, 10, "60.00")], D(2026, 12, 1))
    si.modo(engine, ROUTER, "ponderado", D(2026, 10, 15))
    with _sesion(engine) as db:
        prox = visor_lotes.lotes_de_producto(db, ROUTER, HOY).proxima
    assert prox.restantes == 200 and prox.descuento_unit == Decimal("9.00")
    assert prox.siguiente is not None and prox.siguiente.estado == "desde"
    assert prox.siguiente.descuento_unit == Decimal("6.00")


def test_a_future_row_governs_nothing_yet(engine: Engine) -> None:
    diez, _ = _dos_lotes(engine)
    venta = si.venta(engine, "fuera", ROUTER, 40, D(2026, 10, 20))
    _recompute(engine, ROUTER)
    ids = si.consumo_ids(engine)
    filas = si.consumos(engine)
    si.modo(engine, ROUTER, "ponderado", D(2026, 12, 1))

    r = _recompute(engine, ROUTER)

    assert (r.inserted, r.deleted) == (0, 0) and si.consumo_ids(engine) == ids and si.consumos(engine) == filas
    with _sesion(engine) as db:
        vig = get_costing().vigentes(db, [ROUTER], HOY)[ROUTER]
    assert (vig.compra_item_id, vig.descuento_unit_ars, vig.unidades_restantes, vig.en_pool) == (
        diez,
        Decimal("10.000000"),
        60,
        False,
    )
    assert {c[2] for c in filas} == {venta}  # the rows that stayed are that sale's


def test_a_refused_recompute_leaves_every_row_alone(engine: Engine) -> None:
    _dos_lotes(engine)
    (otra,) = si.compra(engine, [(SWITCH, 10, "100.00")], D(2026, 10, 1))
    si.venta(engine, "fuera", ROUTER, 50, D(2026, 10, 20))
    _recompute(engine, ROUTER)
    ids, filas = si.consumo_ids(engine), si.consumos(engine)
    _manual(engine)
    si.venta(engine, "fuera", ROUTER, 5, D(2026, 10, 25))
    si.venta(engine, "fuera", SWITCH, 2, D(2026, 10, 25))

    r = _recompute(engine, ROUTER, SWITCH)

    assert list(r.failed) == [ROUTER]
    assert [x for x in si.consumos(engine) if x[3] == ROUTER] == [x for x in filas if x[3] == ROUTER]
    assert [x[0] for x in si.consumos(engine) if x[3] == SWITCH] == [otra]
    assert si.consumo_ids(engine)[: len(ids)] == ids

    with _sesion(engine) as db:
        with pytest.raises(ValueError):
            get_costing().recompute(db, [ROUTER], isolate_failures=False)
        db.rollback()
    assert [x for x in si.consumos(engine) if x[3] == ROUTER] == [x for x in filas if x[3] == ROUTER]


def test_a_mode_with_a_return_replays_idempotently_and_the_value_stands(engine: Engine) -> None:
    _dos_lotes(engine)
    si.venta(engine, "fuera", ROUTER, 120, D(2026, 10, 20))
    si.venta(engine, "fuera", ROUTER, 30, D(2026, 10, 22), signo=-1)
    si.modo(engine, ROUTER, "ponderado", D(2026, 10, 15))
    assert not _recompute(engine, ROUTER).failed
    r = _recompute(engine, ROUTER)
    assert (r.inserted, r.deleted) == (0, 0)
    with _sesion(engine) as db:
        vig = get_costing().vigentes(db, [ROUTER], HOY)[ROUTER]
    assert vig.unidades_restantes == 110
    assert vig.descuento_unit_ars == Decimal("9.000000")


def test_the_batch_never_reads_more_than_nine_queries(engine: Engine) -> None:
    # Modes (the stored consumptions' read), a product without a lot reached by a cost bonus, a USD campaign.
    _dos_lotes(engine)
    si.venta(engine, "fuera", ROUTER, 10, D(2026, 10, 20))
    si.modo(engine, ROUTER, "ponderado", D(2026, 10, 15))
    _recompute(engine, ROUTER)
    bw.bono_costo(engine, "3.00", desde=D(2026, 11, 1), hasta=D(2026, 11, 30))
    gid = so.grupo(engine, [{"marca": "TP-LINK"}])
    cid = so.campana(engine, [gid], moneda="USD", monto_unit="1.00", tc_modo="dia_venta")
    so.monto_item(engine, cid, ROUTER, "2.00")
    so.tipo_cambio(engine, D(2026, 11, 9), 1000)
    statements: list[str] = []
    with _sesion(engine) as db:
        conn = db.connection()
        event.listen(conn, "before_cursor_execute", lambda *a: statements.append(a[2]))
        batch = resolver_sell_in_out_batch(db, [ROUTER, SWITCH, 950], HOY)
    assert batch.sell_in[ROUTER].en_pool
    assert batch.bonos_costo, "the cost-bonus query must have run for the measure to mean anything"
    assert len(statements) <= 9, "\n---\n".join(statements)


def test_a_product_without_modes_reads_no_stored_rows(engine: Engine) -> None:
    _dos_lotes(engine)
    statements: list[str] = []
    with _sesion(engine) as db:
        conn = db.connection()
        event.listen(conn, "before_cursor_execute", lambda *a: statements.append(a[2]))
        vig = get_costing().vigentes(db, [ROUTER], HOY)[ROUTER]
    assert len(statements) == 3
    assert vig.en_pool is False


def test_a_repeated_weighted_row_keeps_the_pool_on_real_tables(engine: Engine) -> None:
    (a,) = si.compra(engine, [(ROUTER, 100, "1000.00")], D(2026, 10, 1))
    (b,) = si.compra(engine, [(ROUTER, 100, "800.00")], D(2026, 10, 2))
    si.venta(engine, "fuera", ROUTER, 100, D(2026, 10, 10))
    (c,) = si.compra(engine, [(ROUTER, 100, "600.00")], D(2026, 10, 15))
    si.modo(engine, ROUTER, "ponderado", D(2026, 10, 2))
    _recompute(engine, ROUTER)
    with _sesion(engine) as db:
        una = get_costing().vigentes(db, [ROUTER], HOY)[ROUTER].descuento_unit_ars
    si.modo(engine, ROUTER, "ponderado", D(2026, 10, 15))  # the same mode again, from a load with PPP ticked (D8)
    _recompute(engine, ROUTER)
    with _sesion(engine) as db:
        dos = get_costing().vigentes(db, [ROUTER], HOY)[ROUTER].descuento_unit_ars
    assert una == Decimal("7.500000")
    assert dos == una
