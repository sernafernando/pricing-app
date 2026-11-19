"""vpf-costo-d-erp: the recompute command reports by default and only writes with --aplicar and a backup."""

from __future__ import annotations

import json
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


class _Sesion(SimpleNamespace):
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def test_aplicar_backs_up_the_same_changes_it_writes_in_one_call(
    monkeypatch: pytest.MonkeyPatch, tmp_path, capsys: pytest.CaptureFixture
) -> None:
    llamadas = []
    cambios = [_cambio("1000", "900", "1050")]

    def recostear(db, desde, hasta, aplicar=False, respaldo=None):
        llamadas.append(aplicar)
        respaldo(cambios)
        return cambios

    monkeypatch.setattr(script, "SessionLocal", _Sesion)
    monkeypatch.setattr(script, "recostear", recostear)
    backup = tmp_path / "backup.json"

    script.main(["--aplicar", "--backup", str(backup)])

    assert llamadas == [True]
    assert json.loads(backup.read_text()) == [{"id": 1, "precio_costo": "1000"}]
    assert "written: 1 lines" in capsys.readouterr().out


def test_an_existing_backup_file_is_never_overwritten(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(script, "SessionLocal", lambda: pytest.fail("no session over an existing backup"))
    backup = tmp_path / "backup.json"
    backup.write_text("previous")

    with pytest.raises(SystemExit):
        script.main(["--aplicar", "--backup", str(backup)])

    assert backup.read_text() == "previous"


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
        lambda db, desde, hasta, aplicar=False, respaldo=None: (
            llamadas.append(aplicar) or [_cambio("1000", "900", "1050")]
        ),
    )

    script.main(["--desde", "2026-11-01"])

    assert llamadas == [False]
    assert "dry run: nothing written" in capsys.readouterr().out
