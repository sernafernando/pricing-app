"""Bulk edit preview, recheck of PRs #2014/#2016 kept as regression tests (real Postgres, real sessions).

Deadlocks with the drain or a single write end as Spanish retries, each lock wait gives up with the busy 409, the
"before" side is read inside the rebuild's locks, the pending notice, the drain's stored error text, and more random
seeds of the preview-equals-apply differential. The clock windows are loose (the bound is 2 s; a missing bound would
wait for the 60 s statement timeout). The 500-row timing probe is left out: it measures, it does not check.
"""

from __future__ import annotations

import random
import threading
import time
from collections import Counter
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Callable, Iterator

import pytest
from fastapi import HTTPException
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from app.models.sell_out import SellOutCampana
from app.routers.sell_out_campanas import previa_edicion_masiva
from app.schemas.sell_out import SellOutCampanaItemIn, SellOutEdicionPreviaOut, SellOutEditarMasivoIn
from app.services.sell_out import asignacion, edicion_masiva, queue
from app.services.sell_out import campanas as service
from tests.services.sell_out import _world as w

pytestmark = pytest.mark.postgres

U = 7
ROUTER = 2964
SWITCH = 2270
ROUTERS = {"marca": "TP-LINK", "categoria": "Routers"}
H31 = date(2026, 12, 31)
BUSY_REBUILD = (
    "Otra operación está recalculando o modificando estas campañas en este momento. Reintentar en unos segundos."
)
OCUPADA = "Otra operación está modificando la campaña en este momento. Reintentar en unos segundos."
RECALCULANDO = "La campaña se está recalculando. Reintentar en unos segundos."


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with w.world("recheck") as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    yield
    w.clean(engine)


def _s(engine: Engine) -> Session:
    return sessionmaker(bind=engine, autoflush=False)()


def _drain(engine: Engine) -> None:
    while True:
        with _s(engine) as db:
            ids = queue.claim_batch(db, queue.BATCH_SIZE)
            if not ids:
                return
            asignacion.recalcular(db, ids)
            queue.ack(db, ids)
            db.commit()


def _consumir(engine: Engine) -> None:
    with engine.begin() as c:
        ids = [r[0] for r in c.execute(text("SELECT id FROM sell_out_campanas"))]
    with _s(engine) as db:
        queue.enqueue(db, ids)
        db.commit()
    _drain(engine)


def _tablas(engine: Engine) -> dict:
    with engine.connect() as c:
        schema = c.execute(text("SELECT current_schema()")).scalar()
        nombres = [
            r[0]
            for r in c.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = :s ORDER BY 1"), {"s": schema})
        ]
        return {
            t: c.execute(
                text(
                    f"SELECT count(*), md5(coalesce(string_agg(t::text, chr(10) ORDER BY t::text), '')) FROM \"{t}\" t"
                )
            ).one()
            for t in nombres
        }


def _http_previa(engine: Engine, ids: list[int], **cambios: object) -> tuple[int, object, float]:
    """The router function itself on a real Postgres session: (status, body or detail, seconds)."""
    t = time.monotonic()
    with _s(engine) as db:
        data = SellOutEditarMasivoIn(campana_ids=ids, **cambios)
        try:
            cuerpo = previa_edicion_masiva(data, SimpleNamespace(id=U), db)
            salida = SellOutEdicionPreviaOut.model_validate(cuerpo).model_dump()
            return 200, salida, time.monotonic() - t
        except HTTPException as exc:
            return exc.status_code, exc.detail, time.monotonic() - t


def _espera_advisory(engine: Engine, segundos: float = 5.0) -> None:
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
        fin = time.monotonic() + segundos
        while time.monotonic() < fin:
            n = c.execute(
                text(
                    "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND classid = :ns AND NOT granted "
                    "AND database = (SELECT oid FROM pg_database WHERE datname = current_database())"
                ),
                {"ns": asignacion.LOCK_NAMESPACE},
            ).scalar()
            if n:
                return
            time.sleep(0.01)
    raise AssertionError("the preview never waited for the advisory lock")


