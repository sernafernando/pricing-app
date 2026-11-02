"""Sell-in cost modes, fuzzed invariants of the money pass (`fifo.asignar` with `Periodo`s) and the repeated-row cases
from the #2004 verification: units never change, earlier sales never move, a pool hands out what the lots hold, and the
next-sale value is what a sale really gets."""

from __future__ import annotations

import random
from datetime import date, timedelta
from decimal import Decimal

from app.services.sell_in import fifo
from app.services.sell_in.fifo import Dinero, Lote, Periodo, Venta, asignar

D0 = date(2026, 9, 1)


def _mundo(rng: random.Random):
    lotes = []
    for i in range(rng.randint(1, 5)):
        cantidad = rng.randint(1, 37)
        monto = Decimal(rng.randint(1, 9_999_999)) / 100
        if rng.random() < 0.4:  # a USD line at its purchase's own rate
            monto = monto * (Decimal(rng.randint(800_000, 1_600_000)) / 1000)
        lotes.append((i + 1, i + 1, D0 + timedelta(days=rng.randint(0, 40)), cantidad, monto))
    ventas = []
    refs = rng.sample(range(1, 500), rng.randint(0, 14))
    for ref in refs:
        unidades = rng.randint(1, 12) * (-1 if rng.random() < 0.2 else 1)
        canal = rng.choice(["fuera", "ml", "tn"])
        ventas.append((canal, ref, D0 + timedelta(days=rng.randint(0, 60)), unidades))
    return lotes, ventas


def _nuevo(lotes, ventas):
    return [Lote(*x) for x in lotes], [Venta(*v) for v in ventas]


def _periodos(rng: random.Random, modos=("fifo", "ponderado", "ultimo")):
    filas = sorted((D0 + timedelta(days=rng.randint(0, 60)), rng.choice(modos)) for _ in range(rng.randint(1, 4)))
    return [Periodo(d, m) for d, m in filas]


def test_units_never_change_under_any_mode() -> None:
    rng = random.Random(7)
    for _ in range(3000):
        lotes, ventas = _mundo(rng)
        l, v = _nuevo(lotes, ventas)
        fifo_ = asignar(l, v)
        modos = asignar(l, v, _periodos(rng))
        assert [(c.compra_item_id, c.canal, c.venta_ref, c.unidades) for c in fifo_] == [
            (c.compra_item_id, c.canal, c.venta_ref, c.unidades) for c in modos
        ]


def test_sales_before_the_earliest_desde_keep_their_fifo_rows() -> None:
    rng = random.Random(11)
    for _ in range(3000):
        lotes, ventas = _mundo(rng)
        l, v = _nuevo(lotes, ventas)
        periodos = _periodos(rng)
        fifo_ = {(c.canal, c.venta_ref, c.compra_item_id): c for c in asignar(l, v)}
        for c in asignar(l, v, periodos):
            if c.fecha_venta < periodos[0].desde:
                assert fifo_[(c.canal, c.venta_ref, c.compra_item_id)] == c


def test_adding_a_later_row_never_touches_sales_before_it() -> None:
    rng = random.Random(13)
    for _ in range(3000):
        lotes, ventas = _mundo(rng)
        l, v = _nuevo(lotes, ventas)
        periodos = _periodos(rng)
        extra = Periodo(
            periodos[-1].desde + timedelta(days=rng.randint(1, 20)), rng.choice(["fifo", "ponderado", "ultimo"])
        )
        sin = {(c.canal, c.venta_ref, c.compra_item_id): c for c in asignar(l, v, periodos)}
        for c in asignar(l, v, [*periodos, extra]):
            if c.fecha_venta < extra.desde:
                assert sin[(c.canal, c.venta_ref, c.compra_item_id)] == c


def test_one_weighted_row_conserves_the_money_of_the_lots_it_uses_up() -> None:
    rng = random.Random(17)
    for _ in range(3000):
        lotes, _ = _mundo(rng)
        l = [Lote(*x) for x in lotes]
        total = sum(x.cantidad for x in l)
        ultimo = max(x.fecha for x in l)
        ventas = [Venta("fuera", 1, ultimo, total)]
        consumos = asignar(l, ventas, [Periodo(D0, "ponderado")])
        assert abs(sum(c.descuento_ars for c in consumos) - sum(x.descuento_ars for x in l)) <= Decimal("0.02")


