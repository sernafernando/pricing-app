"""Bulk edit preview under concurrency and at random (verifier probes of PR #2016, kept as regression tests).

Postgres (`_world`): no trace left (commit, notify, lock, data), a random differential against apply plus drain,
deadlocks with the drain or a single edit ending as a retry, and a failed rebuild leaving the session usable.
"""

from __future__ import annotations

import random
import threading
import time
from collections import Counter
from datetime import date, timedelta
from decimal import Decimal
from typing import Iterator

import pytest
from sqlalchemy import Engine, event, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from app.services.sell_out import asignacion, edicion_masiva, queue
from app.services.sell_out import campanas as service
from tests.services.sell_out import _world as w

pytestmark = pytest.mark.postgres

USUARIO = 7
ROUTER = 2964
SWITCH = 2270
ROUTERS = {"marca": "TP-LINK", "categoria": "Routers"}
SWITCHES = {"marca": "TP-LINK", "categoria": "Switches"}


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with w.world("sell_out_verify_2016") as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    yield
    w.clean(engine)


def _session(engine: Engine) -> Session:
    return sessionmaker(bind=engine, autoflush=False)()


def _drain(engine: Engine) -> None:
    """Every batch until the queue is empty, like the handler's loop."""
    while True:
        with _session(engine) as db:
            claimed = queue.claim_batch(db, queue.BATCH_SIZE)
            if not claimed:
                return
            asignacion.recalcular(db, claimed)
            queue.ack(db, claimed)
            db.commit()


def _consumir(engine: Engine) -> None:
    with engine.begin() as conn:
        ids = [r[0] for r in conn.execute(text("SELECT id FROM sell_out_campanas"))]
    with _session(engine) as db:
        queue.enqueue(db, ids)
        db.commit()
    _drain(engine)


def _previa(engine: Engine, ids: list[int], **cambios: object) -> dict:
    with _session(engine) as db:
        return edicion_masiva.previa_edicion(db, ids, cambios, USUARIO)


def _all_tables(engine: Engine) -> dict:
    """md5 of every table of the throwaway schema, read through `to_jsonb` of the rows."""
    with engine.connect() as conn:
        schema = conn.execute(text("SELECT current_schema()")).scalar()
        tablas = [
            r[0]
            for r in conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = :s ORDER BY 1"),
                {"s": schema},
            )
        ]
        salida = {}
        for tabla in tablas:
            salida[tabla] = conn.execute(
                text(
                    f"SELECT count(*), md5(coalesce(string_agg(t::text, chr(10) ORDER BY t::text), '')) FROM \"{tabla}\" t"
                )
            ).one()
        return salida


def _advisory_count(engine: Engine) -> int:
    with engine.connect() as conn:
        return conn.execute(
            # pg_locks is cluster-wide: under xdist every worker has its own database in the same server.
            text(
                "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND classid = :ns "
                "AND database = (SELECT oid FROM pg_database WHERE datname = current_database())"
            ),
            {"ns": asignacion.LOCK_NAMESPACE},
        ).scalar()


# ── 1. No trace ─────────────────────────────────────────────────────


def test_trace_success_path_no_commit_no_notify_no_lock_no_data(engine: Engine) -> None:
    """No commit, no NOTIFY, no advisory lock left and every table identical. Sequences are not transactional: the
    rolled-back inserts consume ids, like any rolled-back write."""
    g = w.grupo(engine, [ROUTERS])
    a = w.campana(engine, [g], nombre="A", tope_unidades=3)
    b = w.campana(engine, [g], nombre="B")
    w.venta(engine, "fuera", ROUTER, 2, date(2026, 11, 20))
    w.venta(engine, "fuera", ROUTER, 2, date(2026, 10, 20))
    _consumir(engine)
    # A queue row in a charged state: the upsert would reset it, the rollback must restore it.
    w.execute(
        engine,
        "INSERT INTO sell_out_dirty (campana_id, attempts, last_error) VALUES (:a, 3, 'boom')",
        a=b,
    )
    antes = _all_tables(engine)

    commits: list[int] = []

    def _commit(conn: object) -> None:
        commits.append(1)

    listener = engine.connect()
    raw = listener.connection.driver_connection
    raw.set_isolation_level(0)  # autocommit
    with raw.cursor() as cur:
        cur.execute("LISTEN sell_out_dirty")
    event.listen(engine, "commit", _commit)
    try:
        previa = _previa(engine, [a], fecha_desde=date(2026, 10, 1), acumulable=False)
        with _session(engine) as db:
            db.execute(text("SELECT 1"))
        time.sleep(0.3)
        raw.poll()
        notificaciones = list(raw.notifies)
    finally:
        event.remove(engine, "commit", _commit)
        raw.set_isolation_level(1)
        listener.close()

    assert previa["totales"]["cambian"] == 1
    assert commits == []
    assert notificaciones == []
    assert _all_tables(engine) == antes
    assert _advisory_count(engine) == 0


