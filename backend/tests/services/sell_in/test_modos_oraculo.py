"""Sell-in cost modes against an independent exact-fraction oracle (#2004 verification): random worlds with returns and
mixed modes, conservation, backdating, repeated rows, zero-money lots, `proximo` and the next line's value."""

from __future__ import annotations

import random
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from fractions import Fraction

import pytest

from app.services.sell_in import fifo
from app.services.sell_in.fifo import Dinero, Lote, Periodo, Venta, asignar

D0 = date(2026, 9, 1)
MODOS = ("fifo", "ponderado", "ultimo")


def _frac(x) -> Fraction:
    return Fraction(x)


class Oracle:
    """Exact money, no rounding, from the design text only (D2, D4, D5), written apart from `Dinero`."""

    def __init__(self, lotes, periodos):
        self.lotes = lotes  # FIFO order
        # only the last row of a date governs
        ultimos = {}
        for p in periodos:
            ultimos[p.desde] = p
        self.pend = [ultimos[d] for d in sorted(ultimos)]
        self.libres = [x.cantidad for x in lotes]
        self.modo = "fifo"
        self.dentro = 0  # lots inside the pool
        self.v = Fraction(0)

    def own(self, i):
        return _frac(self.lotes[i].descuento_ars) / self.lotes[i].cantidad

    def cuentan(self, f):
        return sum(1 for x in self.lotes if x.fecha <= f)

    def valor(self, i):
        if self.modo == "fifo":
            return self.own(i)
        return self.v if i < self.dentro else self.own(i)

    def _reanclar(self, n):
        self.dentro = n
        self.v = self.own(n - 1) if n else Fraction(0)

    def _pesar(self, n):
        unidades = sum(self.libres[j] for j in range(n))
        plata = sum((self.valor(j) * self.libres[j] for j in range(n)), Fraction(0))
        self.dentro = n
        self.v = plata / unidades if unidades else Fraction(0)

    def unir(self, f):
        n = self.cuentan(f)
        if self.modo == "fifo" or n <= self.dentro:
            return
        if self.modo == "ultimo":
            self._reanclar(n)
        else:
            self._pesar(n)

    def avanzar(self, f):
        while self.pend and self.pend[0].desde <= f:
            p = self.pend.pop(0)
            self.unir(p.desde - timedelta(days=1))
            n = self.cuentan(p.desde)
            if p.modo == "ponderado":
                self._pesar(n)
            elif p.modo == "ultimo":
                self._reanclar(n)
            self.modo = p.modo

    def fila(self, f, i, u):
        self.avanzar(f)
        self.unir(f)
        monto = self.valor(i) * u
        self.libres[i] -= u
        return monto


def mundo(rng, ancho=14, max_lotes=5, cero=False):
    lotes = []
    ids = rng.sample(range(1, 50), rng.randint(1, max_lotes))  # item ids NOT in FIFO order
    for n, i in enumerate(ids):
        cantidad = rng.randint(1, 37)
        if cero and rng.random() < 0.3:
            monto = Decimal(0)
        else:
            monto = Decimal(rng.randint(1, 9_999_999)) / 100
            if rng.random() < 0.5:
                monto = monto * (Decimal(rng.randint(800_000, 1_600_000)) / 1000) / 7
        lotes.append(Lote(i, n + 1, D0 + timedelta(days=rng.randint(0, ancho)), cantidad, monto))
    ventas = []
    refs = rng.sample(range(1, 500), rng.randint(0, 14))
    for ref in refs:
        unidades = rng.randint(1, 12) * (-1 if rng.random() < 0.2 else 1)
        canal = rng.choice(["fuera", "ml", "tn"])
        ventas.append(Venta(canal, ref, D0 + timedelta(days=rng.randint(0, ancho + 6)), unidades))
    return lotes, ventas