def test_next_sale_value_matches_what_a_sale_really_gets() -> None:
    """`Dinero.proximo` vs the recompute: one more 1-unit-at-a-time sale block on `hoy`, unit by unit, averaged."""
    rng = random.Random(19)
    malos = []
    for _ in range(4000):
        lotes, ventas = _mundo(rng)
        ventas = [x for x in ventas if x[3] > 0]
        l, v = _nuevo(lotes, ventas)
        periodos = _periodos(rng)
        hoy = D0 + timedelta(days=70)
        previos = asignar(l, v, periodos)
        orden = sorted(l, key=fifo.orden_fifo)
        indice = {x.compra_item_id: i for i, x in enumerate(orden)}
        d = Dinero(orden, periodos)
        for c in sorted(previos, key=lambda c: (c.fecha_venta, c.canal, c.venta_ref, c.compra_item_id)):
            d.fila(c.fecha_venta, indice[c.compra_item_id], c.unidades)
        proximo = d.proximo(hoy)
        if proximo is None:
            continue
        _, monto, sobre, restantes = proximo
        # Take every unit that value promises in one sale after all the others.
        extra = Venta("zz", 9999, hoy, restantes)
        nuevos = [c for c in asignar(l, [*v, extra], periodos) if c.venta_ref == 9999]
        unidades = sum(c.unidades for c in nuevos)
        modo = fifo.periodo_en(periodos, hoy)[1]
        if modo == "fifo":
            continue  # a FIFO line's value is per line and the sale may span lines
        esperado = monto / sobre * restantes
        real = sum(c.descuento_ars for c in nuevos)
        if unidades != restantes or abs(real - esperado) > Decimal("0.02"):
            malos.append((lotes, ventas, periodos, proximo, real, esperado))
    assert not malos, malos[:1]


def test_d5_example_100_left_at_10_plus_10_at_8_gives_110_at_8() -> None:
    a = Lote(1, 1, date(2026, 10, 1), 100, Decimal("1000"))
    b = Lote(2, 2, date(2026, 10, 10), 10, Decimal("80"))
    consumos = asignar([a, b], [Venta("fuera", 1, date(2026, 10, 20), 110)], [Periodo(date(2026, 10, 1), "ultimo")])
    assert sum(c.descuento_ars for c in consumos) == Decimal("880.00")


def test_a_second_weighted_row_is_a_no_op_for_a_weighted_product() -> None:
    """D4: "The pool hands out exactly what the lots hold". D8 adds a `ponderado` row per load with PPP ticked, so a
    product already weighted gets another row at the new purchase's date. 100 at 10, 100 at 8, 100 sold at 9 (900),
    then a new lot of 100 at 6: the pool holds 900 + 600 over 200 units, 7.50 each."""
    oct1, oct2, oct10, oct15, oct20 = (date(2026, 10, d) for d in (1, 2, 10, 15, 20))
    lotes = [
        Lote(1, 1, oct1, 100, Decimal("1000")),
        Lote(2, 2, oct2, 100, Decimal("800")),
        Lote(3, 3, oct15, 100, Decimal("600")),
    ]
    ventas = [Venta("fuera", 1, oct10, 100), Venta("fuera", 2, oct20, 200)]
    una = [Periodo(oct2, "ponderado")]
    dos = [*una, Periodo(oct15, "ponderado")]

    def total(periodos):
        return sum(c.descuento_ars for c in asignar(lotes, ventas, periodos))

    assert total(una) == Decimal("2400.00")  # all that the lots hold
    assert total(dos) == Decimal("2400.00")


def test_a_fifo_row_on_a_fifo_product_changes_no_cent() -> None:
    rng = random.Random(23)
    for _ in range(3000):
        lotes, ventas = _mundo(rng)
        l, v = _nuevo(lotes, ventas)
        assert asignar(l, v, [Periodo(D0 + timedelta(days=rng.randint(0, 60)), "fifo")]) == asignar(l, v)


def test_a_used_up_lot_of_a_few_thousandths_never_leaves_a_negative_row() -> None:
    # 0.125 rounds up to 0.13 on its only unit: the half cent it never held must not reach the pool as -0.005.
    a = Lote(1, 1, date(2026, 10, 1), 1, Decimal("0.125"))
    b = Lote(2, 2, date(2026, 10, 2), 1, Decimal("0"))
    ventas = [Venta("fuera", 1, date(2026, 10, 5), 1), Venta("fuera", 2, date(2026, 10, 20), 1)]
    filas = asignar([a, b], ventas, [Periodo(date(2026, 10, 10), "ponderado")])
    assert [c.descuento_ars for c in filas] == [Decimal("0.13"), Decimal("0.00")]