# ── 2. Differential: independent of the module's `_diferencia` ──────


def _filas(engine: Engine) -> dict:
    return {(c[0], c[1], c[2]): (c[5], c[6]) for c in w.consumos(engine)}


def _mundo(engine: Engine, r: random.Random) -> list[int]:
    grupos = [w.grupo(engine, [ROUTERS]), w.grupo(engine, [SWITCHES]), w.grupo(engine, [ROUTERS, SWITCHES])]
    for offset in range(-70, 90):
        w.tipo_cambio(engine, date(2026, 11, 1) + timedelta(days=offset), 1000.0 + offset)
    ids = []
    for n in range(r.randint(2, 5)):
        g = r.choice(grupos)
        desde = date(2026, 11, 1) + timedelta(days=r.randint(-20, 10))
        hasta = desde + timedelta(days=r.randint(5, 30))
        comun = {
            "nombre": f"C{n}",
            "desde": desde,
            "hasta": hasta,
            "acumulable": r.random() < 0.6,
        }
        tipo = r.choice(["unidad", "unidad", "tope_u", "tope_m", "usd_fijo", "usd_dia", "total", "total_neg"])
        if tipo == "unidad":
            ids.append(w.campana(engine, [g], **comun))
        elif tipo == "tope_u":
            ids.append(w.campana(engine, [g], tope_unidades=r.randint(1, 6), **comun))
        elif tipo == "tope_m":
            ids.append(w.campana(engine, [g], tope_monto="35.00", **comun))
        elif tipo == "usd_fijo":
            ids.append(w.campana(engine, [g], moneda="USD", tc_modo="fijo", tipo_cambio="1000", **comun))
        elif tipo == "usd_dia":
            ids.append(w.campana(engine, [g], moneda="USD", tc_modo="dia_venta", **comun))
        else:
            total = "1000" if tipo == "total" else "-300"
            cid = w.monto_total(engine, [grupos[2]], total, **comun)
            w.reparto(engine, cid, ROUTER, porcentaje="60")
            w.reparto(engine, cid, SWITCH, porcentaje="40")
            ids.append(cid)
    for _ in range(r.randint(3, 10)):
        canal = r.choice(["fuera", "ml", "tn"])
        w.venta(
            engine,
            canal,
            r.choice([ROUTER, SWITCH]),
            r.randint(1, 5),
            date(2026, 11, 1) + timedelta(days=r.randint(-30, 45)),
        )
    return ids


