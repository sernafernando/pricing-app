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
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.models.sell_in import SellInBonoReparto
from app.schemas.sell_in_bonos import SellInBonoIn
from app.services.sell_in import bonos_costo, bonos_crud
from app.services.sell_in.costing import get_costing
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
    def test_equal_parts_store_one_share_per_product_of_the_scope_adding_up_to_the_total(self, db) -> None:
        bono_id = _crear(db, monto_total="1000.01")

        # Split by `split.split('por_unidad')`: the odd cent goes to the first product.
        assert _repartos(db, bono_id) == {2270: Decimal("500.00"), 2964: Decimal("500.01")}
        [fila] = bonos_crud.serializar(db, [bonos_crud.listar_bonos(db, bonos_crud.FiltrosBonos())[0][0]])
        assert (fila["tipo"], fila["monto_total"], fila["reparto_criterio"]) == (
            "monto_total",
            Decimal("1000.01"),
            "iguales",
        )
        assert [(r["item_id"], r["codigo"], r["monto"]) for r in fila["repartos"]] == [
            (2270, "C2270", Decimal("500.00")),
            (2964, "C2964", Decimal("500.01")),
        ]

    def test_by_cost_shares_follow_each_product_cost_in_pesos(self, db, engine) -> None:
        b.tipo_cambio(engine, D(2026, 10, 1), 1000)  # 2964 costs USD 41.50 = ARS 41500; 2270 ARS 12000

        bono_id = _crear(db, monto_total="10000.00", reparto_criterio="costo")

        # 10000 x 41500 / 53500 = 7757.009..., 10000 x 12000 / 53500 = 2242.990...
        assert _repartos(db, bono_id) == {2270: Decimal("2242.99"), 2964: Decimal("7757.01")}

    def test_by_units_stores_the_criterion_and_no_share(self, db) -> None:
        bono_id = _crear(db, reparto_criterio="unidades")

        assert _repartos(db, bono_id) == {}
        [fila] = bonos_crud.serializar(db, [db.get(bonos_crud.SellInBonoMarca, bono_id)])
        assert (fila["reparto_criterio"], fila["repartos"]) == ("unidades", [])

    def test_models_scope_splits_only_among_its_models(self, db) -> None:
        bono_id = _crear(db, alcance="modelos", marca=None, modelos=[2964, 950], monto_total="90.00")

        assert _repartos(db, bono_id) == {950: Decimal("45.00"), 2964: Decimal("45.00")}

    @pytest.mark.parametrize(
        ("overrides", "mensaje"),
        [
            (
                {"monto_total": "-1200.00"},
                "El monto total debe ser mayor que cero: en sell in no se descuenta un monto negativo",
            ),
            (
                {"monto_total": "0"},
                "El monto total debe ser mayor que cero: en sell in no se descuenta un monto negativo",
            ),
            ({"monto_total": None}, "Falta el monto total del bono"),
            ({"reparto_criterio": None}, "Elegí cómo repartir el monto total"),
            ({"tope_unidades": 5}, "Un monto total no lleva topes: el total es su tope"),
            ({"tope_monto": "100.00"}, "Un monto total no lleva topes: el total es su tope"),
            ({"monto_unit": "2.00"}, "Un bono por monto total no lleva monto por unidad ni porcentaje"),
            ({"base": "factura", "moneda": "ARS"}, "Un bono por monto total es solo sobre el costo de la venta"),
        ],
    )
    def test_a_broken_rule_is_refused_with_its_message_and_stores_nothing(self, db, engine, overrides, mensaje) -> None:
        with pytest.raises(bonos_crud.SellInBonoError) as exc:
            _crear(db, **overrides)
        db.rollback()

        assert str(exc.value) == mensaje
        with engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM sell_in_bonos_marca")).scalar() == 0

    def test_a_model_with_its_own_value_is_refused(self, db) -> None:
        with pytest.raises(
            bonos_crud.SellInBonoError, match="^Un bono por monto total no lleva valor propio por modelo$"
        ):
            _crear(db, alcance="modelos", marca=None, modelos=[{"item_id": 2964, "monto_unit": "3.00"}])

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


