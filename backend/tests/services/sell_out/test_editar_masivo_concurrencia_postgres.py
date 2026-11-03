"""Bulk edit apply under concurrency and at scale (verifier probes of PR #2014, kept as regression tests).

Real Postgres, two real sessions: all or nothing, equivalence with N single edits (linked campaigns outside the
selection included), lost updates, lock order, deadlocks with a single edit or the drain ending as a retry, and
the cost of a full batch.
"""

from __future__ import annotations

import os
import threading
import time
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Callable, Iterator

import pytest
from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import sessionmaker

from app.models.sell_out import SellOutCampana
from app.schemas.sell_out import SellOutCampanaIn, SellOutCampanaItemIn
from app.services.sell_out import asignacion, edicion_masiva, queue
from app.services.sell_out import campanas as service
from app.workers.context import WorkerContext
from app.workers.handlers.sell_out_drain import drain as handler
from tests.services.sell_out import _world as w

pytestmark = pytest.mark.postgres

U = 7
ROUTER, SWITCH = 2964, 2270
ROUTERS = {"marca": "TP-LINK", "categoria": "Routers"}
SWITCHES = {"marca": "TP-LINK", "categoria": "Switches"}
TABLAS = (
    "sell_out_campanas",
    "sell_out_campana_grupos",
    "sell_out_campana_items",
    "sell_out_consumos",
    "sell_out_dirty",
    "auditoria",
)
H31 = date(2026, 12, 31)


def _bounded(engine: Engine) -> Engine:
    with engine.connect() as c:
        schema = c.execute(text("SELECT current_schema()")).scalar()
    return create_engine(
        engine.url,
        connect_args={"options": f"-csearch_path={schema} -clock_timeout=8000 -cstatement_timeout=20000"},
    )


@pytest.fixture(scope="module")
def _base() -> Iterator[Engine]:
    with w.world("v2014") as engine:
        yield engine


@pytest.fixture()
def engine(_base: Engine) -> Iterator[Engine]:
    e = _bounded(_base)
    yield e
    e.dispose()
    w.clean(_base)


def _s(engine: Engine):
    return sessionmaker(bind=engine, autoflush=False)()


class Hilo(threading.Thread):
    def __init__(self, name: str, fn: Callable, engine: Engine) -> None:
        super().__init__(name=name, daemon=True)
        self.fn, self.engine = fn, engine
        self.res, self.exc, self.pid = None, None, None
        self.listo = threading.Event()

    def run(self) -> None:
        with _s(self.engine) as db:
            try:
                self.pid = db.execute(text("SELECT pg_backend_pid()")).scalar()
                self.listo.set()
                self.res = self.fn(db)
            except BaseException as exc:  # noqa: BLE001
                self.exc = exc
                db.rollback()
            finally:
                self.listo.set()


def _bloqueado(engine: Engine, pid: int, limite: float = 6.0) -> None:
    fin = time.time() + limite
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
        while time.time() < fin:
            ev = c.execute(text("SELECT wait_event_type FROM pg_stat_activity WHERE pid = :p"), {"p": pid}).scalar()
            if ev == "Lock":
                return
            time.sleep(0.02)
    raise AssertionError(f"backend {pid} never blocked")


def _hash(engine: Engine) -> dict:
    with engine.connect() as c:
        return {
            t: c.execute(
                text(f"SELECT md5(coalesce(string_agg(x::text, '|' ORDER BY x::text), '')) FROM {t} x")
            ).scalar()
            for t in TABLAS
        }


def _fila(engine: Engine, cid: int) -> dict:
    with engine.connect() as c:
        return dict(c.execute(text("SELECT * FROM sell_out_campanas WHERE id = :c"), {"c": cid}).mappings().one())


def _n_audit(engine: Engine) -> int:
    with engine.connect() as c:
        return c.execute(text("SELECT count(*) FROM auditoria WHERE tipo_accion = 'SELL_OUT_CAMPANA_EDITADA'")).scalar()