@pytest.mark.parametrize("seed", range(40))
def test_differential_preview_vs_apply_and_drain(engine: Engine, seed: int) -> None:
    r = random.Random(seed)
    ids = _mundo(engine, r)
    _consumir(engine)
    if seed % 4 == 3:  # pending work on the same campaigns: a sale nobody drained yet
        w.venta(engine, "fuera", ROUTER, 2, date(2026, 11, 12))
        with _session(engine) as db:
            queue.enqueue(db, ids[:1])
            db.commit()
    seleccion = r.sample(ids, r.randint(1, len(ids)))
    cambios: dict = {}
    if r.random() < 0.7:
        cambios["fecha_desde"] = date(2026, 11, 1) + timedelta(days=r.randint(-30, 5))
    if r.random() < 0.7:
        cambios["fecha_hasta"] = date(2026, 11, 1) + timedelta(days=r.randint(10, 45))
    if not cambios or r.random() < 0.4:
        cambios["acumulable"] = r.random() < 0.5

    antes = _filas(engine)
    tablas = _all_tables(engine)
    try:
        previa = _previa(engine, seleccion, **cambios)
    except service.SellOutError as exc:
        pytest.skip(f"refused: {exc}")
    assert _all_tables(engine) == tablas
    if previa["rechazadas"]:
        pytest.skip("mixed refusal")
    with _session(engine) as db:
        edicion_masiva.editar_campanas(db, seleccion, dict(cambios), USUARIO)
    _drain(engine)
    despues = _filas(engine)

    vista = {c["id"]: c for c in previa["cambian"] + previa["vinculadas"]}
    for fila in previa["vinculadas"]:
        assert fila["en_seleccion"] == (fila["id"] in seleccion)
    for cid in ids:
        ant = {k[1:]: v for k, v in antes.items() if k[0] == cid}
        des = {k[1:]: v for k, v in despues.items() if k[0] == cid}
        gone = [k for k in ant if k not in des]
        new = [k for k in des if k not in ant]
        baja = sum(max(ant[k][0] - des[k][0], 0) for k in ant if k in des) + sum(ant[k][0] for k in gone)
        sube = sum(max(des[k][0] - ant[k][0], 0) for k in des if k in ant) + sum(des[k][0] for k in new)
        neto = sum((v[1] for v in des.values()), Decimal(0)) - sum((v[1] for v in ant.values()), Decimal(0))
        fila = vista.get(cid)
        if fila is None:
            assert not (gone or new or baja or sube or neto), f"campaign {cid} moved but is not listed"
            continue
        assert fila["salen"]["lineas"] == len(gone), cid
        assert fila["entran"]["lineas"] == len(new), cid
        assert fila["salen"]["unidades"] == baja, cid
        assert fila["entran"]["unidades"] == sube, cid
        assert fila["entran"]["monto"] - fila["salen"]["monto"] == neto, cid
    for lado in ("salen", "entran"):
        por_moneda = Counter()
        for fila in vista.values():
            por_moneda[fila["moneda"]] += fila[lado]["monto"]
        listados = {m["moneda"]: m["monto"] for m in previa["totales"][lado]["montos"]}
        assert {k: v for k, v in por_moneda.items() if v} == {k: v for k, v in listados.items() if v}


def test_pending_work_is_shown_as_if_the_edit_moved_it(engine: Engine) -> None:
    g = w.grupo(engine, [ROUTERS])
    a = w.campana(engine, [g], nombre="A")
    _consumir(engine)
    w.venta(engine, "fuera", ROUTER, 2, date(2026, 11, 12))  # inside the dates, the sale queue did not drain yet
    with _session(engine) as db:
        queue.enqueue(db, [a])
        db.commit()

    previa = _previa(engine, [a], acumulable=False)  # the edit by itself moves nothing

    assert previa["cambian"][0]["entran"]["lineas"] == 1
    assert previa["cambian"][0]["incluye_pendientes"] is True  # labelled: pending work, not this edit


# ── 3. Concurrency ──────────────────────────────────────────────────


def _espera_advisory(engine: Engine, segundos: float = 5.0) -> None:
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        fin = time.monotonic() + segundos
        while time.monotonic() < fin:
            n = conn.execute(
                text(
                    "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND classid = :ns AND NOT granted "
                    "AND database = (SELECT oid FROM pg_database WHERE datname = current_database())"
                ),
                {"ns": asignacion.LOCK_NAMESPACE},
            ).scalar()
            if n:
                return
            time.sleep(0.02)
    raise AssertionError("the preview never waited for the advisory lock")