class H(threading.Thread):
    def __init__(self, fn: Callable[[], object]) -> None:
        super().__init__(daemon=True)
        self.fn, self.res, self.exc, self.t = fn, None, None, None

    def run(self) -> None:
        t = time.monotonic()
        try:
            self.res = self.fn()
        except BaseException as exc:  # noqa: BLE001
            self.exc = exc
        self.t = time.monotonic() - t


# ── Item 4: void V, preview of a linked campaign during the drain's rebuild ──


@pytest.mark.parametrize("vuelta", range(4))
def test_item4_preview_during_the_rebuild_is_a_spanish_409_nothing_written(engine: Engine, vuelta: int) -> None:
    g = w.grupo(engine, [ROUTERS])
    v = w.campana(engine, [g], nombre="V", acumulable=False)
    a = w.campana(engine, [g], nombre="A", acumulable=False)
    w.venta(engine, "fuera", ROUTER, 2, date(2026, 11, 10))
    _consumir(engine)
    with _s(engine) as db:
        service.anular_campana(db, v, U, "x")
    fila_a = None
    with engine.connect() as c:
        fila_a = c.execute(text("SELECT * FROM sell_out_campanas WHERE id = :a"), {"a": a}).one()
    n_audit = _tablas(engine)["auditoria"]

    drain = _s(engine)
    assert queue.claim_batch(drain, queue.BATCH_SIZE) == [v]
    cierre = asignacion.vinculadas(drain, [v])
    drain.execute(asignacion.LOCK_SQL, {"ns": asignacion.LOCK_NAMESPACE, "ids": cierre})

    p = H(lambda: _http_previa(engine, [a], fecha_hasta=H31))
    p.start()
    _espera_advisory(engine)
    drain_error = None
    try:
        asignacion.recalcular(drain, [v])
        queue.ack(drain, [v])
        drain.commit()
    except DBAPIError as exc:
        drain_error = exc
        drain.rollback()
    finally:
        drain.close()
    p.join(15)
    assert p.exc is None, repr(p.exc)
    status, detail, _ = p.res
    assert (status, detail) == (409, BUSY_REBUILD)
    assert drain_error is None  # the drain keeps going: A got the freed units
    with engine.connect() as c:
        assert c.execute(text("SELECT * FROM sell_out_campanas WHERE id = :a"), {"a": a}).one() == fila_a
    assert _tablas(engine)["auditoria"] == n_audit
    assert [r for r in w.queued(engine) if r[0] == a] == []


def test_item4_natural_race_real_drain_never_a_raw_error(engine: Engine) -> None:
    resultados: Counter = Counter()
    for n in range(10):
        w.clean(engine)
        g = w.grupo(engine, [ROUTERS])
        v = w.campana(engine, [g], nombre="V", acumulable=False)
        a = w.campana(engine, [g], nombre="A", acumulable=False)
        w.venta(engine, "fuera", ROUTER, 2, date(2026, 11, 10))
        _consumir(engine)
        with _s(engine) as db:
            service.anular_campana(db, v, U, "x")
        p = H(lambda: _http_previa(engine, [a], fecha_hasta=H31))
        d = H(lambda: _drain(engine))
        (p if n % 2 else d).start()
        time.sleep(0.002 * n)
        (d if n % 2 else p).start()
        p.join(15), d.join(15)
        assert p.exc is None, repr(p.exc)
        resultados[(p.res[0], type(d.exc).__name__)] += 1
        _drain(engine)
    assert sum(resultados.values()) == 10
    assert all(status in (200, 409) for status, _ in resultados), resultados


# ── Item 5: a preview against a single write of a linked campaign with a queue row ──


