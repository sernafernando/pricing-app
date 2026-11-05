"""A combo sale counts for the sell-out campaigns of each component (owner, 2026-11-05: "cuenta para sus campañas de
sell out. En una campaña por % de precio, a la notebook le toca la parte del precio del combo proporcional a su costo
dentro del combo."): `qty x cantidad` units under the component, the combo's price split by cost share, one row per
component even when both share a campaign, never the combo as its own item, and the queue fan-out reaches the
components' campaigns."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Iterator

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from app.services.sell_out import queue as sell_out_queue
from app.services.sell_out.asignacion import recalcular
from tests.services.sell_in import _world as wi
from tests.services.sell_out import _world as w

pytestmark = pytest.mark.postgres

NOTEBOOK, WH, COMBO = 950, 2964, 2270  # the combo is one notebook plus two WH units
DIA = date(2026, 11, 5)


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with w.world("sell_out_combos") as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    yield
    w.clean(engine)
    w.execute(engine, "DELETE FROM combo_componentes WHERE combo_item_id <> 999999001")
    w.execute(engine, "UPDATE productos_erp SET costo = NULL, moneda_costo = NULL")


def _combo(engine: Engine) -> None:
    wi.combo(engine, COMBO, {NOTEBOOK: 1, WH: 2})
    # The notebook weighs 600 and the two WH units 2 x 200 = 400: 60 % and 40 % of the combo.
    w.execute(engine, "UPDATE productos_erp SET costo = 600, moneda_costo = 'ARS' WHERE item_id = :i", i=NOTEBOOK)
    w.execute(engine, "UPDATE productos_erp SET costo = 200, moneda_costo = 'ARS' WHERE item_id = :i", i=WH)


def _recalcular(engine: Engine, *ids: int) -> None:
    with sessionmaker(bind=engine)() as db:
        recalcular(db, ids)
        db.commit()


def _filas(engine: Engine, cid: int) -> list:
    return [(x[2], x[3], x[5], x[6]) for x in w.consumos(engine, cid)]


def test_a_per_unit_campaign_counts_each_components_units_one_row_each(engine: Engine) -> None:
    _combo(engine)
    cid = w.campana(engine, [w.grupo(engine, [{"item_id": NOTEBOOK}, {"item_id": WH}])])
    ref = w.venta(engine, "fuera", COMBO, 1, DIA)

    _recalcular(engine, cid)

    assert sorted(_filas(engine, cid)) == [(ref, NOTEBOOK, 1, Decimal("10.00")), (ref, WH, 2, Decimal("20.00"))]


def test_a_percentage_of_price_campaign_gives_each_component_its_cost_share_of_the_combo_price(engine: Engine) -> None:
    _combo(engine)
    grupo = w.grupo(engine, [{"item_id": NOTEBOOK}, {"item_id": WH}])
    cid = w.campana(engine, [grupo], tipo="porcentaje", monto_unit=None, porcentaje="10", base_porcentaje="precio_neto")
    ref = w.venta(engine, "fuera", COMBO, 1, DIA)  # the world's fuera price: 54298.64 for the combo

    _recalcular(engine, cid)

    # Notebook: 10 % of 60 % of 54298.64. WH: 10 % of 40 %, over its 2 units.
    assert sorted(_filas(engine, cid)) == [(ref, NOTEBOOK, 1, Decimal("3257.92")), (ref, WH, 2, Decimal("2171.95"))]


def test_the_combo_is_never_counted_as_its_own_item(engine: Engine) -> None:
    _combo(engine)
    cid = w.campana(engine, [w.grupo(engine, [{"marca": "TP-LINK"}])])  # reaches the combo itself and the WH
    ref = w.venta(engine, "fuera", COMBO, 1, DIA)

    _recalcular(engine, cid)

    assert _filas(engine, cid) == [(ref, WH, 2, Decimal("20.00"))]


def test_a_combo_return_gives_back_each_components_units(engine: Engine) -> None:
    _combo(engine)
    cid = w.campana(engine, [w.grupo(engine, [{"item_id": NOTEBOOK}, {"item_id": WH}])])
    w.venta(engine, "fuera", COMBO, 1, DIA)
    w.venta(engine, "fuera", COMBO, 1, date(2026, 11, 6), signo=-1)

    _recalcular(engine, cid)

    assert _filas(engine, cid) == []


def test_a_combo_line_queues_the_campaigns_of_its_components(engine: Engine) -> None:
    _combo(engine)
    cid = w.campana(engine, [w.grupo(engine, [{"item_id": NOTEBOOK}])])
    ref = w.venta(engine, "fuera", COMBO, 1, DIA)

    with sessionmaker(bind=engine)() as db:
        assert sell_out_queue.campanas_de_ventas(db, [("fuera", ref)]) == {cid}