def test_a_drain_of_a_voided_campaign_deadlocking_the_preview_is_a_retry(engine: Engine) -> None:
    """A voided campaign V (not in the preview's closure, so no queue row collides) is being drained: its rebuild
    holds the advisory lock of its linked active A and needs a KEY SHARE on A for the freed units' new row. The
    preview holds A FOR UPDATE and waits for that advisory lock."""
    g = w.grupo(engine, [ROUTERS])
    v = w.campana(engine, [g], nombre="V", acumulable=False)  # lower id: it holds the units
    a = w.campana(engine, [g], nombre="A", acumulable=False)
    w.venta(engine, "fuera", ROUTER, 2, date(2026, 11, 10))
    _consumir(engine)
    with _session(engine) as db:
        service.anular_campana(db, v, USUARIO, "verifier")  # `_anular` queues V alone
    assert [row[0] for row in w.queued(engine)] == [v]

    drain = _session(engine)
    assert queue.claim_batch(drain, queue.BATCH_SIZE) == [v]
    cierre = asignacion.vinculadas(drain, [v])
    assert a in cierre
    drain.execute(asignacion.LOCK_SQL, {"ns": asignacion.LOCK_NAMESPACE, "ids": cierre})  # what `recalcular` does first

    resultado: dict = {}

    def _preview() -> None:
        try:
            resultado["ok"] = _previa(engine, [a], fecha_hasta=date(2026, 12, 31))
        except BaseException as exc:  # noqa: BLE001
            resultado["exc"] = exc

    hilo = threading.Thread(target=_preview)
    hilo.start()
    _espera_advisory(engine)
    drain_error = None
    try:
        asignacion.recalcular(drain, [v])  # blocks on A's row (FK) until the deadlock is resolved
        queue.ack(drain, [v])
        drain.commit()
    except DBAPIError as exc:
        drain_error = exc
        drain.rollback()
    finally:
        drain.close()
    hilo.join(10)
    exc = resultado.get("exc")
    assert exc is None or isinstance(exc, service.SellOutError), f"unhandled in the router: {exc!r}"
    assert exc is None or drain_error is None  # Postgres aborts one side of the cycle, never both


def test_a_preview_behind_a_running_rebuild_gives_up_within_the_queue_bound(engine: Engine) -> None:
    """A drain holds the rebuild's per-campaign locks of A for as long as it rebuilds: the preview, holding A's row,
    waits at most `queue.LOCK_TIMEOUT` for them, then is the busy 409, nothing written; never the 60 s timeout."""
    g = w.grupo(engine, [ROUTERS])
    a = w.campana(engine, [g], nombre="A")
    w.venta(engine, "fuera", ROUTER, 2, date(2026, 11, 10))
    _consumir(engine)
    antes = _all_tables(engine)

    drain = _session(engine)
    drain.execute(asignacion.LOCK_SQL, {"ns": asignacion.LOCK_NAMESPACE, "ids": [a]})  # a long rebuild of A
    resultado: dict = {}

    def _preview() -> None:
        t = time.monotonic()
        try:
            resultado["ok"] = _previa(engine, [a], fecha_hasta=date(2026, 11, 15))
        except BaseException as exc:  # noqa: BLE001
            resultado["exc"] = exc
        resultado["t"] = time.monotonic() - t

    hilo = threading.Thread(target=_preview)
    hilo.start()
    hilo.join(15)
    drain.rollback()
    drain.close()
    hilo.join(10)

    assert resultado["t"] < 8, resultado
    assert isinstance(resultado.get("exc"), service.SellOutRecalculando), resultado
    assert str(resultado["exc"]) == (
        "Otra operación está recalculando o modificando estas campañas en este momento. Reintentar en unos segundos."
    )
    assert _all_tables(engine) == antes


