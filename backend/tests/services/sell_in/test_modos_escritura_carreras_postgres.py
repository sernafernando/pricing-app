"""A cost mode change on Postgres against seeded worlds: the preview equals what the save produces on every
transition, every input the preview depends on changes its fingerprint (and a refused confirm writes nothing), and the
save under concurrent writers (two saves, a drain, a sale committing meanwhile)."""

from __future__ import annotations

import hashlib
import threading
from datetime import date
from decimal import Decimal
from typing import Iterator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from app.services.sell_in import bonos_costo, modos
from app.services.sell_in.costing import LOCK_NAMESPACE, get_costing
from tests.services.sell_in import _world as si

pytestmark = pytest.mark.postgres

D = date
HOY = D(2026, 11, 10)
R = 2964
U = 7
CENTAVOS = Decimal("0.03")


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with si.world("modos_carreras") as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    yield
    si.clean(engine)


def _s(engine: Engine):
    return sessionmaker(bind=engine, autoflush=False)()


def _recompute(engine: Engine) -> None:
    with _s(engine) as db:
        get_costing().recompute(db, [R], isolate_failures=False)
        db.commit()


def _hash(engine: Engine) -> str:
    with engine.connect() as c:
        filas = []
        for q in (
            "SELECT compra_item_id, canal, venta_ref, item_id, fecha_venta, unidades, descuento_ars FROM sell_in_consumos ORDER BY 1,2,3",
            "SELECT id, item_id, modo, desde FROM sell_in_modos_producto ORDER BY id",
            "SELECT id, cantidad, monto_asignado FROM sell_in_compra_items ORDER BY id",
            "SELECT id, tipo_accion, valores_nuevos::text FROM auditoria ORDER BY id",
        ):
            filas.append(repr([tuple(r) for r in c.execute(text(q))]))
    return hashlib.sha256("|".join(filas).encode()).hexdigest()


def _por_venta(engine: Engine) -> dict:
    with engine.connect() as c:
        return {
            (r[0], r[1]): r[2]
            for r in c.execute(
                text("SELECT canal, venta_ref, sum(descuento_ars) FROM sell_in_consumos GROUP BY canal, venta_ref")
            )
        }


def _preview(engine: Engine, modo: str, desde: date, hoy: date = HOY) -> modos.VistaPrevia:
    with _s(engine) as db:
        vista = modos.vista_previa(db, R, modo, desde, hoy, U)
        db.rollback()
    return vista


def _confirm(engine: Engine, modo: str, desde: date, huella: str, hoy: date = HOY) -> int:
    with _s(engine) as db:
        try:
            modo_id = modos.confirmar(db, R, modo, desde, hoy, U, huella)
        except BaseException:
            db.rollback()
            raise
        db.commit()
    return modo_id


def _escalar(engine: Engine, q: str):
    with engine.connect() as c:
        return c.execute(text(q)).scalar()


def _lotes(engine: Engine) -> None:
    si.compra(engine, [(R, 100, "1000.00")], D(2026, 10, 1))
    si.compra(engine, [(R, 100, "800.00")], D(2026, 10, 2))
    si.compra(engine, [(R, 50, "600.00")], D(2026, 10, 8))


def _mundo(engine: Engine, caso: str) -> None:
    _lotes(engine)
    si.venta(engine, "fuera", R, 30, D(2026, 10, 3), cliente=11)
    si.venta(engine, "ml", R, 40, D(2026, 10, 9))
    si.venta(engine, "tn", R, 25, D(2026, 10, 20), cliente=12)
    if caso == "devolucion":
        si.venta(engine, "fuera", R, 10, D(2026, 10, 21), signo=-1, cliente=11)
    if caso == "agotado":
        si.venta(engine, "fuera", R, 500, D(2026, 10, 22))