def _drenar(engine: Engine) -> None:
    with _s(engine) as db:
        while True:
            ids = queue.claim_batch(db, 50)
            if not ids:
                db.commit()
                return
            asignacion.recalcular(db, ids)
            queue.ack(db, ids)
            db.commit()


def _edit_cuerpo(db, cid: int, **cambios) -> SellOutCampanaIn:
    return service.entrada_guardada(db, db.get(SellOutCampana, cid)).model_copy(update=cambios)


# ── All-or-nothing ──────────────────────────────────────────────────


@pytest.mark.parametrize("pos", [0, 7, 14])
def test_all_or_nothing_hash_unchanged_and_each_row_named(engine: Engine, pos: int) -> None:
    g = w.grupo(engine, [ROUTERS])
    ids, malo = [], None
    for i in range(15):
        if i == pos:  # a rule that rolls the session back mid-loop
            malo = w.monto_total(engine, [g], "100", nombre="MALO")
        ids.append(w.campana(engine, [g], nombre=f"C{i}"))
    anulada, invertida = ids[(pos + 5) % 15], ids[(pos + 9) % 15]
    w.venta(engine, "fuera", ROUTER, 5, date(2026, 11, 10))
    with _s(engine) as db:
        queue.enqueue(db, ids)
        db.commit()
    _drenar(engine)
    w.reparto(engine, malo, ROUTER, monto="150")
    w.execute(engine, "UPDATE sell_out_campanas SET estado = 'anulada' WHERE id = :c", c=anulada)
    w.execute(
        engine,
        "UPDATE sell_out_campanas SET fecha_desde = '2027-01-15', fecha_hasta = '2027-02-01' WHERE id = :c",
        c=invertida,
    )
    antes = _hash(engine)

    with _s(engine) as db, pytest.raises(edicion_masiva.SellOutEdicionRechazada) as exc:
        edicion_masiva.editar_campanas(db, [*ids, malo, 999999999], {"fecha_hasta": H31}, U)

    assert {r[0] for r in exc.value.rechazadas} == {anulada, invertida, malo, 999999999}
    assert exc.value.reintentar is False
    assert _hash(engine) == antes


def test_a_refused_row_mid_rollback_with_lower_ids_first(engine: Engine) -> None:
    """Row k rolls the session back mid-loop: rows before AND after it stay untouched."""
    g = w.grupo(engine, [ROUTERS])
    a = w.campana(engine, [g])
    malo = w.monto_total(engine, [g], "100", nombre="MALO")
    w.reparto(engine, malo, ROUTER, monto="150")
    b = w.campana(engine, [g])
    antes = _hash(engine)
    with _s(engine) as db, pytest.raises(edicion_masiva.SellOutEdicionRechazada) as exc:
        edicion_masiva.editar_campanas(db, [a, malo, b], {"fecha_hasta": H31}, U)
    assert [r[0] for r in exc.value.rechazadas] == [malo]
    assert _hash(engine) == antes


# ── Equivalence ─────────────────────────────────────────────────────


