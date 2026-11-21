"""Ventas por fuera after a costo SI recompute (owner L15; sell-in-costo-si T3 PR 9; orchestrator option b).

`queue.drenar` recomputes a product and calls the `ventas_fuera` callback inside the same transaction: every PDF line of
the product and of the combos containing it dated on or after the first changed date is recosted from costo SI, the
previous values are backed up first in `costo_si_backups` (motivo 'ventas_fuera precio_costo'), lines with a manual
cost are skipped, and it is atomic: if the callback fails, the new average is rolled back too and the product stays
queued. Invented data.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Iterator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import sessionmaker

from app.models.sell_dirty import SellDirty
from app.services.costo_si import despues, lote, queue
from app.services.costo_si.despues import ventas_fuera
from app.services.sell import queue as sell_queue
from tests.services.costo_si import _world as w
from tests.services.ventas_fuera_pdf import _mundo as m

pytestmark = pytest.mark.postgres

P, OTRO, COMBO, COMBO_DESGLOSADO = 5601, 5602, 5610, 5611
DESDE = date(2026, 10, 1)  # the bono's start: the first date the recompute changes
CENTINELA = Decimal("1.00")  # what the lines store before the drain, so a recost is visible


def _tablas() -> list:
    vistas, tablas = set(), []
    for tabla in [*w.TABLES, *m.TABLAS, SellDirty.__table__]:
        if tabla.name not in vistas:
            vistas.add(tabla.name)
            tablas.append(tabla)
    return tablas


_STUBS = [s for s in w.STUBS if "usuarios" not in s] + m.STUBS
# Only the PDF line triggers of the sell queue: the recost queues each written line in `sell_dirty`.
_PDF_TRIGGERS = [
    s for s in sell_queue.UPGRADE_SQL if "ventas_fuera_operacion_lineas" in s or "sell_dirty_enqueue_pdf_linea" in s
]


def _install(engine: Engine) -> None:
    w.install(engine)
    with engine.begin() as conn:
        for statement in _PDF_TRIGGERS:
            conn.execute(text(statement))


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    from tests.services.sell._schema import throwaway_schema

    with throwaway_schema("costo_si_vpf", _tablas(), _STUBS, after=_install) as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(despues, "_CALLBACKS", {"ventas_fuera": ventas_fuera.recostear_desde})
    monkeypatch.setattr(despues, "_cargados", True)
    yield
    w.run(engine, "DROP TRIGGER IF EXISTS falla_backup ON costo_si_backups")
    w.run(
        engine,
        "TRUNCATE ventas_fuera_linea_overrides, ventas_fuera_operacion_lineas, ventas_fuera_operaciones,"
        " ventas_fuera_pdf_cargas, sell_dirty CASCADE",
    )
    w.clean(engine)


def _drenar(engine: Engine) -> queue.Drenado:
    return queue.drenar(
        sessionmaker(bind=engine, autoflush=False),
        datetime.now(UTC) + timedelta(minutes=1),
        is_transient=lambda exc: False,
    )


def _venta(engine: Engine, numero: int, fecha: date, renglones: list[tuple[int, str]]) -> list[int]:
    """A PDF document of `fecha` with lines `(item_id, cantidad)`, each storing `CENTINELA` as Precio Costo."""
    with engine.begin() as conn:
        carga = conn.execute(
            text(
                "INSERT INTO ventas_fuera_pdf_cargas (empresa, desde, hasta, documentos, reemplazados, avisos)"
                " VALUES ('EMPRESA EJEMPLO SA', :f, :f, 1, 0, '[]') RETURNING id"
            ),
            {"f": fecha},
        ).scalar()
        op = conn.execute(
            text(
                "INSERT INTO ventas_fuera_operaciones (carga_id, empresa, vendedor, cliente, tipo, letra, punto_venta,"
                " numero, fecha, importe, saldo, total_lineas, recargo_financiero)"
                " VALUES (:c, 'EMPRESA EJEMPLO SA', 'Vendedor Uno', 'CLIENTE EJEMPLO', 'Fc', 'A', 9, :n, :f, 0, 0, 0, 0)"
                " RETURNING id"
            ),
            {"c": carga, "n": numero, "f": fecha},
        ).scalar()
        return [
            conn.execute(
                text(
                    "INSERT INTO ventas_fuera_operacion_lineas (operacion_id, renglon, item_id, articulo, cantidad,"
                    " moneda, precio, precio_costo, precio_costo_pp) VALUES (:o, :r, :i, 'ARTICULO EJEMPLO', :q, 'ARS',"
                    " 1000, :pc, 0) RETURNING id"
                ),
                {"o": op, "r": r, "i": item_id, "q": Decimal(cantidad), "pc": CENTINELA},
            ).scalar()
            for r, (item_id, cantidad) in enumerate(renglones, start=1)
        ]


def _costos(engine: Engine) -> dict[int, Decimal]:
    return dict(w.rows(engine, "SELECT id, precio_costo FROM ventas_fuera_operacion_lineas"))


def _esperado(engine: Engine, item_id: int, fecha: date, cantidad: str) -> Decimal:
    """What the reader says the line costs after the recompute."""
    with sessionmaker(bind=engine)() as db:
        costo = lote.en_fechas(db, [(item_id, fecha)])[(item_id, fecha)].costo_ars
    return (costo * Decimal(cantidad)).quantize(Decimal("0.01"))


def _mundo(engine: Engine) -> dict[str, int]:
    """P (USD, list 25) gets a 3.6 % brand loyalty from 10-01: the drain recomputes it from 10-01. COMBO = 2 x P;
    COMBO_DESGLOSADO = P, sold with its breakdown. Lines: P on 09-20 (before the change), P x2 and P x1 on 10-05, OTRO
    on 10-05, COMBO on 10-06, COMBO_DESGLOSADO + P on 10-07, one P line with a manual cost on 10-08."""
    w.producto(engine, P, costo="25")
    w.producto(engine, OTRO, marca="OTRA MARCA", costo="40")
    w.producto(engine, COMBO, marca="OTRA MARCA")
    w.producto(engine, COMBO_DESGLOSADO, marca="OTRA MARCA")
    w.costo_lista(engine, P, datetime(2026, 9, 1), "25")
    w.costo_lista(engine, OTRO, datetime(2026, 9, 1), "40")
    w.tipo_cambio(engine, date(2026, 9, 1), 1000)
    w.run(
        engine,
        "INSERT INTO combo_componentes (combo_item_id, componente_item_id, cantidad) VALUES"
        f" ({COMBO}, {P}, 2), ({COMBO_DESGLOSADO}, {P}, 1)",
    )
    lineas = {}
    (lineas["antes"],) = _venta(engine, 1, date(2026, 9, 20), [(P, "1")])
    lineas["p2"], lineas["p1"], lineas["otro"] = _venta(engine, 2, date(2026, 10, 5), [(P, "2"), (P, "1"), (OTRO, "1")])
    (lineas["combo"],) = _venta(engine, 3, date(2026, 10, 6), [(COMBO, "1")])
    lineas["desglosado"], lineas["parte"] = _venta(engine, 4, date(2026, 10, 7), [(COMBO_DESGLOSADO, "1"), (P, "1")])
    (lineas["manual"],) = _venta(engine, 5, date(2026, 10, 8), [(P, "1")])
    w.run(
        engine,
        "INSERT INTO ventas_fuera_linea_overrides (empresa, tipo, letra, punto_venta, numero, renglon, costo_unitario,"
        " articulo, cantidad, precio, estado)"
        " VALUES ('EMPRESA EJEMPLO SA', 'Fc', 'A', 9, 5, 1, 1, 'ARTICULO EJEMPLO', 1, 1000, 'aplicado')",
    )
    w.run(
        engine,
        "UPDATE ventas_fuera_operacion_lineas SET override_estado = 'aplicado' WHERE id = :i",
        i=lineas["manual"],
    )
    # The combo line already holds its broken-down value (0): it must not change nor be backed up.
    w.run(engine, "UPDATE ventas_fuera_operacion_lineas SET precio_costo = 0 WHERE id = :i", i=lineas["desglosado"])
    w.run(engine, "DELETE FROM sell_dirty")
    w.bono_marca(engine, "3.6", DESDE, date(2026, 12, 31))  # queues P from 10-01
    return lineas


def test_a1_the_drain_recosts_the_lines_from_the_changed_date_and_commits_everything_together(engine: Engine) -> None:
    lineas = _mundo(engine)

    assert _drenar(engine).cambiados == 1

    costos = _costos(engine)
    assert w.pasos(engine, P) != []
    assert costos[lineas["p2"]] == _esperado(engine, P, date(2026, 10, 5), "2") != CENTINELA
    assert costos[lineas["p1"]] == _esperado(engine, P, date(2026, 10, 5), "1")
    assert costos[lineas["combo"]] == _esperado(engine, COMBO, date(2026, 10, 6), "1")
    assert costos[lineas["parte"]] == _esperado(engine, P, date(2026, 10, 7), "1")
    # Untouched: before the changed date, another product, a broken-down combo (L19), a manual cost.
    assert costos[lineas["antes"]] == costos[lineas["otro"]] == costos[lineas["manual"]] == CENTINELA
    assert costos[lineas["desglosado"]] == Decimal("0.00")
    # The line trigger queued exactly the recosted lines, in the same commit.
    recosteadas = sorted(lineas[k] for k in ("p2", "p1", "combo", "parte"))
    assert sorted(r[0] for r in w.rows(engine, "SELECT venta_ref FROM sell_dirty WHERE canal = 'fuera'")) == recosteadas
    assert w.rows(engine, "SELECT count(*) FROM costo_si_dirty") == [(0,)]


def test_a2_a_failing_callback_rolls_back_the_new_average_too_and_keeps_the_product_queued(engine: Engine) -> None:
    """Atomic (interface §3): the VPF backup cannot be written -> no new costo SI step, no line, no backup."""
    lineas = _mundo(engine)
    w.run(
        engine,
        "CREATE OR REPLACE FUNCTION falla_backup() RETURNS trigger AS $$ BEGIN"
        " IF NEW.motivo = 'ventas_fuera precio_costo' THEN RAISE EXCEPTION 'backup caido'; END IF; RETURN NEW; END;"
        " $$ LANGUAGE plpgsql",
    )
    w.run(
        engine,
        "CREATE TRIGGER falla_backup BEFORE INSERT ON costo_si_backups FOR EACH ROW EXECUTE FUNCTION falla_backup()",
    )

    drenado = _drenar(engine)

    assert list(drenado.fallidos) == [P]
    assert w.pasos(engine, P) == []
    assert set(_costos(engine).values()) <= {CENTINELA, Decimal("0.00")}
    assert _costos(engine)[lineas["p2"]] == CENTINELA
    assert w.rows(engine, "SELECT count(*) FROM costo_si_backups") == [(0,)]
    assert w.rows(engine, "SELECT count(*) FROM sell_dirty") == [(0,)]
    [(item, attempts, error)] = w.rows(engine, "SELECT item_id, attempts, last_error FROM costo_si_dirty")
    assert (item, attempts) == (P, 1) and "backup caido" in error


def test_a2b_a_later_step_failing_also_rolls_back_the_recosted_lines(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The callback never commits by itself: a callback that runs after it and fails undoes its writes too."""

    def falla(db, item_id: int, desde: date) -> None:
        raise RuntimeError("otra area caida")

    monkeypatch.setitem(despues._CALLBACKS, "zz_falla", falla)
    lineas = _mundo(engine)

    assert list(_drenar(engine).fallidos) == [P]

    assert w.pasos(engine, P) == []
    assert _costos(engine)[lineas["p2"]] == CENTINELA
    assert w.rows(engine, "SELECT count(*) FROM costo_si_backups") == [(0,)]