TRANSICIONES = [
    (None, "ponderado", D(2026, 10, 5)),
    (None, "ultimo", D(2026, 10, 5)),
    (None, "ultimo", HOY),
    (None, "fifo", HOY),
    ("ponderado", "fifo", D(2026, 10, 15)),
    ("ponderado", "ultimo", D(2026, 10, 15)),
    ("ponderado", "ponderado", D(2026, 10, 15)),
    ("ultimo", "ponderado", D(2026, 10, 15)),
    ("ultimo", "fifo", D(2026, 10, 15)),
    (None, "ponderado", D(2026, 11, 20)),
    (None, "ultimo", D(2026, 11, 20)),
    ("ponderado", "fifo", D(2026, 11, 20)),
    ("ponderado", "ultimo", D(2026, 11, 20)),
    ("ultimo", "fifo", D(2026, 11, 20)),
]


@pytest.mark.parametrize("caso", ["simple", "devolucion", "agotado"])
@pytest.mark.parametrize(("previo", "modo", "desde"), TRANSICIONES)
def test_preview_equals_what_the_save_produces(engine: Engine, caso, previo, modo, desde) -> None:
    _mundo(engine, caso)
    if previo:
        si.modo(engine, R, previo, D(2026, 10, 1))
    _recompute(engine)
    antes = _por_venta(engine)
    h0 = _hash(engine)

    vista = _preview(engine, modo, desde)
    assert _hash(engine) == h0  # nothing persisted

    _confirm(engine, modo, desde, vista.huella)
    despues = _por_venta(engine)
    cambian = {k for k in antes.keys() | despues.keys() if antes.get(k, 0) != despues.get(k, 0)}
    dif = sum((despues.get(k, Decimal(0)) - antes.get(k, Decimal(0)) for k in cambian), Decimal(0))
    assert (vista.ventas_cambian, vista.diferencia_ars) == (len(cambian), dif)

    # One mode row more and one audit row (sales before `desde`: test_sales_before_desde_stay_byte_for_byte).
    assert _escalar(engine, "SELECT count(*) FROM sell_in_modos_producto") == (2 if previo else 1)
    assert _escalar(engine, "SELECT count(*) FROM auditoria") == 1
    dia = max(HOY, desde)
    with _s(engine) as db:
        vig = get_costing().vigentes(db, [R], dia).get(R)
    assert (vig.unidades_restantes if vig else 0) == vista.unidades_restantes
    assert (vig.descuento_unit_ars if vig else None) == vista.descuento_unit

    # Oracle: really sell everything left on `dia`; the ARS no unit handed out must be the preview's.
    total = _escalar(engine, "SELECT coalesce(sum(monto_asignado),0) FROM sell_in_compra_items")
    quedan = _escalar(engine, "SELECT sum(cantidad) FROM sell_in_compra_items") - _escalar(
        engine, "SELECT coalesce(sum(unidades),0) FROM sell_in_consumos"
    )
    if quedan:
        ref = si.venta(engine, "fuera", R, int(quedan), dia)
        _recompute(engine)
        if modo != "fifo":
            dado = _por_venta(engine)[("fuera", ref)]
            assert abs(dado - quedan * vista.descuento_unit) <= CENTAVOS, (dado, quedan, vista.descuento_unit)
    dado = _escalar(engine, "SELECT coalesce(sum(descuento_ars),0) FROM sell_in_consumos")
    assert abs((total - dado) - vista.sin_asignar_despues) <= CENTAVOS, (total, dado, vista.sin_asignar_despues)


def test_sales_before_desde_stay_byte_for_byte(engine: Engine) -> None:
    _mundo(engine, "simple")
    _recompute(engine)
    q = "SELECT * FROM sell_in_consumos WHERE fecha_venta < '2026-10-15' ORDER BY id"
    with engine.connect() as c:
        antes = [tuple(r) for r in c.execute(text(q))]
    _confirm(engine, "ultimo", D(2026, 10, 15), _preview(engine, "ultimo", D(2026, 10, 15)).huella)
    with engine.connect() as c:
        assert [tuple(r) for r in c.execute(text(q))] == antes


def test_a_sale_the_drain_has_not_seen_is_counted_and_written(engine: Engine) -> None:
    _lotes(engine)
    _recompute(engine)
    ref = si.venta(engine, "fuera", R, 10, D(2026, 10, 20))  # queued, not drained
    vista = _preview(engine, "ponderado", D(2026, 10, 15))
    assert vista.ventas_cambian == 1
    _confirm(engine, "ponderado", D(2026, 10, 15), vista.huella)
    assert ("fuera", ref) in _por_venta(engine)


