"""After a costo SI recompute (owner L15, plan sell-in-costo-si-t3-paralelo.md Q3): every area registers its own
callback; `drenar` calls each one with (db, product, first changed date) inside the product's transaction, so the new
average and the area's follow-up commit together or not at all. Interface: handoffs/sell-in-costo-si-interfaz.md §3.
Invented data."""

from __future__ import annotations

import pkgutil
import sys
import textwrap
from datetime import UTC, date, datetime, timedelta
from typing import Iterator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import sessionmaker

from app.services.costo_si import despues, queue
from tests.services.costo_si import _world as w

pytestmark = pytest.mark.postgres

P = 5501


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with w.world("costo_si_despues") as engine:
        w.run(engine, "CREATE TABLE IF NOT EXISTS despues_probe (item_id INT, desde DATE, nombre TEXT)")
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(despues, "_CALLBACKS", {})
    monkeypatch.setattr(despues, "_cargados", True)
    yield
    w.clean(engine)
    w.run(engine, "DELETE FROM despues_probe")


def _probe(nombre: str):
    def callback(db, item_id: int, desde: date) -> None:
        db.execute(text("INSERT INTO despues_probe VALUES (:i, :d, :n)"), {"i": item_id, "d": desde, "n": nombre})

    return callback


def _producto_con_sell_in(engine: Engine) -> None:
    w.producto(engine, P)
    w.costo_lista(engine, P, datetime(2026, 9, 1), "25")
    w.bono_marca(engine, "3.6", date(2026, 10, 1), date(2026, 12, 31))  # queues P from 10-01


def _drenar(engine: Engine) -> queue.Drenado:
    return queue.drenar(
        sessionmaker(bind=engine, autoflush=False),
        datetime.now(UTC) + timedelta(minutes=1),
        is_transient=lambda exc: False,
    )


def test_drenar_calls_every_registered_callback_with_the_first_changed_date(engine: Engine) -> None:
    """L15: whatever follows the average learns which product moved and from when."""
    despues.registrar("b", _probe("b"))
    despues.registrar("a", _probe("a"))
    _producto_con_sell_in(engine)

    assert _drenar(engine).cambiados == 1

    assert w.rows(engine, "SELECT item_id, desde, nombre FROM despues_probe ORDER BY nombre") == [
        (P, date(2026, 10, 1), "a"),
        (P, date(2026, 10, 1), "b"),
    ]


def test_nothing_changed_calls_nothing(engine: Engine) -> None:
    despues.registrar("a", _probe("a"))
    _producto_con_sell_in(engine)
    _drenar(engine)
    w.run(engine, "DELETE FROM despues_probe")
    w.run(engine, "INSERT INTO costo_si_dirty (item_id, desde) VALUES (:i, NULL)", i=P)

    assert _drenar(engine).cambiados == 0
    assert w.rows(engine, "SELECT count(*) FROM despues_probe") == [(0,)]


def test_a_failing_callback_rolls_the_recompute_back_and_charges_the_product(engine: Engine) -> None:
    """Atomic: a follow-up that cannot be queued leaves the old average and the product queued for a retry."""

    def falla(db, item_id: int, desde: date) -> None:
        raise RuntimeError("cola caida")

    despues.registrar("a", _probe("a"))
    despues.registrar("z", falla)
    _producto_con_sell_in(engine)

    drenado = _drenar(engine)

    assert list(drenado.fallidos) == [P]
    assert w.pasos(engine, P) == []
    assert w.rows(engine, "SELECT count(*) FROM despues_probe") == [(0,)]
    assert w.rows(engine, "SELECT item_id, attempts, last_error FROM costo_si_dirty") == [
        (P, 1, "RuntimeError: cola caida")
    ]


def test_registering_the_same_name_twice_keeps_one_callback(engine: Engine) -> None:
    """A module imported twice registers once."""
    despues.registrar("a", _probe("a"))
    despues.registrar("a", _probe("a"))
    _producto_con_sell_in(engine)

    _drenar(engine)

    assert w.rows(engine, "SELECT count(*) FROM despues_probe") == [(1,)]


def test_every_module_of_the_package_is_loaded_on_the_first_dispatch(
    engine: Engine, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each PR adds its own file under `costo_si/despues/`: no shared registry to edit. Real loading, on the conftest's
    empty registry: every module of the package (the areas' and a probe) is imported and registers on the first
    dispatch. The areas' callbacks need their own tables, which this world does not have (each is tested in its own
    world), so they are registered as no-ops here; the probe's runs."""
    paquete = list(despues.__path__)
    (tmp_path / "probe_area.py").write_text(
        textwrap.dedent("""
            from sqlalchemy import text
            from app.services.costo_si import despues

            def _cb(db, item_id, desde):
                db.execute(text("INSERT INTO despues_probe VALUES (:i, :d, 'auto')"), {"i": item_id, "d": desde})

            despues.registrar("probe_area", _cb)
        """)
    )
    monkeypatch.setattr(despues, "__path__", [*paquete, str(tmp_path)])
    monkeypatch.setattr(despues, "_cargados", False)
    modulos = [m.name for m in pkgutil.iter_modules(paquete)]
    nuevos = [
        f"{despues.__name__}.{nombre}"
        for nombre in [*modulos, "probe_area"]
        if f"{despues.__name__}.{nombre}" not in sys.modules
    ]
    # The modules this test imports for the first time must not outlive it: they registered no-ops into the conftest's
    # empty registry, so a later test's real loading would find them imported and never register the real callbacks
    # (the legacy metrics hook test failed after this one in CI, #2366).
    for clave in nuevos:
        monkeypatch.setitem(sys.modules, clave, None)
        monkeypatch.delitem(sys.modules, clave)
    for nombre in [*modulos, "probe_area"]:  # imported afresh, so each registration runs again
        monkeypatch.delitem(sys.modules, f"{despues.__name__}.{nombre}", raising=False)
        monkeypatch.delattr(despues, nombre, raising=False)
    registrar = despues.registrar
    registrados = []

    def solo_la_sonda(nombre, fn):
        registrados.append(nombre)
        registrar(nombre, fn if nombre == "probe_area" else lambda *_: None)

    monkeypatch.setattr(despues, "registrar", solo_la_sonda)
    _producto_con_sell_in(engine)

    _drenar(engine)

    assert sorted(registrados) == sorted([*modulos, "probe_area"])
    assert w.rows(engine, "SELECT item_id, nombre FROM despues_probe") == [(P, "auto")]
