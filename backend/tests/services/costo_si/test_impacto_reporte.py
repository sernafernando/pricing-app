"""The T4 dry-run report for the owner (sell-in-costo-si T4, plan §2): money delta per month and channel, sales
re-costed, sales left without a cost, stored markups changed, products the engine could not compute. Invented data,
no database."""

from __future__ import annotations

import csv
from datetime import date
from decimal import Decimal
from pathlib import Path

from app.services.costo_si import impacto, impacto_reporte
from app.services.costo_si.simulacion import TablaSombra

D = Decimal
OCT, NOV = date(2026, 10, 1), date(2026, 11, 1)


def _cambio(item: int, fila: int, mes: date, antes: str, despues) -> impacto.Cambio:
    return impacto.Cambio(
        impacto.CANAL_ML_LEGACY, item, fila, mes, mes, D(antes), None if despues is None else D(despues)
    )


def _informe() -> impacto.Informe:
    pasos = impacto.Pasos(
        filas=[
            {"item_id": 1, "orden": 0, "promedio_usd": D("25.00000")},
            {"item_id": 1, "orden": 1, "promedio_usd": D("22.75700")},
            {"item_id": 5, "orden": 0, "promedio_usd": D("30.00000")},
        ],
        desdes={1: OCT, 2: OCT},
        fallidos={3: "ValueError: invoice 9: no exchange rate for 2026-10-02"},
        alcance=3,
    )
    cambios = [
        _cambio(1, 10, OCT, "80000", "50000"),
        _cambio(1, 11, OCT, "40000", "25000"),
        _cambio(2, 12, NOV, "90000", "95000"),
        _cambio(2, 13, NOV, "30000", None),  # its cost becomes unknown
    ]
    markups = [
        impacto.CambioMarkup(1, "markup_calculado", 10.0, 40.0),
        impacto.CambioMarkup(2, "markup_pvp", D("5.00"), D("3.00")),
    ]
    return impacto.Informe(
        pasos, cambios, markups, [(2, "markup_rebate", "sin_comision")], [TablaSombra("costo_si_pasos", "pasos")]
    )


def test_the_month_and_channel_table_adds_known_costs_and_counts_unknown_ones_apart() -> None:
    filas = impacto_reporte.por_canal_mes(_informe().cambios)

    assert filas == [
        impacto_reporte.FilaMes(impacto.CANAL_ML_LEGACY, OCT, 2, D(120000), D(75000), D(-45000), 0, D(0)),
        impacto_reporte.FilaMes(impacto.CANAL_ML_LEGACY, NOV, 1, D(90000), D(95000), D(5000), 1, D(30000)),
    ]


def test_the_products_with_the_biggest_delta_come_first() -> None:
    top = impacto_reporte.top_productos(_informe().cambios, 10)

    assert [(t.canal, t.item_id, t.filas, t.delta) for t in top] == [
        (impacto.CANAL_ML_LEGACY, 1, 2, D(-45000)),
        (impacto.CANAL_ML_LEGACY, 2, 1, D(5000)),
    ]


def test_the_written_report_holds_every_figure_and_the_controls(tmp_path: Path) -> None:
    impacto_reporte.escribir(_informe(), tmp_path, controles={1: D("22.757"), 2: D("10"), 5: D("31.00")})

    md = (tmp_path / "resumen.md").read_text()
    assert "| ml_legacy | 2026-10 | 2 | 120000.00 | 75000.00 | -45000.00 | 0 | 0.00 |" in md
    assert "| ml_legacy | 2026-11 | 1 | 90000.00 | 95000.00 | 5000.00 | 1 | 30000.00 |" in md
    assert "Products in scope: 3; with costo SI: 2; not computed: 1" in md
    assert "| 3 | ValueError: invoice 9: no exchange rate for 2026-10-02 |" in md
    assert "| 1 | 22.757 | 22.75700 | OK |" in md
    assert "| 2 | 10 | — | NO STEPS |" in md
    assert "| 5 | 31.00 | 30.00000 | DIFF |" in md
    assert "Stored markups changed: 2 (2 products)" in md
    assert "| 2 | markup_rebate | sin_comision |" in md
    assert "costo_si_pasos: pasos" in md
    with (tmp_path / "cambios.csv").open() as f:
        filas = list(csv.DictReader(f))
    assert len(filas) == 4 and filas[3]["despues"] == ""
    with (tmp_path / "markups.csv").open() as f:
        assert [r["campo"] for r in csv.DictReader(f)] == ["markup_calculado", "markup_pvp"]