def _set_lote(engine: Engine, linea: int, **valores) -> None:
    sets = ", ".join(f"{k} = :{k}" for k in valores)
    with engine.begin() as c:
        c.execute(text(f"UPDATE sell_in_compra_items SET {sets} WHERE id = :_l"), {"_l": linea, **valores})


def _anular(engine: Engine, linea: int) -> None:
    with engine.begin() as c:
        c.execute(
            text(
                "UPDATE sell_in_compras SET estado='anulada' WHERE id = "
                "(SELECT compra_id FROM sell_in_compra_items WHERE id=:l)"
            ),
            {"l": linea},
        )


@pytest.mark.parametrize(
    "mutacion",
    [
        "venta_nueva",
        "venta_editada",
        "venta_borrada",
        "compra_pasada",
        "lote_primero_monto",
        "lote_ultimo_monto",
        "lote_cantidad",
        "compra_anulada",
        "modo_pasado",
        "modo_futuro",
    ],
)
@pytest.mark.parametrize("modo", ["ponderado", "ultimo"])
def test_every_input_changes_the_fingerprint_and_409_writes_nothing(engine: Engine, mutacion, modo) -> None:
    primero = si.compra(engine, [(R, 100, "1000.00")], D(2026, 10, 1))[0]
    ultimo = si.compra(engine, [(R, 100, "800.00")], D(2026, 10, 2))[0]
    venta = si.venta(engine, "fuera", R, 20, D(2026, 10, 20))
    _recompute(engine)
    desde = D(2026, 10, 15)
    vista = _preview(engine, modo, desde)

    if mutacion == "venta_nueva":
        si.venta(engine, "fuera", R, 5, D(2026, 10, 25))
    elif mutacion == "venta_editada":
        si.update_venta(engine, "fuera", venta, cantidad=Decimal(21))
    elif mutacion == "venta_borrada":
        si.delete_venta(engine, "fuera", venta)
    elif mutacion == "compra_pasada":
        si.compra(engine, [(R, 7, "70.00")], D(2026, 10, 3))
    elif mutacion == "lote_primero_monto":
        _set_lote(engine, primero, monto_asignado=Decimal("1100.00"))
    elif mutacion == "lote_ultimo_monto":
        _set_lote(engine, ultimo, monto_asignado=Decimal("900.00"))
    elif mutacion == "lote_cantidad":
        _set_lote(engine, ultimo, cantidad=90)
    elif mutacion == "compra_anulada":
        _anular(engine, ultimo)
    elif mutacion == "modo_pasado":
        si.modo(engine, R, "ultimo", D(2026, 10, 10))
    elif mutacion == "modo_futuro":
        si.modo(engine, R, "fifo", D(2026, 12, 1))

    h = _hash(engine)
    with pytest.raises(modos.HuellaVencida):
        _confirm(engine, modo, desde, vista.huella)
    assert _hash(engine) == h
    assert _escalar(engine, "SELECT count(*) FROM auditoria") == 0


@pytest.mark.parametrize(
    ("modo", "desde"), [("ponderado", HOY), ("ultimo", HOY), ("fifo", HOY), ("ponderado", D(2026, 11, 15))]
)
def test_a_purchase_counting_after_the_mode_also_refuses_the_confirm(engine: Engine, modo, desde) -> None:
    # D2: "If anything moved in between (a new sale or purchase), the server answers 409".
    _lotes(engine)
    _recompute(engine)
    vista = _preview(engine, modo, desde)
    si.compra(engine, [(R, 100, "50.00")], D(2026, 12, 20))
    h = _hash(engine)
    with pytest.raises(modos.HuellaVencida):
        _confirm(engine, modo, desde, vista.huella)
    assert _hash(engine) == h
    assert _escalar(engine, "SELECT count(*) FROM auditoria") == 0


def test_another_day_refuses_the_confirm(engine: Engine) -> None:
    _lotes(engine)
    vista = _preview(engine, "ponderado", HOY)
    with pytest.raises(modos.HuellaVencida):
        _confirm(engine, "ponderado", HOY, vista.huella, hoy=D(2026, 11, 11))