def periodos_de(rng, ancho=14, modos=MODOS, lo=-5, n=None):
    filas = sorted(
        (D0 + timedelta(days=rng.randint(lo, ancho + 6)), rng.choice(modos)) for _ in range(n or rng.randint(1, 6))
    )
    return [Periodo(d, m) for d, m in filas]


def por_venta(consumos):
    d = defaultdict(Decimal)
    for c in consumos:
        d[(c.canal, c.venta_ref)] += c.descuento_ars
    return d


def correr_oraculo(lotes, ventas, periodos):
    orden = sorted(lotes, key=fifo.orden_fifo)
    idx = {x.compra_item_id: i for i, x in enumerate(orden)}
    o = Oracle(orden, periodos)
    filas = []
    for c in asignar(lotes, ventas):  # units are mode independent, tested elsewhere
        filas.append(c)
    filas.sort(key=lambda c: (c.fecha_venta, c.canal, c.venta_ref, idx[c.compra_item_id]))
    salida = []
    for c in filas:
        salida.append((c, o.fila(c.fecha_venta, idx[c.compra_item_id], c.unidades)))
    return salida


def test_the_reported_blocker_reproduction() -> None:
    oct1, oct2, oct10, oct15, oct20 = (date(2026, 10, d) for d in (1, 2, 10, 15, 20))
    lotes = [
        Lote(1, 1, oct1, 100, Decimal("1000")),
        Lote(2, 2, oct2, 100, Decimal("800")),
        Lote(3, 3, oct15, 100, Decimal("600")),
    ]
    ventas = [Venta("fuera", 1, oct10, 100), Venta("fuera", 2, oct20, 200)]
    periodos = [Periodo(oct2, "ponderado"), Periodo(oct15, "ponderado")]
    cs = asignar(lotes, ventas, periodos)
    assert sum(c.descuento_ars for c in cs) == Decimal("2400.00")
    assert sum(c.descuento_ars for c in cs if c.venta_ref == 1) == Decimal("900.00")
    d = Dinero(lotes, periodos)
    for c in cs:
        if c.venta_ref == 1:
            d.fila(c.fecha_venta, c.compra_item_id - 1, c.unidades)
    i, monto, sobre, restantes = d.proximo(oct20)
    assert (monto / sobre, restantes) == (Decimal("7.5"), 200)


@pytest.mark.parametrize("ancho", [3, 14, 60])
def test_every_money_row_tracks_the_exact_oracle_with_returns_and_mixed_modes(ancho) -> None:
    rng = random.Random(1000 + ancho)
    malos = []
    for _ in range(12000):
        lotes, ventas = mundo(rng, ancho)
        periodos = periodos_de(rng, ancho)
        reales = asignar(lotes, ventas, periodos)
        clave = lambda c: (c.fecha_venta, c.canal, c.venta_ref, c.compra_item_id)  # noqa: E731
        rmap = {clave(c): c.descuento_ars for c in reales}
        exacto = Fraction(0)
        real = Decimal(0)
        tol = Decimal("0.01") * (len(lotes) + len(periodos) + 2)
        for c, valor in correr_oraculo(lotes, ventas, periodos):
            exacto += valor
            real += rmap[clave(c)]
            if abs(_frac(real) - exacto) > _frac(tol):
                malos.append((lotes, ventas, periodos, c, real, float(exacto)))
                break
    assert not malos, (len(malos), malos[:1])