def test_a_preview_behind_a_held_campaign_row_gives_up_within_the_queue_bound(engine: Engine) -> None:
    """Another preview or bulk edit holds A's row until it ends: the preview waits at most `queue.LOCK_TIMEOUT` for
    it, then is the busy 409 naming A, nothing written; never the 60 s statement timeout (a 500)."""
    g = w.grupo(engine, [ROUTERS])
    a = w.campana(engine, [g], nombre="A")
    _consumir(engine)
    antes = _all_tables(engine)

    otro = _session(engine)
    otro.execute(text("SELECT 1 FROM sell_out_campanas WHERE id = :a FOR UPDATE"), {"a": a})
    resultado: dict = {}

    def _preview() -> None:
        t = time.monotonic()
        try:
            resultado["ok"] = _previa(engine, [a], fecha_hasta=date(2026, 12, 31))
        except BaseException as exc:  # noqa: BLE001
            resultado["exc"] = exc
        resultado["t"] = time.monotonic() - t

    hilo = threading.Thread(target=_preview)
    hilo.start()
    hilo.join(15)
    otro.rollback()
    otro.close()
    hilo.join(10)

    assert resultado["t"] < 8, resultado
    exc = resultado.get("exc")
    assert isinstance(exc, edicion_masiva.SellOutEdicionRechazada) and exc.reintentar, resultado
    assert str(exc) == (
        f"No se editó ninguna campaña: otra operación está modificando la campaña {a} en este momento. "
        "Reintentar en unos segundos."
    )
    assert _all_tables(engine) == antes