def _linkeados(engine: Engine, cual: str) -> tuple[int, int, Callable[[Session], object]]:
    g = w.grupo(engine, [ROUTERS])
    a = w.campana(engine, [g], nombre="A", acumulable=False)
    if cual == "tipo_cambio":
        l_ = w.campana(engine, [g], nombre="L", acumulable=False, moneda="USD", tc_modo="al_cobro")
        w.tipo_cambio(engine, date(2026, 11, 10), 1000.0)
    elif cual == "repartir":
        l_ = w.monto_total(engine, [g], "100", nombre="L", acumulable=False)
        w.reparto(engine, l_, ROUTER, porcentaje="40")
    else:
        l_ = w.campana(engine, [g], nombre="L", acumulable=False)
    w.venta(engine, "fuera", ROUTER, 2, date(2026, 11, 10))
    _consumir(engine)
    with _s(engine) as db:
        queue.enqueue(db, [l_])
        db.commit()

    def escribir(db: Session) -> object:
        if cual == "editar":
            campana = db.get(SellOutCampana, l_)
            data = service.entrada_guardada(db, campana).model_copy(update={"fecha_hasta": date(2026, 12, 1)})
            db.rollback()
            return service.editar_campana(db, l_, data, U)
        if cual == "anular":
            return service.anular_campana(db, l_, U, "x")
        if cual == "tipo_cambio":
            return service.definir_tipo_cambio(db, l_, Decimal("1500"), U)
        return service.repartir(
            db, l_, [SellOutCampanaItemIn(item_id=ROUTER, reparto_porcentaje=Decimal("50"))], U, None
        )

    return a, l_, escribir


@pytest.mark.parametrize("cual", ["editar", "anular", "tipo_cambio", "repartir"])
def test_item5_a_preview_never_gives_a_raw_40P01_to_a_single_write(
    engine: Engine, monkeypatch: pytest.MonkeyPatch, cual: str
) -> None:
    a, _l, escribir = _linkeados(engine, cual)
    listo, soltar = threading.Event(), threading.Event()
    original = edicion_masiva._consumos

    def _pausa(*args: object) -> object:
        if not listo.is_set():
            listo.set()
            assert soltar.wait(30)
        return original(*args)

    monkeypatch.setattr(edicion_masiva, "_consumos", _pausa)
    p = H(lambda: _http_previa(engine, [a], fecha_hasta=date(2026, 11, 5)))
    p.start()
    assert listo.wait(15)

    def _single() -> object:
        with _s(engine) as db:
            return escribir(db)

    e = H(_single)
    e.start()
    time.sleep(0.3)
    soltar.set()
    p.join(15), e.join(15)
    assert p.exc is None, repr(p.exc)
    assert p.res[0] in (200, 409), p.res
    assert e.exc is None or isinstance(e.exc, service.SellOutError), repr(e.exc)


def test_item5_natural_race_edits_and_previews_only_retries(engine: Engine) -> None:
    resultados: Counter = Counter()
    for n in range(12):
        w.clean(engine)
        a, _l, escribir = _linkeados(engine, "editar")

        def _single() -> object:
            with _s(engine) as db:
                return escribir(db)

        p = H(lambda: _http_previa(engine, [a], fecha_hasta=date(2026, 11, 5)))
        e = H(_single)
        (p if n % 2 else e).start()
        time.sleep(0.003 * n)
        (e if n % 2 else p).start()
        p.join(20), e.join(20)
        assert p.exc is None, repr(p.exc)
        assert e.exc is None or isinstance(e.exc, service.SellOutError), repr(e.exc)
        resultados[(p.res[0], type(e.exc).__name__)] += 1
    assert sum(resultados.values()) == 12
    assert all(status in (200, 409) for status, _ in resultados), resultados


# ── Item 6: bounded waits ──


def _mundo_rebuild(engine: Engine, con_cola: bool) -> tuple[int, int]:
    """A (lower id) holds the units of a sale; shortening A gives them to L: the rebuild inserts a new L line."""
    g = w.grupo(engine, [ROUTERS])
    a = w.campana(engine, [g], nombre="A", acumulable=False)
    l_ = w.campana(engine, [g], nombre="L", acumulable=False)
    w.venta(engine, "fuera", ROUTER, 2, date(2026, 11, 10))
    _consumir(engine)
    if con_cola:
        with _s(engine) as db:
            queue.enqueue(db, [l_])
            db.commit()
    return a, l_


