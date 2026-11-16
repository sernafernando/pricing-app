"""A USD sell-in cost bonus of a tactical (tactical sell in USD S1-S3).

Owner: "vos elegís un tipo de moneda para el sell in y un tipo de cambio qué importa en qué se cargó la factura?". A
tactical line in USD per unit, or with a money cap, becomes a USD cost bonus: each sale converts at the tactical's
rate type (P1 = C) — `fijo` its fixed rate, `dia_venta` the BNA of the sale date, `al_cobro` the latest BNA until the
rate the brand paid at is loaded on the tactical's collection (`tactical_cobranzas.tipo_cambio`, "Ponelo donde se
carga el cobro"). The money cap counts USD (P2 = A, "En dólares"). Each row keeps its USD amount and the rate; its
ARS discount is that USD amount at that rate, like sell out's rows.

Postgres only, in a throwaway schema (`_bono_world`)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Iterator, Optional

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import sessionmaker

from app.services.sell_in import bonos_costo
from tests.services.sell_in import _bono_world as b
from tests.services.sell_in import _world as w

D = date


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with b.world("sell_in_bonos_costo_usd") as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    yield
    b.clean(engine)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM tactical_cobranzas"))
        conn.execute(text("DELETE FROM tacticals"))


def _tactical(engine: Engine, tc_modo: str, tipo_cambio: Optional[str] = None) -> int:
    with engine.begin() as conn:
        return conn.execute(
            text(
                "INSERT INTO tacticals (tipo, nombre, marca, fecha_desde, fecha_hasta, moneda, tc_modo, tipo_cambio, "
                "usuario_id) VALUES ('sell_in', 'Synthetic', 'TP-LINK', :d, :h, 'USD', :m, :tc, 7) RETURNING id"
            ),
            {"d": D(2026, 10, 1), "h": D(2026, 10, 31), "m": tc_modo, "tc": tipo_cambio},
        ).scalar()


def _cobro(engine: Engine, tactical_id: int, tipo_cambio: Optional[str]) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO tactical_cobranzas (tactical_id, fecha_cobro, tipo_cambio, usuario_id) "
                "VALUES (:t, :f, :tc, 7)"
            ),
            {"t": tactical_id, "f": D(2026, 11, 5), "tc": tipo_cambio},
        )


def _bono_usd(
    engine: Engine,
    tactical_id: int,
    *,
    monto_unit: Optional[str] = "10.00",
    porcentaje: Optional[str] = None,
    tope_unidades: Optional[int] = None,
    tope_monto: Optional[str] = None,
) -> int:
    with engine.begin() as conn:
        return conn.execute(
            text(
                "INSERT INTO sell_in_bonos_marca (base, alcance, marca, tipo, porcentaje, monto_unit, moneda, "
                "fecha_desde, fecha_hasta, estado, tope_unidades, tope_monto, usuario_id, tactical_id, tactical_linea) "
                "VALUES ('costo_venta', 'marca', 'TP-LINK', :tipo, :pct, :mu, 'USD', :d, :h, 'activa', :tu, :tm, 7, "
                ":t, 1) RETURNING id"
            ),
            {
                "tipo": "por_unidad" if porcentaje is None else "porcentaje",
                "pct": porcentaje,
                "mu": monto_unit if porcentaje is None else None,
                "d": D(2026, 10, 1),
                "h": D(2026, 10, 31),
                "tu": tope_unidades,
                "tm": tope_monto,
                "t": tactical_id,
            },
        ).scalar()


def _fuera(engine: Engine, unidades: int, dia: date, costo_unit: str = "50000.00") -> int:
    ref = w.venta(engine, "fuera", 2964, unidades, dia)
    w.update_venta(engine, "fuera", ref, costo_total=Decimal(costo_unit) * unidades)
    return ref


def _recalcular(engine: Engine, *bono_ids: int) -> bonos_costo.CostoResult:
    with sessionmaker(bind=engine)() as db:
        result = bonos_costo.recalcular(db, bono_ids=bono_ids)
        db.commit()
    return result


def _filas(engine: Engine):
    """`(venta_ref, unidades, descuento_ars, monto_usd, tc_venta)` in sale order."""
    with engine.connect() as conn:
        return [
            tuple(r)
            for r in conn.execute(
                text(
                    "SELECT venta_ref, unidades, descuento_ars, monto_usd, tc_venta FROM sell_in_bono_consumos "
                    "ORDER BY fecha_venta, venta_ref"
                )
            )
        ]


@pytest.mark.postgres
class TestTasaPorModo:
    def test_fijo_converts_every_sale_at_the_tacticals_fixed_rate(self, engine: Engine) -> None:
        bono = _bono_usd(engine, _tactical(engine, "fijo", "1000.000000"), monto_unit="10.91")
        b.tipo_cambio(engine, D(2026, 10, 1), 1500)  # BNA is not used with a fixed rate
        ref = _fuera(engine, 4, D(2026, 10, 5))

        _recalcular(engine, bono)

        assert _filas(engine) == [(ref, 4, Decimal("43640.00"), Decimal("43.64"), Decimal("1000.000000"))]

    def test_dia_venta_converts_each_sale_at_the_bna_of_its_own_date(self, engine: Engine) -> None:
        bono = _bono_usd(engine, _tactical(engine, "dia_venta"))
        b.tipo_cambio(engine, D(2026, 10, 4), 1000)
        b.tipo_cambio(engine, D(2026, 10, 6), 1100)
        b.tipo_cambio(engine, D(2026, 10, 20), 1300)
        antes = _fuera(engine, 1, D(2026, 10, 5))
        despues = _fuera(engine, 2, D(2026, 10, 7))

        _recalcular(engine, bono)

        assert _filas(engine) == [
            (antes, 1, Decimal("10000.00"), Decimal("10.00"), Decimal("1000.000000")),
            (despues, 2, Decimal("22000.00"), Decimal("20.00"), Decimal("1100.000000")),
        ]

    def test_al_cobro_estimates_at_the_latest_bna_until_the_collection_rate_is_loaded(self, engine: Engine) -> None:
        tactical = _tactical(engine, "al_cobro")
        bono = _bono_usd(engine, tactical)
        b.tipo_cambio(engine, D(2026, 10, 4), 1000)
        b.tipo_cambio(engine, D(2026, 11, 10), 1200)
        ref = _fuera(engine, 1, D(2026, 10, 5))

        _recalcular(engine, bono)
        assert _filas(engine) == [(ref, 1, Decimal("12000.00"), Decimal("10.00"), Decimal("1200.000000"))]

        _cobro(engine, tactical, "1350.000000")
        _recalcular(engine, bono)
        assert _filas(engine) == [(ref, 1, Decimal("13500.00"), Decimal("10.00"), Decimal("1350.000000"))]

        b.tipo_cambio(engine, D(2026, 11, 11), 1400)  # once loaded, BNA no longer moves it
        _recalcular(engine, bono)
        assert _filas(engine) == [(ref, 1, Decimal("13500.00"), Decimal("10.00"), Decimal("1350.000000"))]

    def test_a_collection_without_a_rate_keeps_the_estimate(self, engine: Engine) -> None:
        tactical = _tactical(engine, "al_cobro")
        bono = _bono_usd(engine, tactical)
        b.tipo_cambio(engine, D(2026, 10, 4), 1000)
        _cobro(engine, tactical, None)
        ref = _fuera(engine, 1, D(2026, 10, 5))

        _recalcular(engine, bono)

        assert _filas(engine) == [(ref, 1, Decimal("10000.00"), Decimal("10.00"), Decimal("1000.000000"))]

    def test_a_recompute_with_nothing_new_writes_nothing(self, engine: Engine) -> None:
        bono = _bono_usd(engine, _tactical(engine, "dia_venta"))
        b.tipo_cambio(engine, D(2026, 10, 4), 1000)
        _fuera(engine, 2, D(2026, 10, 5))
        _recalcular(engine, bono)

        again = _recalcular(engine, bono)

        assert (again.inserted, again.deleted) == (0, 0)

    def test_without_a_bna_rate_the_bonus_fails_and_writes_nothing(self, engine: Engine) -> None:
        bono = _bono_usd(engine, _tactical(engine, "dia_venta"))
        _fuera(engine, 1, D(2026, 10, 5))

        result = _recalcular(engine, bono)

        assert bono in result.bonos_fallidos
        assert _filas(engine) == []


@pytest.mark.postgres
class TestTopeEnDolares:
    def test_the_money_cap_counts_usd_whatever_each_sales_rate(self, engine: Engine) -> None:
        bono = _bono_usd(engine, _tactical(engine, "dia_venta"), monto_unit="10.00", tope_monto="25.00")
        b.tipo_cambio(engine, D(2026, 10, 4), 1000)
        b.tipo_cambio(engine, D(2026, 10, 6), 2000)
        primera = _fuera(engine, 2, D(2026, 10, 5))
        segunda = _fuera(engine, 2, D(2026, 10, 7))

        _recalcular(engine, bono)

        # 20 USD, then the 5 USD left of the 25 USD cap (one unit, capped at the money left).
        assert _filas(engine) == [
            (primera, 2, Decimal("20000.00"), Decimal("20.00"), Decimal("1000.000000")),
            (segunda, 1, Decimal("10000.00"), Decimal("5.00"), Decimal("2000.000000")),
        ]

    def test_a_percentage_line_with_a_usd_cap_counts_its_ars_discount_in_usd(self, engine: Engine) -> None:
        bono = _bono_usd(engine, _tactical(engine, "fijo", "100.000000"), porcentaje="10.00", tope_monto="1.50")
        ref = _fuera(engine, 3, D(2026, 10, 5), costo_unit="1000.00")  # 100 ARS = 1 USD per unit

        _recalcular(engine, bono)

        assert _filas(engine) == [(ref, 2, Decimal("150.00"), Decimal("1.50"), Decimal("100.000000"))]

    def test_a_unit_never_gets_more_than_its_cost(self, engine: Engine) -> None:
        bono = _bono_usd(engine, _tactical(engine, "fijo", "1000.000000"), monto_unit="10.00")
        ref = _fuera(engine, 1, D(2026, 10, 5), costo_unit="4000.00")  # 10 USD = 10000 ARS > 4000 ARS of cost

        _recalcular(engine, bono)

        assert _filas(engine) == [(ref, 1, Decimal("4000.00"), Decimal("4.00"), Decimal("1000.000000"))]


@pytest.mark.postgres
class TestPesosSinCambio:
    def test_an_ars_cost_bonus_rows_carry_no_usd_amount_nor_rate(self, engine: Engine) -> None:
        bono = b.bono_costo(engine, monto_unit="100.00", tope_monto="150.00")
        b.tipo_cambio(engine, D(2026, 10, 4), 1000)
        ref = _fuera(engine, 2, D(2026, 10, 5))

        _recalcular(engine, bono)

        assert _filas(engine) == [(ref, 2, Decimal("150.00"), None, None)]
