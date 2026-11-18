"""vpf-costo-d-erp: the recompute command reports by default and only writes with --aplicar and a backup."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.scripts import recostear_ventas_fuera_erp as script
from app.services.ventas_fuera_pdf.costo_erp import Recosteo


def _cambio(antes: str, despues: str, precio: str, item_id=701) -> Recosteo:
    return Recosteo(1, date(2026, 10, 5), item_id, Decimal("1"), Decimal(precio), Decimal(antes), Decimal(despues))


def test_the_impact_table_counts_lines_costo_d_and_negative_margins() -> None:
    texto = script.resumen([_cambio("1000", "900", "1050"), _cambio("7", "0", "10", item_id=None)])

    assert texto.splitlines() == [
        "lineas que cambian: 2 (con producto, se encolan en sell_dirty: 1)",
        "Costo D: 1,072.46 -> 958.50 (-113.96)",
        "lineas con margen negativo: 1 -> 0",
    ]


def test_aplicar_without_backup_is_refused_before_touching_the_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(script, "SessionLocal", lambda: pytest.fail("no session without --backup"))

    with pytest.raises(SystemExit):
        script.main(["--aplicar"])


def test_by_default_it_is_a_dry_run(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    llamadas = []

    class Sesion(SimpleNamespace):
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    monkeypatch.setattr(script, "SessionLocal", Sesion)
    monkeypatch.setattr(
        script,
        "recostear",
        lambda db, desde, hasta, aplicar=False: llamadas.append(aplicar) or [_cambio("1000", "900", "1050")],
    )

    script.main(["--desde", "2026-11-01"])

    assert llamadas == [False]
    assert "dry run: nothing written" in capsys.readouterr().out