@pytest.mark.parametrize(
    ("nombre", "con_cola", "sql"),
    [
        ("selected row", False, "SELECT 1 FROM sell_out_campanas WHERE id = :a FOR UPDATE"),
        ("linked row, no queue row", False, "SELECT 1 FROM sell_out_campanas WHERE id = :l FOR UPDATE"),
        (
            "linked row with a queue row: the rebuild's insert",
            True,
            "SELECT 1 FROM sell_out_campanas WHERE id = :l FOR UPDATE",
        ),
        ("linked queue row", True, "SELECT 1 FROM sell_out_dirty WHERE campana_id = :l FOR UPDATE"),
        (
            "a stored line the rebuild deletes",
            False,
            "SELECT 1 FROM sell_out_consumos WHERE campana_id = :a FOR UPDATE",
        ),
        ("the rebuild's advisory lock of the linked", False, "SELECT pg_advisory_xact_lock(:ns, :l)"),
    ],
)
def test_item6_each_wait_gives_up_in_about_2s_with_the_409(
    engine: Engine, nombre: str, con_cola: bool, sql: str
) -> None:
    a, l_ = _mundo_rebuild(engine, con_cola)
    antes = _tablas(engine)
    holder = _s(engine)
    holder.execute(
        text(sql).bindparams(),
        {k: v for k, v in {"a": a, "l": l_, "ns": asignacion.LOCK_NAMESPACE}.items() if f":{k}" in sql},
    )
    status, detail, t = _http_previa(engine, [a], fecha_hasta=date(2026, 11, 5))
    holder.rollback()
    holder.close()
    assert status == 409, detail
    assert t < 10, t  # gave up at the 2 s bound, not at the statement timeout
    assert _tablas(engine) == antes


def test_item6_second_selected_row_held_stops_in_about_2s(engine: Engine) -> None:
    g = w.grupo(engine, [ROUTERS])
    ids = [w.campana(engine, [g], nombre=f"C{i}") for i in range(4)]
    _consumir(engine)
    holder = _s(engine)
    holder.execute(text("SELECT 1 FROM sell_out_campanas WHERE id = :a FOR UPDATE"), {"a": ids[2]})
    status, detail, t = _http_previa(engine, ids, fecha_hasta=H31)
    holder.rollback()
    holder.close()
    assert status == 409 and t < 10