def test_d4_only_weighted_rows_hand_out_exactly_what_the_lots_hold() -> None:
    rng = random.Random(5)
    for _ in range(8000):
        lotes, _ = mundo(rng)
        total = sum(x.cantidad for x in lotes)
        ultimo = max(x.fecha for x in lotes)
        # Periods begin before any lot, several on one date, repeated.
        periodos = periodos_de(rng, modos=("ponderado",), lo=-5, n=rng.randint(1, 6))
        periodos = [Periodo(D0 - timedelta(days=9), "ponderado"), *periodos]
        ventas = []
        resto = total
        ref = 1
        while resto > 0:
            q = min(resto, rng.randint(1, 20))
            f = ultimo + timedelta(days=1) if resto == q else D0 + timedelta(days=rng.randint(0, 25))
            ventas.append(Venta("fuera", ref, f, q))
            ref += 1
            resto -= q
        # the last sale after every lot, so all is used up... earlier ones may find no units; top up.
        cs = asignar(lotes, ventas, periodos)
        vendidas = sum(c.unidades for c in cs)
        if vendidas < total:
            ventas.append(Venta("fuera", ref, ultimo + timedelta(days=30), total - vendidas))
            cs = asignar(lotes, ventas, periodos)
        assert sum(c.unidades for c in cs) == total
        esperado = sum((x.descuento_ars for x in lotes), Decimal(0)).quantize(Decimal("0.01"), rounding="ROUND_HALF_UP")
        assert sum((c.descuento_ars for c in cs), Decimal(0)) == esperado


def test_d4_fifo_then_weighted_conserves_within_a_cent_per_lot() -> None:
    rng = random.Random(6)
    for _ in range(8000):
        lotes, ventas = mundo(rng)
        ventas = [v for v in ventas if v.unidades > 0]
        total = sum(x.cantidad for x in lotes)
        ultimo = max(max(x.fecha for x in lotes), max((v.fecha for v in ventas), default=D0))
        ventas.append(Venta("zz", 9999, ultimo + timedelta(days=1), total))
        periodos = periodos_de(rng, modos=("fifo", "ponderado"))
        # a fifo row AFTER a pool hands out by the lots' own value: only all-fifo-then-all-ponderado conserves
        corte = rng.randint(-5, 20)
        periodos = [
            *[p for p in periodos if p.desde < D0 + timedelta(days=corte) and p.modo == "fifo"],
            Periodo(D0 + timedelta(days=corte), "ponderado"),
            *[Periodo(p.desde, "ponderado") for p in periodos if p.desde > D0 + timedelta(days=corte)],
        ]
        cs = asignar(lotes, ventas, periodos)
        assert sum(c.unidades for c in cs) == total
        tol = Decimal("0.01") * (len(lotes) + 1)
        assert (
            abs(sum((c.descuento_ars for c in cs), Decimal(0)) - sum((x.descuento_ars for x in lotes), Decimal(0)))
            <= tol
        )


def test_d2_a_backdated_row_keeps_sales_before_it_byte_identical_wherever_it_lands() -> None:
    rng = random.Random(8)
    for _ in range(8000):
        lotes, ventas = mundo(rng)
        periodos = periodos_de(rng)
        extra = Periodo(D0 + timedelta(days=rng.randint(-5, 20)), rng.choice(MODOS))
        conjunto = sorted([*periodos, extra], key=lambda p: p.desde)  # stable: extra after same-date rows of a list
        antes = {(c.canal, c.venta_ref, c.compra_item_id): c for c in asignar(lotes, ventas, periodos)}
        for c in asignar(lotes, ventas, conjunto):
            if c.fecha_venta < extra.desde:
                assert repr(antes[(c.canal, c.venta_ref, c.compra_item_id)]) == repr(c)


def test_rows_never_go_negative_nor_raise_even_with_zero_money_lots() -> None:
    rng = random.Random(9)
    negativos = []
    for _ in range(20000):
        lotes, ventas = mundo(rng, cero=True)
        periodos = periodos_de(rng)
        for c in asignar(lotes, ventas, periodos):
            if c.descuento_ars < 0:
                negativos.append((lotes, ventas, periodos, c))
                break
    assert not negativos, (len(negativos), negativos[:1])


def test_rows_never_go_negative_with_ordinary_lots() -> None:
    rng = random.Random(10)
    for _ in range(20000):
        lotes, ventas = mundo(rng)
        periodos = periodos_de(rng)
        assert all(c.descuento_ars >= 0 for c in asignar(lotes, ventas, periodos))