class TestEditar:
    def test_a_new_total_resplits_the_shares_and_queues_the_bonus(self, db, engine) -> None:
        bono_id = _crear(db)
        b.clear_queue(engine)

        bonos_crud.editar_bono(db, bono_id, _entrada(monto_total="600.00"), 7)

        assert _repartos(db, bono_id) == {2270: Decimal("300.00"), 2964: Decimal("300.00")}
        assert b.queued(engine) == [("bono", bono_id)]

    def test_an_edit_that_keeps_total_criterion_and_reach_keeps_the_shares(self, db, engine) -> None:
        """Shares are fixed when saved: a date or text edit does not split again with today's costs and rate."""
        b.tipo_cambio(engine, D(2026, 10, 1), 1000)
        bono_id = _crear(db, monto_total="10000.00", reparto_criterio="costo")
        b.tipo_cambio(engine, D(2026, 10, 2), 2000)  # 2964 now ARS 83000: a resplit would move its share
        b.clear_queue(engine)

        bonos_crud.editar_bono(
            db, bono_id, _entrada(monto_total="10000.00", reparto_criterio="costo", fecha_hasta=D(2026, 11, 30)), 7
        )

        assert _repartos(db, bono_id) == {2270: Decimal("2242.99"), 2964: Decimal("7757.01")}
        # Queued once, by its row trigger: the new dates change which sales it credits, its shares stay.
        assert b.queued(engine) == [("bono", bono_id)]

    def test_a_new_reach_resplits_the_shares(self, db) -> None:
        bono_id = _crear(db, alcance="modelos", marca=None, modelos=[2964, 950], monto_total="90.00")

        bonos_crud.editar_bono(
            db, bono_id, _entrada(alcance="modelos", marca=None, modelos=[2964, 950, 2270], monto_total="90.00"), 7
        )

        assert _repartos(db, bono_id) == {950: Decimal("30.00"), 2270: Decimal("30.00"), 2964: Decimal("30.00")}

    def test_switching_to_units_drops_the_shares(self, db) -> None:
        bono_id = _crear(db)

        bonos_crud.editar_bono(db, bono_id, _entrada(reparto_criterio="unidades"), 7)

        assert _repartos(db, bono_id) == {}

    def test_the_stored_entry_keeps_the_total_and_its_criterion(self, db, engine) -> None:
        b.tipo_cambio(engine, D(2026, 10, 1), 1000)
        bono_id = _crear(db, reparto_criterio="costo", monto_total="10.00")
        entrada = bonos_crud.entrada_guardada(db, db.get(bonos_crud.SellInBonoMarca, bono_id))

        assert (entrada.tipo, entrada.monto_total, entrada.reparto_criterio) == (
            "monto_total",
            Decimal("10.00"),
            "costo",
        )


