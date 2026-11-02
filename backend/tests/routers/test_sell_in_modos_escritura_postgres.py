"""The cost mode change's endpoints on Postgres (`vista_previa_modo`, `confirmar_modo`), called with a real session:
a stale fingerprint answers 409 and writes nothing, and a deadlock with a reconcile that deletes a purchase line (it
deletes the line, cascading to its consumptions, and only then takes the product's lock, which the save already holds
and whose consumption rows it needs) answers a 409 to retry instead of a raw 500. The permission paths and the body
are covered on SQLite (`test_sell_in_modos_escritura_contrato`)."""

from __future__ import annotations

import threading
import time
from datetime import date
from types import SimpleNamespace
from typing import Iterator

import pytest
from fastapi import HTTPException
from sqlalchemy import Engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from app.routers import sell_in_lotes as router
from app.schemas.sell_in_modos import ModoConfirmarIn, ModoIn
from app.services.sell_in.costing import LOCK_NAMESPACE, get_costing
from tests.services.sell_in import _world as si

pytestmark = pytest.mark.postgres

D = date
R = 2964
USUARIO = SimpleNamespace(id=7)
DESDE = D(2026, 10, 15)
REINTENTAR = "Another operation is changing the product right now: try again in a few seconds"


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with si.world("modos_router") as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    # The permissions and the product's existence are the contract file's; here only what Postgres decides.
    monkeypatch.setattr(router, "_validar_cambio", lambda *a, **k: None)
    yield
    si.clean(engine)


def _s(engine: Engine):
    return sessionmaker(bind=engine, autoflush=False)()


def _preview(engine: Engine) -> str:
    with _s(engine) as db:
        return router.vista_previa_modo(R, ModoIn(modo="ponderado", desde=DESDE), db=db, usuario=USUARIO).huella


def _confirm(engine: Engine, huella: str) -> None:
    with _s(engine) as db:
        router.confirmar_modo(R, ModoConfirmarIn(modo="ponderado", desde=DESDE, huella=huella), db=db, usuario=USUARIO)


def _filas(engine: Engine) -> tuple:
    with engine.connect() as c:
        return tuple(
            c.execute(text(q)).scalar()
            for q in (
                "SELECT count(*) FROM sell_in_modos_producto",
                "SELECT count(*) FROM auditoria",
                "SELECT coalesce(sum(descuento_ars), 0) FROM sell_in_consumos",
            )
        )


def _mundo(engine: Engine) -> int:
    si.compra(engine, [(R, 100, "1000.00")], D(2026, 10, 1))
    linea = si.compra(engine, [(R, 100, "800.00")], D(2026, 10, 2))[0]
    si.venta(engine, "fuera", R, 150, D(2026, 10, 20))
    with _s(engine) as db:
        get_costing().recompute(db, [R], isolate_failures=False)
        db.commit()
    return linea


def test_a_stale_fingerprint_answers_409_and_writes_nothing(engine: Engine) -> None:
    _mundo(engine)
    huella = _preview(engine)
    si.venta(engine, "fuera", R, 5, D(2026, 10, 25))
    antes = _filas(engine)

    with pytest.raises(HTTPException) as exc:
        _confirm(engine, huella)

    assert (exc.value.status_code, exc.value.detail) == (409, "The product changed since the preview: preview again")
    assert _filas(engine) == antes


@pytest.mark.parametrize("operacion", ["preview", "confirm"])
def test_a_deadlock_with_a_reconcile_deleting_a_line_answers_409_to_retry(engine: Engine, operacion) -> None:
    linea = _mundo(engine)
    huella = _preview(engine)
    antes = _filas(engine)
    salida: list = []
    reconcile = engine.connect()
    tx = reconcile.begin()
    reconcile.execute(text("DELETE FROM sell_in_compra_items WHERE id = :l"), {"l": linea})

    def salvar() -> None:
        try:
            salida.append(_preview(engine) if operacion == "preview" else _confirm(engine, huella))
        except Exception as exc:  # noqa: BLE001 - the outcome is what the test asserts
            salida.append(exc)

    hilo = threading.Thread(target=salvar)
    hilo.start()
    time.sleep(0.3)  # the save holds the product's lock and waits for the deleted line's consumptions
    try:
        reconcile.execute(text("SELECT pg_advisory_xact_lock(:n, :i)"), {"n": LOCK_NAMESPACE, "i": R})
    except OperationalError:
        pass  # had Postgres picked the reconcile, the save would land; the save waited first, so it is the one
    tx.rollback()  # the reconcile is undone either way: only the save's outcome is under test
    reconcile.close()
    hilo.join(30)

    [res] = salida
    assert isinstance(res, HTTPException), repr(res)
    assert (res.status_code, res.detail) == (409, REINTENTAR)
    assert _filas(engine) == antes
