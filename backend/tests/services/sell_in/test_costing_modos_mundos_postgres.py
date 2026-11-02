"""Sell-in cost modes on real tables (#2004 verification): a pool with a future manual row and lot, a future fifo row,
and random worlds where `vigentes` is what a real sale gets."""

from __future__ import annotations
import random
from datetime import timedelta
from decimal import Decimal

import pytest
from app.services.sell_in import visor_lotes
from app.services.sell_in.costing import get_costing
from tests.services.sell_in import _world as si
from tests.services.sell_in.test_costing_modos_replay_postgres import (  # noqa: F401
    D,
    HOY,
    ROUTER,
    _clean,
    _dos_lotes,
    _recompute,
    _sesion,
    engine,
)

pytestmark = pytest.mark.postgres


def test_repeated_row_real_tables_2400_and_750(engine) -> None:  # noqa: F811
    si.compra(engine, [(ROUTER, 100, "1000.00")], D(2026, 10, 1))
    si.compra(engine, [(ROUTER, 100, "800.00")], D(2026, 10, 2))
    si.modo(engine, ROUTER, "ponderado", D(2026, 10, 2))
    si.venta(engine, "fuera", ROUTER, 100, D(2026, 10, 10))
    si.compra(engine, [(ROUTER, 100, "600.00")], D(2026, 10, 15))
    si.modo(engine, ROUTER, "ponderado", D(2026, 10, 15))
    assert not _recompute(engine, ROUTER).failed
    with _sesion(engine) as db:
        vig = get_costing().vigentes(db, [ROUTER], HOY)[ROUTER]
    assert (vig.descuento_unit_ars, vig.unidades_restantes) == (Decimal("7.500000"), 200)
    si.venta(engine, "fuera", ROUTER, 200, D(2026, 10, 20))
    # a sale before today, so vigentes changes, money doesn't.
    _recompute(engine, ROUTER)
    assert sum(c[5] for c in si.consumos(engine)) == Decimal("2400.00")


def test_pool_today_keeps_its_value_with_a_future_manual_row_before_a_future_lot(engine) -> None:  # noqa: F811
    _dos_lotes(engine)
    si.modo(engine, ROUTER, "ponderado", D(2026, 10, 15))
    si.modo(engine, ROUTER, "manual", D(2026, 11, 20), cantidad=30, costo_unit="52000", costo_base_unit="50000")
    si.compra(engine, [(ROUTER, 10, "60.00")], D(2026, 12, 1))
    assert not _recompute(engine, ROUTER).failed
    with _sesion(engine) as db:
        vig = get_costing().vigentes(db, [ROUTER], HOY)[ROUTER]
    assert (vig.descuento_unit_ars, vig.en_pool, vig.unidades_restantes) == (Decimal("9.000000"), True, 200)


def test_next_line_under_a_future_fifo_row_is_the_lot_at_its_own_value(engine) -> None:  # noqa: F811
    # From Nov 20 each lot is back at its own value, so lot 3 counts from Dec 1 at its own 6.00.
    _dos_lotes(engine)
    si.modo(engine, ROUTER, "ponderado", D(2026, 10, 15))
    si.modo(engine, ROUTER, "fifo", D(2026, 11, 20))
    si.compra(engine, [(ROUTER, 10, "60.00")], D(2026, 12, 1))
    with _sesion(engine) as db:
        prox = visor_lotes.lotes_de_producto(db, ROUTER, HOY).proxima
    assert (prox.descuento_unit, prox.restantes) == (Decimal("9.000000"), 200)
    assert (prox.siguiente.numero, prox.siguiente.descuento_unit) == (3, Decimal("6.000000"))


@pytest.mark.parametrize("semilla", range(12))
def test_random_worlds_vigentes_is_what_a_real_sale_gets(engine, semilla) -> None:  # noqa: F811
    rng = random.Random(semilla)
    malos = []
    for vuelta in range(12):
        base = D(2026, 10, 1)
        fechas = []
        for _ in range(rng.randint(1, 4)):
            f = base + timedelta(days=rng.randint(0, 30))
            q = rng.randint(1, 40)
            fechas.append(f)
            if rng.random() < 0.4:
                monto = str(Decimal(rng.randint(100, 900_000)) / 100)
                si.compra(
                    engine,
                    [(ROUTER, q, monto)],
                    f,
                    moneda="USD",
                    tipo_cambio=str(Decimal(rng.randint(900_000, 1_500_000)) / 1000),
                )
            else:
                si.compra(engine, [(ROUTER, q, str(Decimal(rng.randint(100, 90_000_000)) / 100))], f)
        for _ in range(rng.randint(1, 5)):
            si.modo(
                engine, ROUTER, rng.choice(["fifo", "ponderado", "ultimo"]), base + timedelta(days=rng.randint(-3, 35))
            )
        for _ in range(rng.randint(0, 8)):
            d = base + timedelta(days=rng.randint(0, 38))
            canal = rng.choice(["fuera", "tn"])
            if canal == "fuera" and rng.random() < 0.2:
                si.venta(engine, "fuera", ROUTER, rng.randint(1, 4), d, signo=-1)
            else:
                si.venta(engine, canal, ROUTER, rng.randint(1, 10), d)
        r = _recompute(engine, ROUTER)
        assert not r.failed
        r2 = _recompute(engine, ROUTER)
        assert (r2.inserted, r2.deleted) == (0, 0)
        antes = {c[:5]: c[5] for c in si.consumos(engine)}
        with _sesion(engine) as db:
            vig = get_costing().vigentes(db, [ROUTER], HOY).get(ROUTER)
        if vig is not None and vig.en_pool:
            ref = si.venta(engine, "fuera", ROUTER, vig.unidades_restantes, HOY)
            assert not _recompute(engine, ROUTER).failed
            filas = si.consumos(engine)
            nuevos = [c for c in filas if c[2] == ref]
            real = sum(c[5] for c in nuevos)
            esperado = vig.descuento_unit_ars * vig.unidades_restantes
            if sum(c[4] for c in nuevos) != vig.unidades_restantes or abs(real - esperado) > Decimal("0.03"):
                malos.append((semilla, vuelta, vig, real, esperado))
            for c in filas:
                if c[2] != ref:
                    assert antes[c[:5]] == c[5]
        si.clean(engine)
    assert not malos, malos[:2]


def test_a_stored_sale_after_today_is_behind_the_next_sale(engine) -> None:  # noqa: F811
    # The pool holds 1000 + 200 over 200 units from Nov 20; 10 of them already went at 6.00 on Nov 20, so the next
    # sale gets 6.00 on the 190 left, not the later lot's money over the 90 of the first.
    si.compra(engine, [(ROUTER, 100, "1000.00")], D(2026, 10, 1))
    si.compra(engine, [(ROUTER, 100, "200.00")], D(2026, 11, 20))
    si.modo(engine, ROUTER, "ponderado", D(2026, 10, 1))
    si.venta(engine, "fuera", ROUTER, 10, D(2026, 11, 20))
    assert not _recompute(engine, ROUTER).failed
    with _sesion(engine) as db:
        vig = get_costing().vigentes(db, [ROUTER], HOY)[ROUTER]
    assert (vig.descuento_unit_ars, vig.unidades_restantes, vig.en_pool) == (Decimal("6.000000"), 190, True)