def _mundo(engine: Engine) -> dict:
    r, s, x = w.grupo(engine, [ROUTERS]), w.grupo(engine, [SWITCHES]), w.grupo(engine, [{"item_id": 950}])
    c1 = w.campana(engine, [r], nombre="c1", tope_unidades=3, acumulable=False)
    w.monto_item(engine, c1, ROUTER, "7.25")
    c2 = w.campana(engine, [r], nombre="c2", tipo="porcentaje", monto_unit=None, porcentaje="5.5")
    c3 = w.monto_total(engine, [r, s], "1000", nombre="c3")
    w.reparto(engine, c3, ROUTER, porcentaje="40")
    w.reparto(engine, c3, SWITCH, monto="300")
    c4 = w.campana(engine, [r], nombre="c4", moneda="USD", tc_modo="al_cobro", monto_unit="2.00")
    with _s(engine) as db:
        service.definir_tipo_cambio(db, c4, Decimal("1450.5"), U)
    w.execute(engine, "UPDATE sell_out_campanas SET tc_definido_en = '2026-10-30 12:00:00+00' WHERE id = :c", c=c4)
    c5 = w.campana(engine, [s], nombre="c5", moneda="USD", tc_modo="fijo", tipo_cambio="1400", monto_incluye_iva=True)
    c6 = w.campana(engine, [r], nombre="c6 fuera seleccion", tope_unidades=4, acumulable=False)  # linked, not selected
    c7 = w.campana(engine, [x], nombre="c7 otra")
    w.tipo_cambio(engine, date(2026, 11, 1), 1400.0)
    for item, u, dia in [
        (ROUTER, 5, date(2026, 11, 5)),
        (ROUTER, 3, date(2026, 11, 10)),
        (ROUTER, 4, date(2026, 12, 15)),
        (SWITCH, 2, date(2026, 11, 7)),
        (950, 1, date(2026, 11, 8)),
    ]:
        w.venta(engine, "fuera", item, u, dia)
    w.execute(engine, "DELETE FROM auditoria")
    with _s(engine) as db:
        queue.enqueue(db, [c1, c2, c3, c4, c5, c6, c7])
        db.commit()
    _drenar(engine)
    return dict(c1=c1, c2=c2, c3=c3, c4=c4, c5=c5, c6=c6, c7=c7)


RONDAS = [
    (("c1", "c2", "c3", "c4", "c5"), {"fecha_hasta": H31}),
    (("c1",), {"acumulable": True}),
    (("c2", "c4"), {"fecha_desde": date(2026, 11, 6), "acumulable": False}),
]


def _foto(engine: Engine) -> dict:
    with engine.connect() as c:
        camp = [
            {k: v for k, v in dict(r).items() if k not in ("updated_at", "created_at")}
            for r in c.execute(text("SELECT * FROM sell_out_campanas ORDER BY id")).mappings()
        ]
        aud = [
            tuple(r)
            for r in c.execute(
                text(
                    "SELECT usuario_id, tipo_accion, valores_anteriores, valores_nuevos, comentario "
                    "FROM auditoria ORDER BY id"
                )
            )
        ]
        cons = [
            tuple(r)
            for r in c.execute(
                text(
                    "SELECT campana_id, canal, item_id, fecha_venta, unidades, monto, tc_venta FROM sell_out_consumos "
                    "ORDER BY 1, 2, 3, 4, 5, 6"
                )
            )
        ]
        hijos = [
            tuple(r)
            for r in c.execute(
                text(
                    "SELECT campana_id, item_id, monto_unit, reparto_porcentaje, reparto_monto FROM sell_out_campana_items ORDER BY 1, 2"
                )
            )
        ]
        grupos = [
            tuple(r) for r in c.execute(text("SELECT campana_id, grupo_id FROM sell_out_campana_grupos ORDER BY 1, 2"))
        ]
        cola = [tuple(r) for r in c.execute(text("SELECT campana_id FROM sell_out_dirty ORDER BY 1"))]
    return dict(camp=camp, aud=aud, cons=cons, hijos=hijos, grupos=grupos, cola=cola)


