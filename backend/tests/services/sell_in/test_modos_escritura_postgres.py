"""Changing a product's sell-in cost mode (D2): the mandatory preview (sales whose sell in changes, the ARS difference,
the units and unit value left, the ARS the lots hold that no unit will hand out) computed by the recompute itself and
rolled back, and the confirm, which saves only what the preview showed (its fingerprint) or refuses."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Iterator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import sessionmaker

from app.services.sell_in import modos
from app.services.sell_in.costing import get_costing
from tests.services.sell_in import _world as si

pytestmark = pytest.mark.postgres

D = date
HOY = D(2026, 11, 10)
ROUTER = 2964
USUARIO = 7


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with si.world("modos_escritura") as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    yield
    si.clean(engine)


def _sesion(engine: Engine):
    return sessionmaker(bind=engine, autoflush=False)()


def _dos_lotes(engine: Engine) -> None:
    si.compra(engine, [(ROUTER, 100, "1000.00")], D(2026, 10, 1))
    si.compra(engine, [(ROUTER, 100, "800.00")], D(2026, 10, 2))


def _modos(engine: Engine) -> list:
    with engine.connect() as conn:
        return [
            tuple(r) for r in conn.execute(text("SELECT modo, desde, origen FROM sell_in_modos_producto ORDER BY id"))
        ]


def _auditoria(engine: Engine) -> list:
    with engine.connect() as conn:
        return [
            tuple(r)
            for r in conn.execute(text("SELECT item_id, usuario_id, tipo_accion, valores_nuevos FROM auditoria"))
        ]


def _vista(engine: Engine, modo: str, desde: date) -> modos.VistaPrevia:
    with _sesion(engine) as db:
        vista = modos.vista_previa(db, ROUTER, modo, desde, HOY, USUARIO)
        db.commit()
    return vista


def test_the_preview_counts_the_sales_that_change_and_saves_nothing(engine: Engine) -> None:
    _dos_lotes(engine)
    si.venta(engine, "fuera", ROUTER, 100, D(2026, 10, 20))
    si.venta(engine, "fuera", ROUTER, 20, D(2026, 10, 5))  # before `desde`: stays at 10.00
    with _sesion(engine) as db:
        get_costing().recompute(db, [ROUTER])
        db.commit()
    antes = si.consumos(engine)

    vista = _vista(engine, "ponderado", D(2026, 10, 15))

    # FIFO: 80 at 10 + 20 at 8 = 960; weighted from Oct 15: 180 left worth 1600, 100 of them = 888.89, and the
    # 711.11 left over 80 units.
    assert (vista.ventas_cambian, vista.diferencia_ars) == (1, Decimal("-71.11"))
    assert (vista.unidades_restantes, vista.descuento_unit, vista.del_bloque) == (80, Decimal("8.888875"), False)
    assert (vista.sin_asignar_antes, vista.sin_asignar_despues) == (Decimal("0.00"), Decimal("0.00"))
    assert si.consumos(engine) == antes and _modos(engine) == [] and _auditoria(engine) == []


def test_the_confirm_saves_the_row_recomputes_and_audits(engine: Engine) -> None:
    _dos_lotes(engine)
    venta = si.venta(engine, "fuera", ROUTER, 100, D(2026, 10, 20))
    vista = _vista(engine, "ponderado", D(2026, 10, 15))

    with _sesion(engine) as db:
        modo_id = modos.confirmar(db, ROUTER, "ponderado", D(2026, 10, 15), HOY, USUARIO, vista.huella)
        db.commit()

    assert _modos(engine) == [("ponderado", D(2026, 10, 15), "visor")]
    assert sum(c[5] for c in si.consumos(engine) if c[2] == venta) == Decimal("900.00")
    [(item_id, usuario_id, tipo, valores)] = _auditoria(engine)
    assert (item_id, usuario_id, tipo) == (ROUTER, USUARIO, "SELL_IN_MODO_CREADO")  # the column holds the member name
    assert valores == {
        "modo_id": modo_id,
        "modo": "ponderado",
        "desde": "2026-10-15",
        "ventas_cambian": 1,
        "diferencia_ars": "-100.00",
        "sin_asignar_ars": "0.00",
    }


def test_a_sale_recorded_after_the_preview_refuses_the_confirm(engine: Engine) -> None:
    _dos_lotes(engine)
    si.venta(engine, "fuera", ROUTER, 100, D(2026, 10, 20))
    vista = _vista(engine, "ponderado", D(2026, 10, 15))
    si.venta(engine, "fuera", ROUTER, 5, D(2026, 10, 25))
    antes = si.consumos(engine)

    with _sesion(engine) as db:
        with pytest.raises(modos.HuellaVencida):
            modos.confirmar(db, ROUTER, "ponderado", D(2026, 10, 15), HOY, USUARIO, vista.huella)
        db.rollback()

    assert _modos(engine) == [] and _auditoria(engine) == [] and si.consumos(engine) == antes


def test_a_purchase_loaded_after_the_preview_refuses_the_confirm_even_with_no_sale(engine: Engine) -> None:
    _dos_lotes(engine)
    vista = _vista(engine, "ponderado", D(2026, 10, 15))
    si.compra(engine, [(ROUTER, 50, "100.00")], D(2026, 10, 3))

    with _sesion(engine) as db:
        with pytest.raises(modos.HuellaVencida):
            modos.confirmar(db, ROUTER, "ponderado", D(2026, 10, 15), HOY, USUARIO, vista.huella)
        db.rollback()

    assert _modos(engine) == [] and _auditoria(engine) == []


def test_back_to_fifo_from_a_pool_shows_what_no_unit_will_hand_out(engine: Engine) -> None:
    # The pool sold 100 at 9.00 (900); back to FIFO the first lot is used up and the second holds its own 800: of
    # the 1800 the lots hold, 100 is never handed out (D2: the preview shows it).
    _dos_lotes(engine)
    si.modo(engine, ROUTER, "ponderado", D(2026, 10, 1))
    si.venta(engine, "fuera", ROUTER, 100, D(2026, 10, 10))

    vista = _vista(engine, "fifo", D(2026, 10, 15))

    assert (vista.ventas_cambian, vista.diferencia_ars) == (0, Decimal("0.00"))
    assert (vista.unidades_restantes, vista.descuento_unit) == (100, Decimal("8.000000"))
    assert (vista.sin_asignar_antes, vista.sin_asignar_despues) == (Decimal("0.00"), Decimal("100.00"))


def test_a_cheaper_last_price_leaves_ars_no_unit_hands_out(engine: Engine) -> None:
    # D5's example: 100 left at 10 plus a new lot of 10 at 8 gives 110 at 8: 880 handed out against 1080 held.
    si.compra(engine, [(ROUTER, 100, "1000.00")], D(2026, 10, 1))
    si.compra(engine, [(ROUTER, 10, "80.00")], D(2026, 10, 2))

    vista = _vista(engine, "ultimo", D(2026, 10, 15))

    assert (vista.unidades_restantes, vista.descuento_unit) == (110, Decimal("8.000000"))
    assert vista.sin_asignar_despues == Decimal("200.00")


def test_a_dearer_last_price_hands_out_beyond_the_lots(engine: Engine) -> None:
    # 100 left at 8 plus a new lot of 10 at 10 gives 110 at 10: 1100 handed out against 900 held, 200 beyond them.
    si.compra(engine, [(ROUTER, 100, "800.00")], D(2026, 10, 1))
    si.compra(engine, [(ROUTER, 10, "100.00")], D(2026, 10, 2))

    vista = _vista(engine, "ultimo", D(2026, 10, 15))

    assert (vista.unidades_restantes, vista.descuento_unit) == (110, Decimal("10.000000"))
    assert vista.sin_asignar_despues == Decimal("-200.00")


@pytest.mark.parametrize(
    ("modo", "valor", "unidades", "sin_asignar"),
    [("ultimo", Decimal("8.000000"), 110, Decimal("200.00")), ("ponderado", Decimal("9.818182"), 110, Decimal("0.00"))],
)
def test_a_future_mode_is_previewed_as_it_will_stand_from_its_date(
    engine: Engine, modo, valor, unidades, sin_asignar
) -> None:
    # Today FIFO gives the first lot's 100 at 10.00; from tomorrow the mode governs all 110 (1080 held).
    si.compra(engine, [(ROUTER, 100, "1000.00")], D(2026, 10, 1))
    si.compra(engine, [(ROUTER, 10, "80.00")], D(2026, 10, 2))

    vista = _vista(engine, modo, D(2026, 11, 11))

    assert (vista.unidades_restantes, vista.descuento_unit, vista.sin_asignar_despues) == (unidades, valor, sin_asignar)


@pytest.mark.parametrize(
    ("modo", "desde", "tiene", "falta"),
    [
        ("ponderado", HOY, {"sell_in.costo_ultimo"}, "sell_in.costo_ponderado"),
        ("ultimo", HOY, {"sell_in.costo_ponderado"}, "sell_in.costo_ultimo"),
        ("fifo", HOY, set(), "sell_in.costo_ponderado | sell_in.costo_ultimo | sell_in.costo_manual"),
        ("fifo", HOY, {"sell_in.costo_manual"}, None),
        ("ponderado", D(2026, 11, 9), {"sell_in.costo_ponderado"}, "sell_in.costo_retroactivo"),
        ("ponderado", D(2026, 11, 9), {"sell_in.costo_ponderado", "sell_in.costo_retroactivo"}, None),
        ("ultimo", D(2026, 11, 11), {"sell_in.costo_ultimo"}, None),
    ],
)
def test_each_mode_needs_its_own_permission_and_a_past_date_the_backdating_one(modo, desde, tiene, falta) -> None:
    assert modos.permiso_faltante(modo, desde, HOY, tiene.__contains__) == falta
