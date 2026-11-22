"""A sell-in cost bonus over a TOTAL split across its products (tactical monto total S4).

Owner: "si me bajan USD1200 por x modelos de notebook, quiero poder dividir entre esas notebooks [...] no puedo poner
un total y que aplique el total a los productos en ese rango de fecha"; the split rule: "un selector"; sell in too:
"sí, es para los dos". A `tipo = 'monto_total'` cost bonus (`base = 'costo_venta'`, ARS) stores its total and
`reparto_criterio`: `iguales` and `costo` keep fixed per-product shares (`sell_in_bono_repartos`, cent-exact, adding
up to the total), each spread over its product's net units sold in the dates; `unidades` spreads the whole total over
every net unit. A negative or zero total is refused (`descuento_ars >= 0` stays), and so are caps.

Postgres only, in a throwaway schema (`_bono_world`)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Iterator

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.models.sell_in import SellInBonoReparto
from app.schemas.sell_in_bonos import SellInBonoIn
from app.services.sell_in import bonos_costo, bonos_crud
from tests.services.sell_in import _bono_world as b
from tests.services.sell_in import _world as w

D = date
pytestmark = pytest.mark.postgres


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with b.world("sell_in_bonos_total") as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    yield
    b.clean(engine)


@pytest.fixture
def db(engine: Engine) -> Iterator[Session]:
    session = sessionmaker(bind=engine, autoflush=False)()
    try:
        yield session
    finally:
        session.close()


def _entrada(**overrides) -> SellInBonoIn:
    body = {
        "base": "costo_venta",
        "alcance": "marca",
        "marca": b.TPLINK,
        "tipo": "monto_total",
        "monto_total": "1000.00",
        "reparto_criterio": "iguales",
        "moneda": "ARS",
        "fecha_desde": D(2026, 10, 1),
        "fecha_hasta": D(2026, 10, 31),
    }
    body.update(overrides)
    return SellInBonoIn(**body)


def _crear(db: Session, **overrides) -> int:
    return bonos_crud.crear_bono(db, _entrada(**overrides), 7).id


def _repartos(db: Session, bono_id: int) -> dict[int, Decimal]:
    filas = db.query(SellInBonoReparto.item_id, SellInBonoReparto.monto).filter(SellInBonoReparto.bono_id == bono_id)
    return dict(filas.order_by(SellInBonoReparto.item_id).all())


def _fuera(engine: Engine, item_id: int, unidades: int, dia: date, costo_unit: str = "1000.00", **kw) -> int:
    ref = w.venta(engine, "fuera", item_id, unidades, dia, **kw)
    w.update_venta(engine, "fuera", ref, costo_total=Decimal(costo_unit) * unidades)
    return ref


def _recalcular(engine: Engine, *item_ids: int) -> bonos_costo.CostoResult:
    with sessionmaker(bind=engine, autoflush=False)() as db:
        result = bonos_costo.recalcular(db, item_ids)
        db.commit()
    return result


def _filas(engine: Engine):
    """`(bono_id, venta_ref, item_id, unidades, descuento_ars)` in sale order."""
    return [(r[0], r[2], r[3], r[5], r[6]) for r in b.bono_consumos(engine)]


class TestCrear:
    @pytest.mark.parametrize(
        ("overrides", "mensaje"),
        [
            ({"tipo": "por_unidad", "monto_unit": "2.00", "monto_total": "10.00", "reparto_criterio": None},
             "Solo un bono por monto total lleva monto total"),
            ({"tipo": "porcentaje", "porcentaje": "3", "monto_total": None},
             "El reparto es solo para un bono por monto total"),
        ],
    )  # fmt: skip
    def test_a_per_unit_or_percentage_bonus_takes_no_total_nor_criterion(self, db, overrides, mensaje) -> None:
        with pytest.raises(bonos_crud.SellInBonoError) as exc:
            _crear(db, **overrides)

        assert str(exc.value) == mensaje