def test_bulk_equals_n_single_edits_including_linked_outside_the_selection() -> None:
    with w.world("v2014a") as ea, w.world("v2014b") as eb:
        a, b = _bounded(ea), _bounded(eb)
        try:
            ids_a, ids_b = _mundo(a), _mundo(b)
            assert ids_a == ids_b
            inicial = _foto(a)["cons"]
            for nombres, cambios in RONDAS:
                ids = [ids_a[n] for n in nombres]
                with _s(a) as db:
                    assert edicion_masiva.editar_campanas(db, list(reversed(ids)), cambios, U) == (ids, [])
                for cid in ids:
                    with _s(b) as db:
                        fila = service.serializar(db, [db.get(SellOutCampana, cid)])[0]
                        cuerpo = {k: fila[k] for k in service._CAMPOS} | {
                            "monto_total": fila["monto_total"],
                            "grupo_ids": [g["id"] for g in fila["grupos"]],
                            "items": [
                                {k: i[k] for k in ("item_id", "monto_unit", "reparto_porcentaje", "reparto_monto")}
                                for i in fila["items"]
                            ],
                            **cambios,
                        }
                        service.editar_campana(db, cid, SellOutCampanaIn.model_validate(cuerpo), U)
                assert _foto(a) == _foto(b), "before the rebuild"
                _drenar(a), _drenar(b)
                fa, fb = _foto(a), _foto(b)
                assert fa == fb, "after the rebuild"
                assert fa["cola"] == []
            final = _foto(a)["cons"]
            c6 = ids_a["c6"]
            assert [x for x in inicial if x[0] == c6] != [x for x in final if x[0] == c6], "c6 did not move: weak probe"
            with _s(a) as db:  # fixed point: a full rebuild changes nothing, the linked rows are consistent
                r = asignacion.recalcular(db, list(ids_a.values()))
                db.commit()
            assert (r.inserted, r.deleted) == (0, 0)
            with a.connect() as c:
                assert c.execute(text("SELECT count(*), bool_and(es_masivo) FROM auditoria")).one() == (8, True)
            with b.connect() as c:
                assert c.execute(text("SELECT count(*), bool_or(es_masivo) FROM auditoria")).one() == (8, False)
        finally:
            a.dispose(), b.dispose()


# ── Concurrency ─────────────────────────────────────────────────────


def _dos(engine: Engine):
    g1, g2 = w.grupo(engine, [ROUTERS]), w.grupo(engine, [SWITCHES])  # unlinked: no shared queue row
    return w.campana(engine, [g1], nombre="A"), w.campana(engine, [g2], nombre="B", descripcion="original")


def test_bulk_does_not_overwrite_a_single_edit_committed_while_it_waited(engine: Engine) -> None:
    """S3: 'Edit one field and the others are not replaced with stale values.'"""
    a, b = _dos(engine)
    with _s(engine) as otro:
        otro.expire_on_commit = False
        data = _edit_cuerpo(otro, b, nombre="B editada", monto_unit=Decimal("25"))
        service.editar_campana_sin_commit(otro, b, data, U)  # holds b's row, uncommitted
        bulk = Hilo("bulk", lambda db: edicion_masiva.editar_campanas(db, [a, b], {"fecha_hasta": H31}, U), engine)
        bulk.start()
        bulk.listo.wait(5)
        _bloqueado(engine, bulk.pid)
        otro.commit()
    bulk.join(20)
    assert not bulk.is_alive()
    assert bulk.exc is None, repr(bulk.exc)
    f = _fila(engine, b)
    assert (f["nombre"], str(f["monto_unit"]), f["fecha_hasta"]) == ("B editada", "25.00", H31)


def test_bulk_does_not_overwrite_a_bulk_committed_while_it_waited(engine: Engine) -> None:
    a, b = _dos(engine)
    with _s(engine) as otro:
        edicion_masiva._aplicar(otro, [b], {"acumulable": False}, U)  # the other bulk, not yet committed
        bulk = Hilo("bulk", lambda db: edicion_masiva.editar_campanas(db, [a, b], {"fecha_hasta": H31}, U), engine)
        bulk.start()
        bulk.listo.wait(5)
        _bloqueado(engine, bulk.pid)
        otro.commit()
    bulk.join(20)
    assert bulk.exc is None, repr(bulk.exc)
    f = _fila(engine, b)
    assert (f["acumulable"], f["fecha_hasta"]) == (False, H31)


def test_sin_cambio_is_not_decided_on_a_value_read_before_the_lock(engine: Engine) -> None:
    a, b = _dos(engine)  # both end 2026-11-30
    w.execute(engine, "UPDATE sell_out_campanas SET fecha_hasta = '2026-11-20' WHERE id = :c", c=a)
    pedido = date(2026, 11, 30)
    with _s(engine) as otro:
        data = _edit_cuerpo(otro, b, fecha_hasta=date(2026, 12, 20))
        service.editar_campana_sin_commit(otro, b, data, U)
        bulk = Hilo("bulk", lambda db: edicion_masiva.editar_campanas(db, [a, b], {"fecha_hasta": pedido}, U), engine)
        bulk.start()
        bulk.listo.wait(5)
        _bloqueado(engine, bulk.pid)
        otro.commit()
    bulk.join(20)
    assert bulk.exc is None, repr(bulk.exc)
    assert _fila(engine, b)["fecha_hasta"] == pedido