def test_a3_after_the_cause_is_fixed_the_retry_lands_and_a_second_drain_changes_nothing(engine: Engine) -> None:
    lineas = _mundo(engine)
    w.run(
        engine,
        "CREATE OR REPLACE FUNCTION falla_backup() RETURNS trigger AS $$ BEGIN RAISE EXCEPTION 'backup caido'; END;"
        " $$ LANGUAGE plpgsql",
    )
    w.run(
        engine,
        "CREATE TRIGGER falla_backup BEFORE INSERT ON costo_si_backups FOR EACH ROW EXECUTE FUNCTION falla_backup()",
    )
    _drenar(engine)
    w.run(engine, "DROP TRIGGER falla_backup ON costo_si_backups")

    assert _drenar(engine).cambiados == 1
    assert _costos(engine)[lineas["p2"]] == _esperado(engine, P, date(2026, 10, 5), "2")
    backups = w.rows(engine, "SELECT count(*) FROM costo_si_backups WHERE motivo = 'ventas_fuera precio_costo'")
    w.run(engine, "DELETE FROM sell_dirty")

    w.run(engine, "INSERT INTO costo_si_dirty (item_id, desde) VALUES (:i, :d)", i=P, d=DESDE)
    _drenar(engine)

    assert w.rows(engine, "SELECT count(*) FROM costo_si_backups WHERE motivo = 'ventas_fuera precio_costo'") == backups
    assert w.rows(engine, "SELECT count(*) FROM sell_dirty") == [(0,)]


