"""Renewing a sell-out campaign (campaign system, slice B): the pure helpers that propose the renewal's dates and
name. No database."""

from __future__ import annotations

from datetime import date

import pytest

from app.services.sell_out.renovacion import nombre_renovado, siguiente_trimestre


@pytest.mark.parametrize(
    "fecha_hasta,esperado",
    [
        (date(2026, 12, 31), (date(2027, 1, 1), date(2027, 3, 31))),
        (date(2026, 11, 15), (date(2027, 1, 1), date(2027, 3, 31))),
        (date(2026, 10, 1), (date(2027, 1, 1), date(2027, 3, 31))),
        (date(2026, 3, 31), (date(2026, 4, 1), date(2026, 6, 30))),
        (date(2026, 1, 1), (date(2026, 4, 1), date(2026, 6, 30))),
        (date(2026, 6, 30), (date(2026, 7, 1), date(2026, 9, 30))),
        (date(2026, 8, 31), (date(2026, 10, 1), date(2026, 12, 31))),
        (date(2027, 12, 31), (date(2028, 1, 1), date(2028, 3, 31))),
    ],
)
def test_the_next_calendar_quarter_after_the_end_date(fecha_hasta, esperado) -> None:
    assert siguiente_trimestre(fecha_hasta) == esperado


@pytest.mark.parametrize(
    "nombre,desde,esperado",
    [
        # A trailing period advances to the new quarter's.
        ("Rebate Q4 2026", date(2027, 1, 1), "Rebate Q1 2027"),
        ("Rebate 4Q26", date(2027, 1, 1), "Rebate 1Q27"),
        ("Campaña noviembre 2026", date(2027, 1, 1), "Campaña enero 2027"),
        ("Campaña Noviembre 2026", date(2027, 1, 1), "Campaña Enero 2027"),
        ("BONO JULIO 2026", date(2026, 10, 1), "BONO OCTUBRE 2026"),
        ("Bono Q2 2026", date(2026, 7, 1), "Bono Q3 2026"),
        ("Bono 2Q26", date(2026, 7, 1), "Bono 3Q26"),
        ("Bono abril 2026", date(2026, 7, 1), "Bono julio 2026"),
        # Production's names are models and amounts, not periods: unchanged.
        ("MARCA PROGRAM1", date(2027, 1, 1), "MARCA PROGRAM1"),
        ("MARCA PROG 3.0", date(2027, 1, 1), "MARCA PROG 3.0"),
        ("M20 / M80 SP", date(2027, 1, 1), "M20 / M80 SP"),
        ("MODELO 8180", date(2027, 1, 1), "MODELO 8180"),
        ("M60 SDW", date(2027, 1, 1), "M60 SDW"),
        ("m11w/11a", date(2027, 1, 1), "m11w/11a"),
        # A period that is not at the end is not touched either.
        ("Q4 2026 Rebate TP-Link", date(2027, 1, 1), "Q4 2026 Rebate TP-Link"),
    ],
)
def test_the_name_advances_only_a_trailing_period(nombre, desde, esperado) -> None:
    assert nombre_renovado(nombre, desde) == esperado