def test_lock_order_is_by_id_whatever_the_request_order(engine: Engine) -> None:
    g = w.grupo(engine, [ROUTERS])
    ids = [w.campana(engine, [g]) for _ in range(6)]
    vistos: list[int] = []

    def _cap(conn, cursor, statement, parameters, context, many):
        if "FOR UPDATE" in statement and "sell_out_campanas" in statement:
            vistos.append(parameters["id_1"])

    event.listen(engine, "before_cursor_execute", _cap)
    with _s(engine) as db:
        edicion_masiva.editar_campanas(
            db, [ids[3], ids[0], ids[5], ids[1], ids[4], ids[2], ids[3]], {"acumulable": False}, U
        )
    event.remove(engine, "before_cursor_execute", _cap)
    primera = list(dict.fromkeys(vistos))
    assert primera == ids
    assert _n_audit(engine) == 6


def test_bulk_vs_bulk_overlapping_different_orders_natural_race(engine: Engine) -> None:
    g = w.grupo(engine, [ROUTERS])
    ids = [w.campana(engine, [g]) for _ in range(8)]
    errores, ok, perdidas, audits = [], 0, 0, 0
    for ronda in range(12):
        h1, h2 = date(2026, 12, 1 + ronda), bool(ronda % 2)
        barrera = threading.Barrier(2)

        def _f(sel, cambios):
            def run(db):
                barrera.wait(5)
                return edicion_masiva.editar_campanas(db, sel, cambios, U)

            return run

        s1, s2 = ids, list(reversed(ids[3:]))  # overlap: ids[3:], different request order
        t1 = Hilo("b1", _f(s1, {"fecha_hasta": h1}), engine)
        t2 = Hilo("b2", _f(s2, {"acumulable": h2}), engine)
        n0 = _n_audit(engine)
        t1.start(), t2.start()
        t1.join(20), t2.join(20)
        assert not t1.is_alive() and not t2.is_alive()
        edit = 0
        for t in (t1, t2):
            if t.exc is None:
                ok += 1
                edit += len(t.res[0])
            elif isinstance(t.exc, edicion_masiva.SellOutEdicionRechazada) and t.exc.reintentar:
                pass
            else:
                errores.append(repr(t.exc))
        audits += _n_audit(engine) - n0 - edit
        if t1.exc is None and t2.exc is None:
            filas = [_fila(engine, c) for c in ids[3:]]
            perdidas += sum(1 for f in filas if (f["fecha_hasta"], f["acumulable"]) != (h1, h2))
    assert errores == [] and audits == 0
    assert perdidas == 0


def _cruzadas(engine: Engine):
    g = w.grupo(engine, [ROUTERS])
    return w.campana(engine, [g], nombre="Y"), w.campana(engine, [g], nombre="X")  # y < x, linked