def test_a4_one_backup_row_holds_exactly_every_changed_line_before_and_after(engine: Engine) -> None:
    lineas = _mundo(engine)
    antes = _costos(engine)

    _drenar(engine)

    [(item_id, desde, pasos)] = w.rows(
        engine, "SELECT item_id, desde, pasos FROM costo_si_backups WHERE motivo = 'ventas_fuera precio_costo'"
    )
    despues_ = _costos(engine)
    assert (item_id, desde) == (P, DESDE)
    cambiadas = {lineas[k] for k in ("p2", "p1", "combo", "parte")}
    assert {p["linea_id"] for p in pasos} == cambiadas
    for p in pasos:
        assert Decimal(p["precio_costo_antes"]) == antes[p["linea_id"]]
        assert Decimal(p["precio_costo_despues"]) == despues_[p["linea_id"]]
    # Undo: restoring every "antes" gives back the table as it was before the drain.
    for p in pasos:
        w.run(
            engine,
            "UPDATE ventas_fuera_operacion_lineas SET precio_costo = :v WHERE id = :i",
            v=Decimal(p["precio_costo_antes"]),
            i=p["linea_id"],
        )
    assert _costos(engine) == antes


def test_nothing_to_recost_writes_no_backup(engine: Engine) -> None:
    w.producto(engine, P, costo="25")
    w.costo_lista(engine, P, datetime(2026, 9, 1), "25")
    w.tipo_cambio(engine, date(2026, 9, 1), 1000)
    _venta(engine, 1, date(2026, 9, 20), [(P, "1")])  # before the change only
    w.bono_marca(engine, "3.6", DESDE, date(2026, 12, 31))

    assert _drenar(engine).cambiados == 1
    assert w.rows(engine, "SELECT count(*) FROM costo_si_backups WHERE motivo = 'ventas_fuera precio_costo'") == [(0,)]


def test_the_callback_is_registered_when_the_package_loads(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(despues, "_CALLBACKS", {})
    monkeypatch.setattr(despues, "_cargados", False)
    import importlib

    importlib.reload(ventas_fuera)
    despues._cargar()

    assert despues._CALLBACKS["ventas_fuera"] is ventas_fuera.recostear_desde
