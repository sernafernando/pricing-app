"""A `monto_total` campaign split by a criterion (tactical monto total, S2/S3/S6) on Postgres: `costo` stores fixed
per-product shares, cent-exact; `iguales` stores none and the rebuild splits the total in equal parts among the products
that sold in the dates (tactical iguales sell out S2/S3); `unidades` stores none and the rebuild spreads the total over every unit
sold in the dates, following returns; the manual split keeps working and clears the criterion; a brand-scoped user
cannot split by a criterion; the preview stores nothing. `_world`, like the other split tests."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Iterator, List, Optional

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.models.sell_out import SellOutCampana
from app.schemas.sell_out import SellOutCampanaIn, SellOutCampanaItemIn
from app.services.sell_out import campanas as service
from app.services.sell_out import criterio as criterio_service
from app.services.sell_out import queue
from app.services.sell_out import resumen
from app.services.sell_out.asignacion import recalcular
from tests.services.sell_out import _world as w

pytestmark = pytest.mark.postgres

USUARIO = 7
TP_LINK = {"marca": "TP-LINK"}
MERCUSYS = {"marca": "MERCUSYS"}
D = Decimal


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with w.world("sell_out_reparto_criterio") as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    yield
    w.clean(engine)
    w.execute(engine, "UPDATE productos_erp SET costo = NULL, moneda_costo = 'ARS'")


def _db(engine: Engine) -> Session:
    return sessionmaker(bind=engine, autoflush=False)()


def _tres(engine: Engine, total: str, **values) -> int:
    """A `monto_total` campaign over the three products (2964, 2270: TP-LINK; 950: MERCUSYS)."""
    return w.monto_total(engine, [w.grupo(engine, [TP_LINK, MERCUSYS])], total, **values)


def _costos(engine: Engine, **costos) -> None:
    for item_id, (costo, moneda) in costos.items():
        w.execute(
            engine,
            "UPDATE productos_erp SET costo = :c, moneda_costo = :m WHERE item_id = :i",
            c=costo,
            m=moneda,
            i=int(item_id[1:]),
        )


def _repartir(engine: Engine, campana: int, criterio: Optional[str], repartos=(), pares=None) -> None:
    with _db(engine) as db:
        service.repartir(db, campana, list(repartos), USUARIO, pares, criterio=criterio)


def _items(engine: Engine, campana: int) -> dict:
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT item_id, reparto_porcentaje, reparto_monto FROM sell_out_campana_items WHERE campana_id = :c"),
            {"c": campana},
        )
        return {item_id: (pct, monto) for item_id, pct, monto in rows}


def _criterio(engine: Engine, campana: int) -> Optional[str]:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT reparto_criterio FROM sell_out_campanas WHERE id = :c"), {"c": campana}
        ).scalar()


def _recalcular(engine: Engine, *ids: int) -> None:
    with _db(engine) as db:
        recalcular(db, ids)
        db.commit()


def _filas(engine: Engine, campana_id: int) -> List[tuple]:
    return [(r[3], r[5], r[6]) for r in w.consumos(engine, campana_id)]


def _reparto_resumen(engine: Engine, campana: int) -> dict:
    with _db(engine) as db:
        [out] = resumen.serializar(db, [db.get(SellOutCampana, campana)])
    return out["resumen"]["reparto"]


class TestIguales:
    """Sell out "iguales" (tactical iguales sell out S2/S3): no stored share; every rebuild splits the total in equal
    parts among the products with net sales in the dates, so the rebuild after the range ends is the recalculation."""

    def test_it_stores_the_criterion_and_no_share_and_queues_the_campaign(self, engine: Engine) -> None:
        campana = _tres(engine, "1000.00")
        w.reparto(engine, campana, 2964, monto="10.00")  # a previous manual split is replaced
        w.clear_queue(engine)

        _repartir(engine, campana, "iguales")

        assert _items(engine, campana) == {}
        assert _criterio(engine, campana) == "iguales"
        assert [row[0] for row in w.queued(engine)] == [campana]

    def test_a_product_with_no_sales_gets_no_share_and_the_ones_that_sold_split_it_all(self, engine: Engine) -> None:
        campana = _tres(engine, "1000.00")
        _repartir(engine, campana, "iguales")
        w.venta(engine, "ml", 2964, 2, date(2026, 11, 2))
        w.venta(engine, "ml", 2270, 1, date(2026, 11, 3))
        _recalcular(engine, campana)

        assert _filas(engine, campana) == [(2964, 2, D("500.00")), (2270, 1, D("500.00"))]
        assert _reparto_resumen(engine, campana) == {
            "asignado": D("1000.00"),
            "asignado_sin_ventas": D("0.00"),
            "sin_asignar": D("0.00"),
            "motivo": None,
        }

    def test_the_parts_add_up_to_the_total_to_the_cent(self, engine: Engine) -> None:
        campana = _tres(engine, "100.00")
        _repartir(engine, campana, "iguales")
        for item_id, dia in ((2964, 2), (2270, 3), (950, 4)):
            w.venta(engine, "ml", item_id, 1, date(2026, 11, dia))
        _recalcular(engine, campana)

        montos = [m for _, _, m in _filas(engine, campana)]
        assert sorted(montos) == [D("33.33"), D("33.33"), D("33.34")]
        assert sum(montos) == D("100.00")

    def test_a_negative_total_splits_negative_among_the_products_that_sold(self, engine: Engine) -> None:
        campana = _tres(engine, "-100.00")
        _repartir(engine, campana, "iguales")
        w.venta(engine, "ml", 2964, 1, date(2026, 11, 2))
        w.venta(engine, "ml", 950, 1, date(2026, 11, 3))
        _recalcular(engine, campana)

        assert _filas(engine, campana) == [(2964, 1, D("-50.00")), (950, 1, D("-50.00"))]

    def test_a_return_after_the_range_ends_requeues_and_moves_its_part(self, engine: Engine) -> None:
        campana = _tres(engine, "300.00")
        _repartir(engine, campana, "iguales")
        w.venta(engine, "fuera", 2964, 1, date(2026, 11, 2), cliente=55)
        w.venta(engine, "fuera", 2270, 1, date(2026, 11, 3), cliente=56)
        _recalcular(engine, campana)
        assert _filas(engine, campana) == [(2964, 1, D("150.00")), (2270, 1, D("150.00"))]

        # The range (Nov 1-30) is over; a return dated inside it arrives late and still queues the campaign.
        devolucion = w.venta(engine, "fuera", 2270, 1, date(2026, 11, 20), signo=-1, cliente=56)
        with _db(engine) as db:
            assert campana in queue.campanas_de_ventas(db, [("fuera", devolucion)])
        _recalcular(engine, campana)

        assert _filas(engine, campana) == [(2964, 1, D("300.00"))]

    def test_a_late_sale_of_a_product_that_had_none_joins_the_split(self, engine: Engine) -> None:
        campana = _tres(engine, "300.00")
        _repartir(engine, campana, "iguales")
        w.venta(engine, "ml", 2964, 1, date(2026, 11, 2))
        _recalcular(engine, campana)
        assert _filas(engine, campana) == [(2964, 1, D("300.00"))]

        tarde = w.venta(engine, "ml", 950, 1, date(2026, 11, 29))
        with _db(engine) as db:
            assert campana in queue.campanas_de_ventas(db, [("ml", tarde)])
        _recalcular(engine, campana)

        assert _filas(engine, campana) == [(2964, 1, D("150.00")), (950, 1, D("150.00"))]

    def test_without_sales_the_whole_total_is_sin_asignar(self, engine: Engine) -> None:
        campana = _tres(engine, "1200.00")
        _repartir(engine, campana, "iguales")
        _recalcular(engine, campana)

        assert _reparto_resumen(engine, campana)["sin_asignar"] == D("1200.00")
        assert _reparto_resumen(engine, campana)["asignado_sin_ventas"] == D("0.00")


class TestCosto:
    def test_shares_follow_each_product_cost_and_add_up_exactly(self, engine: Engine) -> None:
        _costos(engine, p2964=(100, "ARS"), p2270=(300, "ARS"), p950=(600, "ARS"))
        campana = _tres(engine, "1000.00")

        _repartir(engine, campana, "costo")

        assert {i: m for i, (_, m) in _items(engine, campana).items()} == {
            2964: D("100.00"),
            2270: D("300.00"),
            950: D("600.00"),
        }
        assert _criterio(engine, campana) == "costo"

    def test_a_usd_cost_converts_to_the_campaign_currency_at_the_latest_bna(self, engine: Engine) -> None:
        _costos(engine, p2964=(1000, "ARS"), p2270=(1, "USD"), p950=(None, "ARS"))
        w.tipo_cambio(engine, date(2026, 11, 1), 1000.0)
        campana = _tres(engine, "100.00")

        _repartir(engine, campana, "costo")

        # 950 has no cost: no share, the total goes to the products that have one.
        assert {i: m for i, (_, m) in _items(engine, campana).items()} == {2964: D("50.00"), 2270: D("50.00")}

    def test_no_product_with_a_cost_is_refused_and_nothing_changes(self, engine: Engine) -> None:
        campana = _tres(engine, "100.00")
        w.reparto(engine, campana, 2964, monto="10.00")

        with pytest.raises(service.SellOutError, match="costo"):
            _repartir(engine, campana, "costo")

        assert _items(engine, campana) == {2964: (None, D("10.00"))}
        assert _criterio(engine, campana) is None


class TestCostoEntreVendidos:
    """Sell out "costo" (orchestrator L2): the stored cost shares are weights; the rebuild splits the total by them
    among the products that sold in the dates, like "iguales"."""

    def test_a_product_with_no_sales_gets_no_share_and_the_ones_that_sold_split_it_by_cost(
        self, engine: Engine
    ) -> None:
        _costos(engine, p2964=(100, "ARS"), p2270=(300, "ARS"), p950=(600, "ARS"))
        campana = _tres(engine, "1000.00")
        _repartir(engine, campana, "costo")
        w.venta(engine, "ml", 2964, 2, date(2026, 11, 2))
        w.venta(engine, "ml", 2270, 1, date(2026, 11, 3))
        _recalcular(engine, campana)

        assert _filas(engine, campana) == [(2964, 2, D("250.00")), (2270, 1, D("750.00"))]
        assert _reparto_resumen(engine, campana) == {
            "asignado": D("1000.00"),
            "asignado_sin_ventas": D("0.00"),
            "sin_asignar": D("0.00"),
            "motivo": None,
        }

    def test_a_return_after_the_range_ends_requeues_and_moves_its_part(self, engine: Engine) -> None:
        _costos(engine, p2964=(100, "ARS"), p2270=(300, "ARS"), p950=(600, "ARS"))
        campana = _tres(engine, "1000.00")
        _repartir(engine, campana, "costo")
        w.venta(engine, "fuera", 2964, 1, date(2026, 11, 2), cliente=55)
        w.venta(engine, "fuera", 950, 1, date(2026, 11, 3), cliente=56)
        _recalcular(engine, campana)
        assert _filas(engine, campana) == [(2964, 1, D("142.86")), (950, 1, D("857.14"))]

        devolucion = w.venta(engine, "fuera", 950, 1, date(2026, 11, 20), signo=-1, cliente=56)
        with _db(engine) as db:
            assert campana in queue.campanas_de_ventas(db, [("fuera", devolucion)])
        _recalcular(engine, campana)

        assert _filas(engine, campana) == [(2964, 1, D("1000.00"))]

    def test_without_sales_the_whole_total_is_sin_asignar(self, engine: Engine) -> None:
        _costos(engine, p2964=(100, "ARS"), p2270=(300, "ARS"), p950=(600, "ARS"))
        campana = _tres(engine, "1000.00")
        _repartir(engine, campana, "costo")
        _recalcular(engine, campana)

        resumen_ = _reparto_resumen(engine, campana)
        assert (resumen_["asignado_sin_ventas"], resumen_["sin_asignar"]) == (D("0.00"), D("1000.00"))


class TestUnidades:
    def test_every_unit_sold_gets_the_same_share_and_a_return_moves_it(self, engine: Engine) -> None:
        campana = _tres(engine, "1200.00")
        w.reparto(engine, campana, 2964, monto="10.00")  # a previous manual split is replaced

        _repartir(engine, campana, "unidades")
        assert _items(engine, campana) == {}
        assert _criterio(engine, campana) == "unidades"

        w.venta(engine, "fuera", 2964, 2, date(2026, 11, 2), cliente=55)
        w.venta(engine, "ml", 2270, 1, date(2026, 11, 3))
        w.venta(engine, "ml", 950, 1, date(2026, 11, 4))
        _recalcular(engine, campana)
        assert _filas(engine, campana) == [(2964, 2, D("600.00")), (2270, 1, D("300.00")), (950, 1, D("300.00"))]

        w.venta(engine, "fuera", 2964, 1, date(2026, 11, 5), signo=-1, cliente=55)
        _recalcular(engine, campana)
        assert _filas(engine, campana) == [(2964, 1, D("400.00")), (2270, 1, D("400.00")), (950, 1, D("400.00"))]
        assert _reparto_resumen(engine, campana)["sin_asignar"] == D("0.00")

    def test_a_sale_outside_the_dates_does_not_count(self, engine: Engine) -> None:
        campana = _tres(engine, "100.00")
        _repartir(engine, campana, "unidades")
        w.venta(engine, "ml", 2964, 1, date(2026, 11, 2))
        w.venta(engine, "ml", 2270, 5, date(2026, 12, 2))
        _recalcular(engine, campana)

        assert _filas(engine, campana) == [(2964, 1, D("100.00"))]

    def test_without_sales_the_whole_total_is_sin_asignar(self, engine: Engine) -> None:
        campana = _tres(engine, "1200.00")
        _repartir(engine, campana, "unidades")
        _recalcular(engine, campana)

        assert _reparto_resumen(engine, campana) == {
            "asignado": D("0.00"),
            "asignado_sin_ventas": D("0.00"),
            "sin_asignar": D("1200.00"),
            "motivo": None,
        }


class TestManualYPermisos:
    def test_a_manual_split_still_works_and_clears_the_criterion(self, engine: Engine) -> None:
        campana = _tres(engine, "100.00")
        _repartir(engine, campana, "iguales")

        share = SellOutCampanaItemIn.model_validate({"item_id": 2964, "reparto_porcentaje": "60"})
        _repartir(engine, campana, None, [share])

        assert _items(engine, campana) == {2964: (D("60.0000"), None)}
        assert _criterio(engine, campana) is None

    def test_a_criterion_with_shares_is_refused(self, engine: Engine) -> None:
        campana = _tres(engine, "100.00")
        share = SellOutCampanaItemIn.model_validate({"item_id": 2964, "reparto_monto": "10"})

        with pytest.raises(service.SellOutError):
            _repartir(engine, campana, "iguales", [share])

    def test_a_brand_scoped_user_cannot_split_by_a_criterion(self, engine: Engine) -> None:
        campana = _tres(engine, "100.00")
        w.reparto(engine, campana, 950, monto="10.00")
        w.clear_queue(engine)

        with pytest.raises(service.SellOutSinPermiso):
            _repartir(engine, campana, "iguales", pares={("TP-LINK", "Routers")})

        assert _items(engine, campana) == {950: (None, D("10.00"))}
        assert _criterio(engine, campana) is None
        assert w.queued(engine) == []

    def test_a_criterion_on_a_campaign_that_is_not_monto_total_is_refused(self, engine: Engine) -> None:
        campana = w.campana(engine, [w.grupo(engine, [TP_LINK])])
        with pytest.raises(service.SellOutError):
            _repartir(engine, campana, "iguales")


class TestVistaPrevia:
    @pytest.mark.parametrize("criterio", ["iguales", "unidades", "costo"])
    def test_the_preview_stores_nothing(self, engine: Engine, criterio: str) -> None:
        _costos(engine, p2964=(100, "ARS"), p2270=(100, "ARS"), p950=(200, "ARS"))
        campana = _tres(engine, "100.00")
        w.reparto(engine, campana, 2964, monto="10.00")
        w.clear_queue(engine)

        with _db(engine) as db:
            criterio_service.vista_previa(db, db.get(SellOutCampana, campana), criterio)
            db.commit()

        assert _items(engine, campana) == {2964: (None, D("10.00"))}
        assert _criterio(engine, campana) is None
        assert w.queued(engine) == []

    def test_the_preview_by_units_shows_each_product_units_and_amount(self, engine: Engine) -> None:
        campana = _tres(engine, "300.00")
        w.venta(engine, "ml", 2964, 2, date(2026, 11, 2))
        w.venta(engine, "ml", 2270, 1, date(2026, 11, 3))

        with _db(engine) as db:
            previa = criterio_service.vista_previa(db, db.get(SellOutCampana, campana), "unidades")

        assert previa["criterio"] == "unidades"
        assert previa["monto_total"] == D("300.00")
        assert {i["item_id"]: (i["codigo"], i["unidades"], i["monto"]) for i in previa["items"]} == {
            2964: ("C2964", 2, D("200.00")),
            2270: ("C2270", 1, D("100.00")),
            950: ("C950", 0, D("0.00")),
        }
        assert previa["sin_asignar"] == D("0.00")

    def test_the_preview_in_equal_parts_splits_among_the_products_sold_so_far(self, engine: Engine) -> None:
        campana = _tres(engine, "300.00")
        w.venta(engine, "ml", 2964, 2, date(2026, 11, 2))
        w.venta(engine, "ml", 2270, 1, date(2026, 11, 3))

        with _db(engine) as db:
            previa = criterio_service.vista_previa(db, db.get(SellOutCampana, campana), "iguales")

        assert {i["item_id"]: (i["unidades"], i["monto"]) for i in previa["items"]} == {
            2964: (2, D("150.00")),
            2270: (1, D("150.00")),
            950: (0, D("0.00")),
        }
        assert previa["sin_asignar"] == D("0.00")

    def test_the_preview_by_cost_splits_among_the_products_sold_so_far(self, engine: Engine) -> None:
        _costos(engine, p2964=(100, "ARS"), p2270=(300, "ARS"), p950=(600, "ARS"))
        campana = _tres(engine, "1000.00")
        w.venta(engine, "ml", 2964, 1, date(2026, 11, 2))
        w.venta(engine, "ml", 2270, 1, date(2026, 11, 3))

        with _db(engine) as db:
            previa = criterio_service.vista_previa(db, db.get(SellOutCampana, campana), "costo")
        _repartir(engine, campana, "costo")
        _recalcular(engine, campana)

        assert {i["item_id"]: i["monto"] for i in previa["items"]} == {
            2964: D("250.00"),
            2270: D("750.00"),
            950: D("0.00"),
        }
        assert {i: m for i, _, m in _filas(engine, campana)} == {2964: D("250.00"), 2270: D("750.00")}
        assert previa["sin_asignar"] == D("0.00")


class TestCrearYEditar:
    def _entrada(self, engine: Engine, **values) -> SellOutCampanaIn:
        return SellOutCampanaIn.model_validate(
            {
                "nombre": "Notebooks",
                "fecha_desde": "2026-11-01",
                "fecha_hasta": "2026-11-30",
                "tipo": "monto_total",
                "monto_total": "1200.00",
                "moneda": "ARS",
                "grupo_ids": [w.grupo(engine, [TP_LINK, MERCUSYS])],
                **values,
            }
        )

    def test_a_campaign_created_with_a_criterion_stores_it_and_its_shares(self, engine: Engine) -> None:
        _costos(engine, p2964=(100, "ARS"), p2270=(100, "ARS"), p950=(100, "ARS"))
        with _db(engine) as db:
            campana = service.crear_campana(db, self._entrada(engine, reparto_criterio="costo"), USUARIO).id

        assert _criterio(engine, campana) == "costo"
        assert sorted(m for _, m in _items(engine, campana).values()) == [D("400.00")] * 3

    def test_a_campaign_created_split_in_equal_parts_stores_no_share(self, engine: Engine) -> None:
        with _db(engine) as db:
            campana = service.crear_campana(db, self._entrada(engine, reparto_criterio="iguales"), USUARIO).id

        assert (_criterio(engine, campana), _items(engine, campana)) == ("iguales", {})

    def test_a_criterion_with_items_on_create_is_refused(self, engine: Engine) -> None:
        entrada = self._entrada(engine, reparto_criterio="iguales", items=[{"item_id": 2964, "reparto_monto": "10.00"}])
        with _db(engine) as db, pytest.raises(service.SellOutError):
            service.crear_campana(db, entrada, USUARIO)

    def test_a_criterion_on_a_per_unit_campaign_is_refused(self, engine: Engine) -> None:
        entrada = self._entrada(
            engine, tipo="por_unidad", monto_total=None, monto_unit="10.00", reparto_criterio="iguales"
        )
        with _db(engine) as db, pytest.raises(service.SellOutError):
            service.crear_campana(db, entrada, USUARIO)

    def test_an_edit_without_items_keeps_the_criterion_and_resplits_the_new_total(self, engine: Engine) -> None:
        _costos(engine, p2964=(100, "ARS"), p2270=(100, "ARS"), p950=(100, "ARS"))
        with _db(engine) as db:
            campana = service.crear_campana(db, self._entrada(engine, reparto_criterio="costo"), USUARIO).id
        grupo = w.grupo(engine, [TP_LINK, MERCUSYS])

        with _db(engine) as db:
            service.editar_campana(db, campana, self._entrada(engine, monto_total="300.00", grupo_ids=[grupo]), USUARIO)

        assert _criterio(engine, campana) == "costo"
        assert sorted(m for _, m in _items(engine, campana).values()) == [D("100.00")] * 3

    def test_an_edit_of_an_equal_parts_campaign_keeps_it_with_no_share(self, engine: Engine) -> None:
        with _db(engine) as db:
            campana = service.crear_campana(db, self._entrada(engine, reparto_criterio="iguales"), USUARIO).id

        with _db(engine) as db:
            service.editar_campana(db, campana, self._entrada(engine, monto_total="300.00"), USUARIO)

        assert (_criterio(engine, campana), _items(engine, campana)) == ("iguales", {})

    def test_an_edit_with_items_is_a_manual_split(self, engine: Engine) -> None:
        with _db(engine) as db:
            campana = service.crear_campana(db, self._entrada(engine, reparto_criterio="unidades"), USUARIO).id

        entrada = self._entrada(engine, items=[{"item_id": 2964, "reparto_monto": "100.00"}])
        with _db(engine) as db:
            service.editar_campana(db, campana, entrada, USUARIO)

        assert _criterio(engine, campana) is None
        assert _items(engine, campana) == {2964: (None, D("100.00"))}

    def test_an_edit_to_per_unit_clears_the_criterion(self, engine: Engine) -> None:
        with _db(engine) as db:
            campana = service.crear_campana(db, self._entrada(engine, reparto_criterio="unidades"), USUARIO).id
        entrada = self._entrada(engine, tipo="por_unidad", monto_total=None, monto_unit="10.00", items=[])

        with _db(engine) as db:
            service.editar_campana(db, campana, entrada, USUARIO)

        assert _criterio(engine, campana) is None

    def test_an_edit_that_keeps_total_and_groups_does_not_move_cost_shares(self, engine: Engine) -> None:
        _costos(engine, p2964=(100, "ARS"), p2270=(100, "ARS"), p950=(200, "ARS"))
        entrada = self._entrada(engine, reparto_criterio="costo")
        with _db(engine) as db:
            campana = service.crear_campana(db, entrada, USUARIO).id
        antes = _items(engine, campana)
        _costos(engine, p950=(800, "ARS"))  # costs move after the split

        with _db(engine) as db:
            service.editar_campana(
                db, campana, entrada.model_copy(update={"nombre": "Otro", "reparto_criterio": None}), USUARIO
            )

        assert _items(engine, campana) == antes
        assert _criterio(engine, campana) == "costo"


class TestPmSobreCriterio:
    @pytest.mark.parametrize("criterio", ["iguales", "unidades", "costo"])
    def test_a_brand_scoped_manual_split_cannot_drop_a_criterion(self, engine: Engine, criterio: str) -> None:
        _costos(engine, p2964=(100, "ARS"), p2270=(100, "ARS"), p950=(100, "ARS"))
        campana = _tres(engine, "300.00")
        _repartir(engine, campana, criterio)
        antes = _items(engine, campana)
        w.clear_queue(engine)
        share = SellOutCampanaItemIn.model_validate({"item_id": 2964, "reparto_monto": "10.00"})

        with pytest.raises(service.SellOutSinPermiso, match="todas las marcas"):
            _repartir(engine, campana, None, [share], pares={("TP-LINK", "Routers")})

        assert (_items(engine, campana), _criterio(engine, campana)) == (antes, criterio)
        assert w.queued(engine) == []


class TestVistaPreviaAnulada:
    def test_the_preview_of_a_voided_campaign_is_refused(self, engine: Engine) -> None:
        campana = _tres(engine, "100.00", estado="anulada")
        with _db(engine) as db, pytest.raises(criterio_service.CriterioError, match="anulada"):
            criterio_service.vista_previa(db, db.get(SellOutCampana, campana), "iguales")