@pytest.mark.parametrize("victima", ["single", "bulk"])
def test_bulk_vs_single_real_lock_cycle(engine: Engine, monkeypatch, victima: str) -> None:
    """Single: row x then queue {x, y}. Bulk [y, x]: row y, queue {x, y}, then row x. A true cycle."""
    y, x = _cruzadas(engine)
    w.execute(engine, "INSERT INTO sell_out_dirty (campana_id) VALUES (:y), (:x)", y=y, x=x)  # a pending re-queue
    original_enc, original_bloq = service._encolar, service.bloquear
    single_con_fila, bulk_con_cola, seguir_single = threading.Event(), threading.Event(), threading.Event()

    def enc(db, ids):
        if threading.current_thread().name == "single":
            single_con_fila.set()
            seguir_single.wait(5)
        original_enc(db, ids)
        if threading.current_thread().name == "bulk":
            bulk_con_cola.set()

    def bloq(db, cid):
        if threading.current_thread().name == "bulk" and cid == x:
            seguir_single.set()
            if victima == "single":
                time.sleep(0.4)  # single starts waiting first, so its deadlock check fires first
        return original_bloq(db, cid)

    monkeypatch.setattr(service, "_encolar", enc)
    monkeypatch.setattr(service, "bloquear", bloq)
    with _s(engine) as db:
        data = _edit_cuerpo(db, x, nombre="X editada")
    single = Hilo("single", lambda db: service.editar_campana(db, x, data, U), engine)
    bulk = Hilo("bulk", lambda db: edicion_masiva.editar_campanas(db, [x, y], {"acumulable": False}, U), engine)
    single.start()
    single_con_fila.wait(5)
    if victima == "bulk":
        bulk.start()
        bulk.join(0.5)  # bulk blocked on row x, single then enters the queue
    else:
        bulk.start()
    single.join(20), bulk.join(20)
    assert not single.is_alive() and not bulk.is_alive()
    # The one that waited first detects the cycle and is the victim, a retry; the other goes through.
    if victima == "single":
        assert isinstance(single.exc, service.SellOutRecalculando), repr(single.exc)
        assert bulk.exc is None and bulk.res == (sorted([x, y]), [])
    else:
        assert isinstance(bulk.exc, edicion_masiva.SellOutEdicionRechazada) and bulk.exc.reintentar, repr(bulk.exc)
        assert single.exc is None
        assert _fila(engine, x)["nombre"] == "X editada"


OCUPADA = "Otra operación está modificando la campaña en este momento. Reintentar en unos segundos."


def _escritura_simple(engine: Engine, cual: str, x: int):
    """The single write on x the test races, and a reader of what it would change."""
    if cual == "anular":
        return (lambda db: service.anular_campana(db, x, U, "baja")), (lambda: _fila(engine, x)["estado"])
    if cual == "tipo_cambio":
        return (lambda db: service.definir_tipo_cambio(db, x, Decimal("1500"), U)), (
            lambda: _fila(engine, x)["tipo_cambio"]
        )
    repartos = [SellOutCampanaItemIn(item_id=ROUTER, reparto_porcentaje=Decimal("50"))]

    def _items() -> list:
        with engine.connect() as c:
            return c.execute(
                text("SELECT item_id, reparto_porcentaje FROM sell_out_campana_items WHERE campana_id = :c"), {"c": x}
            ).all()

    return (lambda db: service.repartir(db, x, repartos, U, None)), _items


@pytest.mark.parametrize("cual", ["anular", "tipo_cambio", "repartir"])
def test_a_single_write_deadlocked_by_a_bulk_edit_is_the_busy_409_and_writes_nothing(
    engine: Engine, monkeypatch: pytest.MonkeyPatch, cual: str
) -> None:
    """A real cycle. Bulk [y, x] (y linked to x): row y, the queue rows of y AND x, then row x. The single void,
    rate or split of x: row x, then x's queue row. The single waits first, so Postgres picks it as the victim."""
    g = w.grupo(engine, [ROUTERS])
    y = w.campana(engine, [g], nombre="Y")
    if cual == "anular":
        x = w.campana(engine, [g], nombre="X")
    elif cual == "tipo_cambio":
        x = w.campana(engine, [g], nombre="X", moneda="USD", tc_modo="al_cobro")
    else:
        x = w.monto_total(engine, [g], "100", nombre="X")
        w.reparto(engine, x, ROUTER, porcentaje="40")
    w.execute(engine, "INSERT INTO sell_out_dirty (campana_id) VALUES (:y), (:x)", y=y, x=x)  # pending re-queues
    escribir, leer = _escritura_simple(engine, cual, x)
    antes = leer()
    original_enc, original_bloq = service._encolar, service.bloquear
    single_con_fila, seguir_single = threading.Event(), threading.Event()

    def enc(db, ids) -> None:
        if threading.current_thread().name == "single":
            single_con_fila.set()
            seguir_single.wait(5)
        original_enc(db, ids)

    def bloq(db, cid):
        if threading.current_thread().name == "bulk" and cid == x:
            seguir_single.set()
            time.sleep(0.4)  # the single starts waiting first: its deadlock check fires first
        return original_bloq(db, cid)

    monkeypatch.setattr(service, "_encolar", enc)
    monkeypatch.setattr(service, "bloquear", bloq)
    single = Hilo("single", escribir, engine)
    bulk = Hilo("bulk", lambda db: edicion_masiva.editar_campanas(db, [x, y], {"fecha_hasta": H31}, U), engine)
    single.start()
    assert single_con_fila.wait(5)
    bulk.start()
    single.join(20), bulk.join(20)

    assert not single.is_alive() and not bulk.is_alive()
    assert isinstance(single.exc, service.SellOutRecalculando), repr(single.exc)
    assert str(single.exc) == OCUPADA
    assert bulk.exc is None and bulk.res == (sorted([x, y]), [])
    assert leer() == antes  # the single wrote nothing