def test_repeating_the_governing_row_moves_no_money() -> None:
    rng = random.Random(12)
    malos = []
    for _ in range(12000):
        lotes, ventas = mundo(rng)
        periodos = periodos_de(rng)
        i = rng.randrange(len(periodos))
        fin = periodos[i + 1].desde if i + 1 < len(periodos) else periodos[i].desde + timedelta(days=30)
        if fin <= periodos[i].desde:
            continue
        d = periodos[i].desde + timedelta(days=rng.randint(0, (fin - periodos[i].desde).days - 1))
        otro = [*periodos[: i + 1], Periodo(d, periodos[i].modo), *periodos[i + 1 :]]
        a = por_venta(asignar(lotes, ventas, periodos))
        b = por_venta(asignar(lotes, ventas, otro))
        if periodos[i].modo == "fifo" and repr(dict(a)) != repr(dict(b)):
            malos.append(("fifo-moved", lotes, ventas, periodos, d))
        if periodos[i].modo != "fifo":
            # A repeated pool row may shift a rounding cent between sales, never more than a few, never the total.
            diff = sum((abs(a[k] - b[k]) for k in a), Decimal(0))
            if diff > Decimal("0.01") * (2 * len(a) + 2):
                malos.append(("pool-moved", lotes, ventas, periodos, d, diff))
    assert not malos, (len(malos), malos[:1])


def test_a_fifo_row_on_a_fifo_product_moves_zero_cents() -> None:
    rng = random.Random(14)
    for _ in range(20000):
        lotes, ventas = mundo(rng)
        filas = [Periodo(D0 + timedelta(days=rng.randint(-5, 25)), "fifo") for _ in range(rng.randint(1, 4))]
        assert repr(asignar(lotes, ventas, sorted(filas, key=lambda p: p.desde))) == repr(asignar(lotes, ventas))


def test_proximo_says_what_a_sale_really_gets_mixed_modes_with_returns() -> None:
    rng = random.Random(16)
    malos = []
    for _ in range(12000):
        lotes, ventas = mundo(rng)
        periodos = periodos_de(rng)
        hoy = D0 + timedelta(days=rng.randint(21, 40))
        orden = sorted(lotes, key=fifo.orden_fifo)
        idx = {x.compra_item_id: i for i, x in enumerate(orden)}
        d = Dinero(orden, periodos)
        for c in sorted(
            asignar(lotes, ventas, periodos), key=lambda c: (c.fecha_venta, c.canal, c.venta_ref, c.compra_item_id)
        ):
            d.fila(c.fecha_venta, idx[c.compra_item_id], c.unidades)
        prox = d.proximo(hoy)
        if prox is None:
            continue
        i, monto, sobre, restantes = prox
        extra = Venta("zz", 9999, hoy, restantes)
        nuevos = [c for c in asignar(lotes, [*ventas, extra], periodos) if c.venta_ref == 9999]
        real = sum((c.descuento_ars for c in nuevos), Decimal(0))
        unidades = sum(c.unidades for c in nuevos)
        assert unidades == restantes
        assert min(idx[c.compra_item_id] for c in nuevos) == i
        esperado = monto / sobre * restantes
        tol = Decimal("0.02")
        if fifo.periodo_en(periodos, hoy)[1] == "fifo":
            # per line: only the first line's value is promised; `restantes` are that line's units, at its rate.
            tol = Decimal("0.02") + Decimal("0.01")
        if abs(real - esperado) > tol:
            malos.append((lotes, ventas, periodos, hoy, prox, real, esperado))
    assert not malos, (len(malos), malos[:1])