def test_item6_docstring_single_edit_with_a_queue_row_gets_the_409_after_2s(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    a, l_ = _mundo_rebuild(engine, True)
    listo, soltar = threading.Event(), threading.Event()
    original = edicion_masiva._consumos

    def _pausa(*args: object) -> object:
        if not listo.is_set():
            listo.set()
            assert soltar.wait(30)
        return original(*args)

    monkeypatch.setattr(edicion_masiva, "_consumos", _pausa)
    p = H(lambda: _http_previa(engine, [a], acumulable=True))
    p.start()
    assert listo.wait(15)

    def _single() -> object:
        with _s(engine) as db:
            data = service.entrada_guardada(db, db.get(SellOutCampana, l_)).model_copy(update={"fecha_hasta": H31})
            db.rollback()
            return service.editar_campana(db, l_, data, U)

    e = H(_single)
    e.start()
    e.join(8)
    soltar.set()
    p.join(15)
    assert isinstance(e.exc, service.SellOutRecalculando)
    assert e.t < 10


# ── Item 7: the "before" snapshot inside the rebuild's locks ──


def test_item7_lines_a_drain_commits_while_the_preview_waits_are_not_shown_as_moving(engine: Engine) -> None:
    """V (voided, holds the units), A (selected; its dates miss the sale, so it never gets a new line), L (gets the
    freed units: its queue row is not touched, and the FK's KEY SHARE on L is compatible with the preview's). The
    drain commits L's new line while the preview waits on the advisory lock. A snapshot read before the lock would
    list L with `entran` 1 line; read inside it, L does not move."""
    g = w.grupo(engine, [ROUTERS])
    v = w.campana(engine, [g], nombre="V", acumulable=False)
    a = w.campana(engine, [g], nombre="A", acumulable=False, desde=date(2026, 12, 1), hasta=date(2026, 12, 20))
    l_ = w.campana(engine, [g], nombre="L", acumulable=False)
    w.venta(engine, "fuera", ROUTER, 2, date(2026, 11, 10))
    _consumir(engine)
    assert [c[0] for c in w.consumos(engine)] == [v]
    with _s(engine) as db:
        service.anular_campana(db, v, U, "x")

    drain = _s(engine)
    assert queue.claim_batch(drain, queue.BATCH_SIZE) == [v]
    drain.execute(asignacion.LOCK_SQL, {"ns": asignacion.LOCK_NAMESPACE, "ids": asignacion.vinculadas(drain, [v])})
    p = H(lambda: _http_previa(engine, [a], fecha_hasta=date(2026, 12, 25)))
    p.start()
    _espera_advisory(engine)
    asignacion.recalcular(drain, [v])
    queue.ack(drain, [v])
    drain.commit()
    drain.close()
    p.join(15)
    assert p.exc is None, repr(p.exc)
    assert p.res[0] == 200, p.res
    assert [c[0] for c in w.consumos(engine)] == [l_]
    assert p.res[1]["vinculadas"] == []
    assert p.res[1]["totales"]["entran"]["lineas"] == 0
    assert p.res[1]["totales"]["salen"]["lineas"] == 0


# ── Item 8: pending flags ──


def _sin_banderas(previa: dict) -> dict:
    copia = {k: v for k, v in previa.items() if k != "aviso_pendientes"}
    for lista in ("cambian", "vinculadas"):
        copia[lista] = [{k: v for k, v in f.items() if k != "incluye_pendientes"} for f in copia[lista]]
    return copia


def test_item8_flags_only_with_pending_rows_and_the_numbers_do_not_change(engine: Engine) -> None:
    a, l_ = _mundo_rebuild(engine, False)
    otro = w.campana(engine, [w.grupo(engine, [{"marca": "TP-LINK", "categoria": "Switches"}])], nombre="Otro")
    _consumir(engine)

    s, limpia, _ = _http_previa(engine, [a], fecha_hasta=date(2026, 11, 5))
    assert s == 200 and limpia["aviso_pendientes"] is None
    assert not any(f["incluye_pendientes"] for f in limpia["cambian"] + limpia["vinculadas"])

    # A queue row of a campaign outside the closure: no flag, no notice.
    w.execute(engine, "INSERT INTO sell_out_dirty (campana_id) VALUES (:c)", c=otro)
    s, ajena, _ = _http_previa(engine, [a], fecha_hasta=date(2026, 11, 5))
    assert s == 200 and ajena == limpia
    w.clear_queue(engine)

    # A no-op queue row of the linked one: flagged, numbers identical to the clean run.
    w.execute(engine, "INSERT INTO sell_out_dirty (campana_id) VALUES (:c)", c=l_)
    s, marcada, _ = _http_previa(engine, [a], fecha_hasta=date(2026, 11, 5))
    assert s == 200 and marcada["aviso_pendientes"] == edicion_masiva.AVISO_PENDIENTES
    assert [f["incluye_pendientes"] for f in marcada["vinculadas"]] == [True]
    assert [f["incluye_pendientes"] for f in marcada["cambian"]] == [False]
    assert _sin_banderas(marcada) == _sin_banderas(limpia)


def test_item8_pending_work_of_a_campaign_that_is_not_listed_raises_the_notice(engine: Engine) -> None:
    """M has a queue row but its own lines do not move; the sale it left behind goes to L: noticed, M unlisted."""
    g = w.grupo(engine, [ROUTERS])
    a = w.campana(engine, [g], nombre="A", desde=date(2026, 12, 1), hasta=date(2026, 12, 20))
    m = w.campana(engine, [g], nombre="M", acumulable=False, tope_unidades=1)
    l_ = w.campana(engine, [g], nombre="L", acumulable=False)
    w.venta(engine, "fuera", ROUTER, 1, date(2026, 11, 10))
    w.venta(engine, "fuera", SWITCH, 1, date(2026, 11, 10))
    _consumir(engine)
    w.venta(engine, "fuera", ROUTER, 1, date(2026, 11, 12))
    w.execute(engine, "INSERT INTO sell_out_dirty (campana_id) VALUES (:c)", c=m)
    s, previa, _ = _http_previa(engine, [a], fecha_hasta=date(2026, 12, 25))
    listadas = {f["id"]: f for f in previa["cambian"] + previa["vinculadas"]}
    assert s == 200 and m not in listadas and listadas[l_]["entran"]["lineas"] == 1
    assert previa["aviso_pendientes"] == edicion_masiva.AVISO_PENDIENTES


# ── Item 9: the drain's last_error ──


def test_item9_the_drains_last_error_text_is_the_english_message(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import datetime, timezone

    from app.workers.context import WorkerContext
    from app.workers.handlers.sell_out_drain import drain as handler

    monkeypatch.setattr("app.core.database.SessionLocal", sessionmaker(bind=engine, autoflush=False))
    cid = w.campana(engine, [w.grupo(engine, [ROUTERS])], moneda="USD", tc_modo="dia_venta")
    w.venta(engine, "fuera", ROUTER, 1, date(2026, 11, 2))
    w.clear_queue(engine)
    with _s(engine) as db:
        queue.enqueue(db, [cid])
        db.commit()
    handler.run(WorkerContext(deadline=datetime.now(timezone.utc).replace(year=2100), worker_name="w"))
    fila = [r for r in w.queued(engine) if r[0] == cid][0]
    assert fila[2] == f"SellOutAsignacionError: campaign {cid}: no BNA rate to convert the sale of 2026-11-02"


# ── Item 7, short: seeds beyond the kept 0..39, with counts ──


@pytest.mark.parametrize("seed", range(100, 130))
def test_item7_equivalence_more_seeds(engine: Engine, seed: int) -> None:
    from tests.services.sell_out import test_editar_masivo_previa_concurrencia_postgres as k

    r = random.Random(seed)
    ids = k._mundo(engine, r)
    _consumir(engine)
    seleccion = r.sample(ids, r.randint(1, len(ids)))
    cambios: dict = {"fecha_hasta": date(2026, 11, 1 + r.randint(9, 29))}
    if r.random() < 0.5:
        cambios["acumulable"] = r.random() < 0.5
    antes = k._filas(engine)
    try:
        with _s(engine) as db:
            previa = edicion_masiva.previa_edicion(db, seleccion, dict(cambios), U)
    except service.SellOutError as exc:
        pytest.skip(f"refused: {exc}")
    if previa["rechazadas"]:
        pytest.skip("mixed refusal")
    with _s(engine) as db:
        edicion_masiva.editar_campanas(db, seleccion, dict(cambios), U)
    _drain(engine)
    despues = k._filas(engine)
    vista = {c["id"]: c for c in previa["cambian"] + previa["vinculadas"]}
    for cid in ids:
        ant = {k_[1:]: v for k_, v in antes.items() if k_[0] == cid}
        des = {k_[1:]: v for k_, v in despues.items() if k_[0] == cid}
        gone, new = [x for x in ant if x not in des], [x for x in des if x not in ant]
        neto = sum((v[1] for v in des.values()), Decimal(0)) - sum((v[1] for v in ant.values()), Decimal(0))
        fila = vista.get(cid)
        if fila is None:
            assert not (gone or new or neto), cid
            continue
        assert (fila["salen"]["lineas"], fila["entran"]["lineas"]) == (len(gone), len(new)), cid
        assert fila["entran"]["monto"] - fila["salen"]["monto"] == neto, cid