def test_two_saves_racing_only_one_lands(engine: Engine) -> None:
    _lotes(engine)
    si.venta(engine, "fuera", R, 20, D(2026, 10, 20))
    _recompute(engine)
    desde = D(2026, 10, 15)
    vista = _preview(engine, "ponderado", desde)
    barrera = threading.Barrier(2)
    salida = []

    def salvar() -> None:
        barrera.wait()
        try:
            salida.append(("ok", _confirm(engine, "ponderado", desde, vista.huella)))
        except modos.HuellaVencida:
            salida.append(("409", None))
        except Exception as exc:  # noqa: BLE001
            salida.append(("raw", repr(exc)))

    hilos = [threading.Thread(target=salvar) for _ in range(2)]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join(30)
    assert sorted(s[0] for s in salida) == ["409", "ok"], salida
    assert _escalar(engine, "SELECT count(*) FROM sell_in_modos_producto") == 1
    assert _escalar(engine, "SELECT count(*) FROM auditoria") == 1


def test_the_preview_keeps_no_lock(engine: Engine) -> None:
    _lotes(engine)
    with _s(engine) as db:
        modos.vista_previa(db, R, "ponderado", HOY, HOY, U)
        with engine.connect() as otra:
            assert otra.execute(
                text("SELECT pg_try_advisory_xact_lock(:n, :i)"), {"n": LOCK_NAMESPACE, "i": R}
            ).scalar()
            otra.rollback()
        db.rollback()


def test_a_confirm_waits_for_a_drain_holding_the_product_and_never_fails_on_it(engine: Engine) -> None:
    _lotes(engine)
    _recompute(engine)
    desde = D(2026, 10, 15)
    vista = _preview(engine, "ponderado", desde)
    salida = []
    drenaje = _s(engine)
    si.venta(engine, "fuera", R, 5, D(2026, 10, 25))  # the sale alone already makes the preview stale
    get_costing().recompute(drenaje, [R])  # the drain, uncommitted, holds the product
    pid = drenaje.execute(text("SELECT pg_backend_pid()")).scalar()

    def salvar() -> None:
        try:
            salida.append(_confirm(engine, "ponderado", desde, vista.huella))
        except Exception as exc:  # noqa: BLE001
            salida.append(exc)

    hilo = threading.Thread(target=salvar)
    hilo.start()
    try:
        si.esperar_bloqueado_por(engine, pid)  # it waits on the drain, it does not fail
        assert not salida
    finally:
        drenaje.commit()
        drenaje.close()
        hilo.join(30)
    assert isinstance(salida[0], modos.HuellaVencida), salida


def test_a_sale_committing_during_a_confirm_lands_under_the_new_mode(engine: Engine) -> None:
    _lotes(engine)
    si.venta(engine, "fuera", R, 100, D(2026, 10, 20))
    _recompute(engine)
    desde = D(2026, 10, 15)
    vista = _preview(engine, "ponderado", desde)
    with _s(engine) as db:
        modos.confirmar(db, R, "ponderado", desde, HOY, U, vista.huella)
        ref = si.venta(engine, "fuera", R, 10, D(2026, 10, 25))  # never blocked by the save
        db.commit()
    assert si.queued(engine)  # the drain still owes it
    _recompute(engine)
    assert _por_venta(engine)[("fuera", ref)] == Decimal("96.00")  # 2400/250 = 9.60


def test_a_failing_cost_bonus_follow_up_still_saves_one_row_one_audit(engine: Engine, monkeypatch) -> None:
    _lotes(engine)
    vista = _preview(engine, "ponderado", HOY)

    llamadas = []

    def falla(db, item_ids):
        llamadas.append(set(item_ids))
        raise OperationalError("x", {}, Exception("canceling statement due to lock timeout"))

    monkeypatch.setattr(bonos_costo, "recalcular", falla)
    _confirm(engine, "ponderado", HOY, vista.huella)
    assert llamadas == [{R}]  # the follow-up ran and failed
    assert _escalar(engine, "SELECT count(*) FROM sell_in_modos_producto") == 1
    assert _escalar(engine, "SELECT count(*) FROM auditoria") == 1