def test_retry_after_409_applies_once_and_audits_once(engine: Engine, monkeypatch) -> None:
    monkeypatch.setattr(queue, "LOCK_TIMEOUT", "100ms")
    a, b = _dos(engine)
    w.execute(engine, "INSERT INTO sell_out_dirty (campana_id) VALUES (:c)", c=b)
    antes = _hash(engine)
    with engine.connect() as holder:
        holder.execute(text("SELECT 1 FROM sell_out_dirty WHERE campana_id = :c FOR UPDATE"), {"c": b})
        with _s(engine) as db, pytest.raises(edicion_masiva.SellOutEdicionRechazada) as exc:
            edicion_masiva.editar_campanas(db, [a, b], {"fecha_hasta": H31}, U)
        holder.rollback()
    assert exc.value.reintentar is True
    assert _hash(engine) == antes
    with _s(engine) as db:
        assert edicion_masiva.editar_campanas(db, [a, b], {"fecha_hasta": H31}, U) == ([a, b], [])
    assert _n_audit(engine) == 2
    with _s(engine) as db:
        assert edicion_masiva.editar_campanas(db, [a, b], {"fecha_hasta": H31}, U) == ([], [a, b])
    assert _n_audit(engine) == 2


def _rebuild_mundo(engine: Engine):
    g = w.grupo(engine, [ROUTERS])
    x = w.campana(engine, [g], nombre="X")
    w.venta(engine, "fuera", ROUTER, 5, date(2026, 11, 10))
    w.execute(engine, "INSERT INTO sell_out_dirty (campana_id) VALUES (:c)", c=x)
    return x


@pytest.mark.parametrize("primero", ["bulk", "rebuild"])
def test_bulk_vs_the_real_rebuild_writer(engine: Engine, monkeypatch, primero: str) -> None:
    """Drain: queue row x, then consumo INSERT (FK: KEY SHARE on row x). Bulk: FOR UPDATE row x, then queue row x."""
    monkeypatch.setattr("app.core.database.SessionLocal", sessionmaker(bind=engine, autoflush=False))
    x = _rebuild_mundo(engine)
    real_rec, real_enc = asignacion.recalcular, service._encolar
    drain_claimed, bulk_con_fila, soltar_bulk = threading.Event(), threading.Event(), threading.Event()

    def rec(db, ids):
        drain_claimed.set()
        if threading.current_thread().name == "drain":
            bulk_con_fila.wait(5)
            if primero == "bulk":
                time.sleep(0.3)
        soltar_bulk.set()
        return real_rec(db, ids)

    def enc(db, ids):
        if threading.current_thread().name == "bulk":
            bulk_con_fila.set()
            if primero == "rebuild":
                soltar_bulk.wait(5)
                time.sleep(0.3)
        return real_enc(db, ids)

    monkeypatch.setattr(asignacion, "recalcular", rec)
    monkeypatch.setattr(service, "_encolar", enc)
    ctx = lambda: WorkerContext(deadline=datetime.now(timezone.utc).replace(year=2100), worker_name="w")  # noqa: E731
    drain = threading.Thread(target=lambda: results.append(handler.run(ctx())), name="drain", daemon=True)
    results: list = []
    drain.start()
    assert drain_claimed.wait(5)
    bulk = Hilo("bulk", lambda db: edicion_masiva.editar_campanas(db, [x], {"fecha_hasta": H31}, U), engine)
    bulk.start()
    bulk.join(20), drain.join(25)
    assert not bulk.is_alive() and not drain.is_alive()
    assert bulk.exc is None or (isinstance(bulk.exc, edicion_masiva.SellOutEdicionRechazada) and bulk.exc.reintentar)
    monkeypatch.setattr(asignacion, "recalcular", real_rec)
    monkeypatch.setattr(service, "_encolar", real_enc)
    if bulk.exc is not None:
        with _s(engine) as db:
            assert edicion_masiva.editar_campanas(db, [x], {"fecha_hasta": H31}, U) == ([x], [])
    assert _n_audit(engine) == 1
    _drenar(engine)
    assert w.queued(engine) == []
    with _s(engine) as db:
        r = asignacion.recalcular(db, [x])
        db.commit()
    assert (r.inserted, r.deleted) == (0, 0)
    assert len(w.consumos(engine, x)) == 1