def test_during_a_preview_writers_and_drain(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    g = w.grupo(engine, [ROUTERS])
    a = w.campana(engine, [g], nombre="A")
    linked = w.campana(engine, [g], nombre="L")
    w.venta(engine, "fuera", ROUTER, 2, date(2026, 11, 10))
    _consumir(engine)
    # Pending real work: the preview's upsert locks this row, so the drain must skip it.
    with _session(engine) as db:
        queue.enqueue(db, [a])
        db.commit()
    w.execute(engine, "UPDATE sell_out_dirty SET attempts = 2")
    antes = w.queued(engine)

    listo, soltar = threading.Event(), threading.Event()
    original = edicion_masiva._diferencia

    def _pausa(*args: object) -> dict:
        if not listo.is_set():
            listo.set()
            assert soltar.wait(30)
        return original(*args)

    monkeypatch.setattr(edicion_masiva, "_diferencia", _pausa)
    salida: dict = {}
    hilo = threading.Thread(target=lambda: salida.update(p=_previa(engine, [a], fecha_hasta=date(2026, 11, 5))))
    hilo.start()
    assert listo.wait(15)

    # The drain finds nothing: the pending row is locked by the preview.
    with _session(engine) as db:
        assert queue.claim_batch(db, queue.BATCH_SIZE) == []
        db.rollback()

    # A single edit of a linked campaign with no queue row: the preview's queue INSERT holds KEY SHARE on its row, so
    # the edit's FOR UPDATE waits with no timeout (not the 2 s 409 of the module docstring).
    editada: dict = {}

    def _edit() -> None:
        t = time.monotonic()
        try:
            with _session(engine) as db:
                campana = service.bloquear(db, linked)
                data = service.entrada_guardada(db, campana).model_copy(update={"acumulable": False})
                service.editar_campana(db, linked, data, USUARIO)
        except service.SellOutRecalculando as exc:  # the deadlock victim against the apply below: a retry
            editada["exc"] = exc
        editada["t"] = time.monotonic() - t

    editor = threading.Thread(target=_edit)
    editor.start()
    time.sleep(3)
    assert editor.is_alive()

    # The apply of the same campaign waits for the preview, then edits the current row.
    aplicada: dict = {}

    def _apply() -> None:
        t = time.monotonic()
        try:
            with _session(engine) as db:
                aplicada["r"] = edicion_masiva.editar_campanas(db, [a], {"fecha_hasta": date(2026, 11, 5)}, USUARIO)
        except edicion_masiva.SellOutEdicionRechazada as exc:  # or it is the victim against the single edit
            assert exc.reintentar, exc
            aplicada["exc"] = exc
        aplicada["t"] = time.monotonic() - t

    otro = threading.Thread(target=_apply)
    otro.start()
    time.sleep(0.5)
    assert otro.is_alive()
    soltar.set()
    hilo.join(10)
    otro.join(10)
    editor.join(10)
    vivos = [n for n, t in (("preview", hilo), ("apply", otro), ("edit", editor)) if t.is_alive()]
    assert vivos == [], f"still running after 10 s: {vivos}, advisory={_advisory_count(engine)}"
    if "exc" not in editada:
        assert editada["t"] > 3  # no queue row: it waited on the campaign row past the 2 s bound
    assert salida["p"]["cambian"][0]["salen"]["lineas"] == 1
    # The apply and the single edit of its linked campaign lock in opposite orders: at most one is the victim, a
    # retry, and the other goes through.
    assert ("exc" in aplicada) + ("exc" in editada) <= 1
    assert aplicada.get("r") in (None, ([a], []))
    assert antes[0][1] == 2  # the row was charged before
    assert _advisory_count(engine) == 0


def test_single_edit_of_a_linked_campaign_with_a_queue_row_deadlocks_with_the_preview(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No void involved. L has a pending queue row, so the preview's upsert takes no KEY SHARE on L's campaign row:
    the single edit locks L FOR UPDATE and waits for the queue row, then the rebuild's new L row needs that KEY SHARE."""
    g = w.grupo(engine, [ROUTERS])
    a = w.campana(engine, [g], nombre="A", acumulable=False)  # lower id: it holds the units
    linked = w.campana(engine, [g], nombre="L", acumulable=False)
    w.venta(engine, "fuera", ROUTER, 2, date(2026, 11, 10))
    _consumir(engine)
    with _session(engine) as db:
        queue.enqueue(db, [linked])
        db.commit()

    listo, soltar = threading.Event(), threading.Event()
    original = edicion_masiva._consumos

    def _pausa(*args: object) -> object:
        if not listo.is_set():  # the "before" read, after the loop and before the rebuild
            listo.set()
            assert soltar.wait(30)
        return original(*args)

    monkeypatch.setattr(edicion_masiva, "_consumos", _pausa)
    salida: dict = {}

    def _preview() -> None:
        try:
            salida["p"] = _previa(engine, [a], fecha_hasta=date(2026, 11, 5))
        except BaseException as exc:  # noqa: BLE001
            salida["exc"] = exc

    hilo = threading.Thread(target=_preview)
    hilo.start()
    assert listo.wait(15)

    editada: dict = {}

    def _edit() -> None:
        try:
            with _session(engine) as db:
                campana = service.bloquear(db, linked)
                data = service.entrada_guardada(db, campana).model_copy(update={"fecha_hasta": date(2026, 12, 1)})
                service.editar_campana(db, linked, data, USUARIO)
            editada["ok"] = True
        except BaseException as exc:  # noqa: BLE001
            editada["exc"] = exc

    editor = threading.Thread(target=_edit)
    editor.start()
    time.sleep(0.3)  # the edit holds L's row and waits for a queue row
    soltar.set()
    hilo.join(15)
    editor.join(15)
    pre, ed = salida.get("exc"), editada.get("exc")
    assert pre is None or isinstance(pre, service.SellOutError), repr(pre)
    assert ed is None or isinstance(ed, service.SellOutError), repr(ed)


# ── 4. Failed rebuild ───────────────────────────────────────────────


def test_failed_rebuild_leaves_the_same_session_usable(engine: Engine) -> None:
    w.execute(
        engine,
        "INSERT INTO productos_erp (item_id, codigo, descripcion, marca, categoria) "
        "VALUES (9998, 'C9998', 'Producto', 'MARCA PROG', 'Routers')",
    )
    try:
        cid = w.campana(engine, [w.grupo(engine, [{"item_id": 9998}])], nombre="Rebate", monto_incluye_iva=True)
        otra = w.campana(engine, [w.grupo(engine, [ROUTERS])], nombre="Otra")
        w.venta(engine, "fuera", 9998, 1, date(2026, 12, 10))
        _consumir(engine)
        antes = _all_tables(engine)
        with _session(engine) as db:
            with pytest.raises(service.SellOutError) as exc:
                edicion_masiva.previa_edicion(db, [cid], {"fecha_hasta": date(2026, 12, 31)}, USUARIO)
            assert "Rebate" in str(exc.value)
            assert not db.in_transaction()
            assert _advisory_count(engine) == 0
            assert _all_tables(engine) == antes
            assert edicion_masiva.editar_campanas(db, [otra], {"acumulable": False}, USUARIO) == ([otra], [])
    finally:
        w.clean(engine)
        w.execute(engine, "DELETE FROM productos_erp WHERE item_id = 9998")