class TestMotor:
    def test_equal_parts_spread_each_share_over_its_product_s_units_to_the_cent(self, db, engine) -> None:
        bono_id = _crear(db)
        una = _fuera(engine, 2964, 1, D(2026, 10, 5))
        dos = _fuera(engine, 2964, 2, D(2026, 10, 6))
        _fuera(engine, 2964, 1, D(2026, 11, 2))  # outside the dates

        result = _recalcular(engine, 2964)

        # 2964's share 500.00 over its 3 units: 166.67 (cents of 500 x 1/3), then 500.00 - 166.67. 2270 sold nothing:
        # its share stays unwritten.
        assert _filas(engine) == [
            (bono_id, una, 2964, 1, Decimal("166.67")),
            (bono_id, dos, 2964, 2, Decimal("333.33")),
        ]
        assert result.failed == {}

    def test_a_product_with_no_sale_in_the_dates_writes_nothing(self, db, engine) -> None:
        _crear(db)
        _fuera(engine, 2270, 1, D(2026, 9, 30))

        _recalcular(engine, 2270)

        assert _filas(engine) == []

    def test_by_cost_each_product_gets_its_fixed_share(self, db, engine) -> None:
        b.tipo_cambio(engine, D(2026, 10, 1), 1000)
        bono_id = _crear(db, monto_total="10000.00", reparto_criterio="costo")
        tp = _fuera(engine, 2964, 2, D(2026, 10, 5))
        forza = _fuera(engine, 2270, 1, D(2026, 10, 5))

        _recalcular(engine, 2964)  # one product recomputes the whole bonus: its total couples them

        assert sorted(_filas(engine)) == sorted(
            [(bono_id, tp, 2964, 2, Decimal("7757.01")), (bono_id, forza, 2270, 1, Decimal("2242.99"))]
        )

    def test_by_units_every_unit_gets_the_same_share_and_the_rows_add_up_to_the_total(self, db, engine) -> None:
        bono_id = _crear(db, reparto_criterio="unidades")
        tp = _fuera(engine, 2964, 1, D(2026, 10, 5))
        forza = _fuera(engine, 2270, 2, D(2026, 10, 6))

        _recalcular(engine, 2964, 2270)

        assert _filas(engine) == [
            (bono_id, tp, 2964, 1, Decimal("333.33")),
            (bono_id, forza, 2270, 2, Decimal("666.67")),
        ]

    def test_by_units_a_return_moves_its_share_to_the_units_kept(self, db, engine) -> None:
        bono_id = _crear(db, reparto_criterio="unidades")
        tp = _fuera(engine, 2964, 1, D(2026, 10, 5))
        forza = _fuera(engine, 2270, 2, D(2026, 10, 6))
        w.venta(engine, "fuera", 2270, 1, D(2026, 10, 7), signo=-1)

        _recalcular(engine, 2964, 2270)

        assert _filas(engine) == [
            (bono_id, tp, 2964, 1, Decimal("500.00")),
            (bono_id, forza, 2270, 1, Decimal("500.00")),
        ]

    def test_units_invoice_sell_in_took_are_not_the_total_s(self, db, engine) -> None:
        w.compra(engine, [(2964, 5, "300.00")], D(2026, 10, 1))  # covers the 2964 sale whole (rule 5)
        bono_id = _crear(db, reparto_criterio="unidades")
        _fuera(engine, 2964, 5, D(2026, 10, 5))
        forza = _fuera(engine, 2270, 1, D(2026, 10, 6))
        with sessionmaker(bind=engine)() as s:
            get_costing().recompute(s, [2964], isolate_failures=False)
            s.commit()

        _recalcular(engine, 2964, 2270)

        assert _filas(engine) == [(bono_id, forza, 2270, 1, Decimal("1000.00"))]

    def test_with_vat_each_row_is_divided_by_its_product_s_rate(self, db, engine) -> None:
        b.set_iva(engine, 2964, 21.0)
        bono_id = _crear(db, reparto_criterio="unidades", incluye_iva=True)
        ref = _fuera(engine, 2964, 1, D(2026, 10, 5))

        _recalcular(engine, 2964)

        assert _filas(engine) == [(bono_id, ref, 2964, 1, Decimal("826.45"))]  # 1000 / 1.21

    def test_a_percentage_bonus_on_the_same_sale_is_unchanged(self, db, engine) -> None:
        pct = b.bono_costo(engine, "3.00")
        total = _crear(db, reparto_criterio="unidades")
        ref = _fuera(engine, 2964, 2, D(2026, 10, 5))

        _recalcular(engine, 2964)

        # 3 % of 1000.00 x 2 units, as without the total bonus; the total takes its 1000.00 over the same 2 units.
        assert sorted(_filas(engine)) == sorted(
            [(pct, ref, 2964, 2, Decimal("60.00")), (total, ref, 2964, 2, Decimal("1000.00"))]
        )

    def test_the_product_panel_reads_a_total_bonus_as_nothing_per_unit(self, db) -> None:
        bono = db.get(bonos_crud.SellInBonoMarca, _crear(db))

        assert bonos_costo.valor_del_bono(bono, None) == Decimal(0)
        assert bonos_costo.unitario(bono, Decimal(0), Decimal("1000"), 2964, None, D(2026, 10, 5)) == Decimal(0)


class TestCombos:
    """Owner, 2026-11-11 (S4): "si cargo por Marca, no me contabilice 2 veces los productos que están en un combo [...]
    me tome la parte que lo componga y no el combo persé como parte". A combo whose own row carries the brand is never
    a product of the split: its sales count under its components (2026-11-05), so a share of its own is never paid."""

    def test_a_combo_of_the_brand_gets_no_share_of_its_own(self, db, engine) -> None:
        w.combo(engine, 2270, {950: 1, 2964: 2})  # 2270 is TP-LINK: the brand reaches the combo and the WH

        bono_id = _crear(db)

        assert _repartos(db, bono_id) == {2964: Decimal("1000.00")}

    def test_a_combo_sale_pays_the_whole_total_through_its_component(self, db, engine) -> None:
        w.combo(engine, 2270, {950: 1, 2964: 2})
        bono_id = _crear(db)
        ref = _fuera(engine, 2270, 1, D(2026, 10, 5))

        _recalcular(engine, 2964)

        assert _filas(engine) == [(bono_id, ref, 2964, 2, Decimal("1000.00"))]