def test_a_row_with_over_50_groups_is_edited_its_stored_groups_are_not_re_capped(engine: Engine) -> None:
    gs = [w.grupo(engine, [ROUTERS]) for _ in range(51)]  # only reachable outside the API's cap
    cid = w.campana(engine, gs, nombre="51 grupos")
    otra = w.campana(engine, [gs[0]])
    with _s(engine) as db:
        assert edicion_masiva.editar_campanas(db, [otra, cid], {"acumulable": False}, U) == (sorted([otra, cid]), [])
    assert _fila(engine, cid)["acumulable"] is False


def test_500_linked_rows_read_their_links_once_and_queue_each_campaign_once(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cap is 500 per request, every row holding its lock until the commit: the links of the batch are read
    ONCE (`asignacion.vinculadas_por_campana`), so the cost grows with the rows, not with their square (before:
    200 rows 13 s, 500 never finished). The clock bound is generous and skipped in CI (shared runners)."""
    g = w.grupo(engine, [ROUTERS])  # every campaign linked to every other: the worst case
    ids = [w.campana(engine, [g]) for _ in range(500)]
    cargas: list[int] = []
    cargar = asignacion._cargar

    def _contar(db, pedidas):
        cargas.append(len(pedidas))
        return cargar(db, pedidas)

    monkeypatch.setattr(asignacion, "_cargar", _contar)
    t0 = time.monotonic()
    with _s(engine) as db:
        assert edicion_masiva.editar_campanas(db, ids, {"fecha_hasta": H31}, U) == (ids, [])
    segundos = time.monotonic() - t0

    assert cargas == [500]  # one load for the whole batch, none per row
    assert sorted(c for c, *_ in w.queued(engine)) == ids
    if not os.environ.get("CI"):
        assert segundos < 30, segundos  # about 6 s on the test server; the statement_timeout is 60 s


def test_the_row_lock_reads_the_committed_values_not_a_stale_instance_of_the_session(engine: Engine) -> None:
    """`bloquear` reloads the locked row (`populate_existing`): a campaign the session loaded before another writer
    committed comes back with the values committed, so the step never rebuilds an edit from stale ones."""
    cid = w.campana(engine, [w.grupo(engine, [ROUTERS])], nombre="Rebate Q4 2026")
    with _s(engine) as db:
        vieja = db.get(SellOutCampana, cid)  # kept referenced: the identity map holds it weakly
        assert vieja.nombre == "Rebate Q4 2026"
        # Another writer commits; READ COMMITTED: the next statement of this transaction sees it.
        w.execute(engine, "UPDATE sell_out_campanas SET nombre = 'MODELO 8180' WHERE id = :c", c=cid)
        bloqueada = service.bloquear(db, cid)
        assert bloqueada is vieja and bloqueada.nombre == "MODELO 8180"