def test_siguiente_is_what_a_sale_on_the_next_lots_date_gets() -> None:
    """`costing.vigentes`' `despues` is `proximo(futuro.fecha)`: replay it the same way against a real extra sale."""
    rng = random.Random(18)
    malos = []
    otra_linea = 0
    for _ in range(12000):
        lotes, ventas = mundo(rng, ancho=30)
        ventas = [v for v in ventas if v.fecha <= D0 + timedelta(days=12)]
        periodos = periodos_de(rng, ancho=30)
        hoy = D0 + timedelta(days=12)
        if fifo.periodo_en(periodos, hoy)[1] == "fifo":
            continue
        orden = sorted(lotes, key=fifo.orden_fifo)
        futuro = next((x for x in orden if x.fecha > hoy), None)
        if futuro is None:
            continue
        idx = {x.compra_item_id: i for i, x in enumerate(orden)}
        d = Dinero(orden, periodos)
        for c in sorted(
            asignar(lotes, ventas, periodos), key=lambda c: (c.fecha_venta, c.canal, c.venta_ref, c.compra_item_id)
        ):
            d.fila(c.fecha_venta, idx[c.compra_item_id], c.unidades)
        if d.proximo(hoy) is None:
            continue
        i, monto, sobre, restantes = d.proximo(futuro.fecha)
        if orden[i].fecha <= hoy and fifo.periodo_en(periodos, futuro.fecha)[1] == "fifo":
            otra_linea += (
                1  # a fifo row before the lot: the value shown is the first line's, under the later line's name
            )
        extra = Venta("zz", 9999, futuro.fecha, 1)
        nuevos = [c for c in asignar(lotes, [*ventas, extra], periodos) if c.venta_ref == 9999]
        real = sum((c.descuento_ars for c in nuevos), Decimal(0))
        if abs(real - monto / sobre) > Decimal("0.02"):
            malos.append((lotes, ventas, periodos, futuro, (monto, sobre), real))
    assert not malos, (len(malos), malos[:1])


def test_ultimo_re_anchors_with_no_sale_in_between() -> None:
    o1, o5, o10, o20 = (date(2026, 10, d) for d in (1, 5, 10, 20))
    a = Lote(1, 1, o1, 100, Decimal("1000"))
    b = Lote(2, 2, o5, 10, Decimal("80"))
    ventas = [Venta("fuera", 1, o20, 110)]
    assert sum(
        c.descuento_ars for c in asignar([a, b], ventas, [Periodo(o1, "ultimo"), Periodo(o10, "ponderado")])
    ) == Decimal("880.00")
    # back to FIFO: each lot its own
    assert sum(
        c.descuento_ars for c in asignar([a, b], ventas, [Periodo(o1, "ultimo"), Periodo(o10, "fifo")])
    ) == Decimal("1080.00")
    assert sum(
        c.descuento_ars for c in asignar([a, b], ventas, [Periodo(o1, "ultimo"), Periodo(o10, "ultimo")])
    ) == Decimal("880.00")


def test_manual_is_refused_only_once_it_governs_or_precedes_a_sale() -> None:
    o1, o5, o10, o20 = (date(2026, 10, d) for d in (1, 5, 10, 20))
    a = Lote(1, 1, o1, 100, Decimal("1000"))
    v = Venta("fuera", 1, o5, 10)
    assert asignar([a], [v], [Periodo(o10, "manual")]) == asignar([a], [v])
    assert asignar([a], [v], [Periodo(o1, "ponderado"), Periodo(o10, "manual")]) == asignar(
        [a], [v], [Periodo(o1, "ponderado")]
    )
    with pytest.raises(ValueError):
        asignar([a], [Venta("fuera", 1, o20, 10)], [Periodo(o10, "manual")])
    # same date, overwritten by a later row: it never governs.
    assert asignar([a], [Venta("fuera", 1, o20, 10)], [Periodo(o10, "manual"), Periodo(o10, "fifo")]) == asignar(
        [a], [Venta("fuera", 1, o20, 10)]
    )
    # a typo mode stays refused too, only once entered
    with pytest.raises(ValueError):
        asignar([a], [Venta("fuera", 1, o20, 10)], [Periodo(o10, "typo")])
