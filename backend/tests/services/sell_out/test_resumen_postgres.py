"""What each sell-out campaign credited, read for the T8 screen (sell-in-sell-out T7 S5).

The figures come from the allocator's own rows (`sell_out_consumos`, written by
`asignacion.recalcular`), the queue (`sell_out_dirty`) and the allocator's
advisory lock. Postgres only (the lock, `round(numeric)`); `_world`.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Iterator, List

import pytest
from sqlalchemy import Engine, event, text
from sqlalchemy.orm import sessionmaker

from app.models.sell_out import SellOutCampana
from app.services.sell_out import asignacion, queue, resumen
from tests.services.sell_out import _world as w

pytestmark = pytest.mark.postgres

D = date
ROUTERS = {"marca": "TP-LINK", "categoria": "Routers"}


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with w.world("sell_out_resumen") as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    yield
    w.clean(engine)


def _recalcular(engine: Engine, *ids: int) -> asignacion.RecomputeResult:
    with sessionmaker(bind=engine)() as db:
        result = asignacion.recalcular(db, ids)
        db.commit()
    return result


def _resumenes(engine: Engine, *ids: int) -> dict:
    with sessionmaker(bind=engine)() as db:
        campanas = db.query(SellOutCampana).filter(SellOutCampana.id.in_(ids)).all()
        return resumen.resumenes(db, campanas)


def _detalle(engine: Engine, campana_id: int, page: int = 1, page_size: int = 50):
    with sessionmaker(bind=engine)() as db:
        return resumen.consumos(db, db.get(SellOutCampana, campana_id), page=page, page_size=page_size)


def _fuera(engine: Engine, item_id: int, cantidad: int, dia: date, costo: str) -> int:
    ref = w.venta(engine, "fuera", item_id, cantidad, dia)
    w.execute(engine, "UPDATE ventas_fuera_ml_metricas SET costo_total = :c WHERE it_transaction = :r", c=costo, r=ref)
    return ref


class TestMontos:
    def test_an_ars_campaign_adds_its_rows_by_channel_and_shows_what_the_cap_has_left(self, engine: Engine) -> None:
        campana = w.campana(engine, [w.grupo(engine, [ROUTERS])], monto_unit="10.00", tope_unidades=10)
        w.venta(engine, "ml", 2964, 2, D(2026, 11, 2))
        w.venta(engine, "fuera", 2964, 3, D(2026, 11, 3))
        w.venta(engine, "tn", 2964, 1, D(2026, 11, 4))
        _recalcular(engine, campana)

        r = _resumenes(engine, campana)[campana]

        assert (r["lineas"], r["unidades"], r["monto"]) == (3, 6, Decimal("60.00"))
        assert (r["monto_ars"], r["ars_estimado"]) == (Decimal("60.00"), False)
        assert (r["tope_unidades_restantes"], r["tope_monto_restante"]) == (4, None)
        assert r["por_canal"] == [
            {"canal": "ml", "lineas": 1, "unidades": 2, "monto": Decimal("20.00")},
            {"canal": "fuera", "lineas": 1, "unidades": 3, "monto": Decimal("30.00")},
            {"canal": "tn", "lineas": 1, "unidades": 1, "monto": Decimal("10.00")},
        ]

    def test_a_usd_fixed_rate_campaign_converts_each_row_at_its_rate(self, engine: Engine) -> None:
        campana = w.campana(
            engine,
            [w.grupo(engine, [ROUTERS])],
            monto_unit="1.25",
            moneda="USD",
            tc_modo="fijo",
            tipo_cambio="1000.5",
            tope_monto="10.00",
        )
        w.venta(engine, "ml", 2964, 3, D(2026, 11, 2))
        _recalcular(engine, campana)

        r = _resumenes(engine, campana)[campana]

        assert (r["unidades"], r["monto"]) == (3, Decimal("3.75"))
        assert (r["monto_ars"], r["ars_estimado"]) == (Decimal("3751.88"), False)  # 3.75 x 1000.5, to cents
        assert (r["tope_unidades_restantes"], r["tope_monto_restante"]) == (None, Decimal("6.25"))

    def test_a_usd_sale_day_campaign_converts_each_row_at_its_own_day(self, engine: Engine) -> None:
        w.tipo_cambio(engine, D(2026, 11, 1), 1000)
        w.tipo_cambio(engine, D(2026, 11, 3), 1200)
        campana = w.campana(engine, [w.grupo(engine, [ROUTERS])], monto_unit="1.00", moneda="USD", tc_modo="dia_venta")
        w.venta(engine, "ml", 2964, 1, D(2026, 11, 2))
        w.venta(engine, "ml", 2964, 2, D(2026, 11, 3))
        _recalcular(engine, campana)

        r = _resumenes(engine, campana)[campana]

        assert (r["monto"], r["monto_ars"], r["ars_estimado"]) == (Decimal("3.00"), Decimal("3400.00"), False)

    def test_a_usd_campaign_paid_later_is_an_estimate_at_the_latest_bna_until_its_rate_is_set(
        self, engine: Engine
    ) -> None:
        w.tipo_cambio(engine, D(2026, 11, 1), 1000)
        w.tipo_cambio(engine, D(2026, 11, 20), 1500)
        campana = w.campana(engine, [w.grupo(engine, [ROUTERS])], monto_unit="2.00", moneda="USD", tc_modo="al_cobro")
        w.venta(engine, "ml", 2964, 1, D(2026, 11, 2))
        _recalcular(engine, campana)

        assert (
            _resumenes(engine, campana)[campana]["monto_ars"],
            _resumenes(engine, campana)[campana]["ars_estimado"],
        ) == (
            Decimal("3000.00"),
            True,
        )

        w.execute(
            engine, "UPDATE sell_out_campanas SET tipo_cambio = 900, tc_definido_en = now() WHERE id = :c", c=campana
        )
        _recalcular(engine, campana)

        r = _resumenes(engine, campana)[campana]
        assert (r["monto_ars"], r["ars_estimado"]) == (Decimal("1800.00"), False)

    def test_a_usd_row_without_its_rate_leaves_the_ars_amount_unknown_never_partial(self, engine: Engine) -> None:
        campana = w.campana(
            engine, [w.grupo(engine, [ROUTERS])], monto_unit="1.00", moneda="USD", tc_modo="fijo", tipo_cambio="1000"
        )
        w.venta(engine, "ml", 2964, 1, D(2026, 11, 2))
        w.venta(engine, "ml", 2964, 1, D(2026, 11, 3))
        _recalcular(engine, campana)
        w.execute(engine, "UPDATE sell_out_consumos SET tc_venta = NULL WHERE fecha_venta = :d", d=D(2026, 11, 3))

        r = _resumenes(engine, campana)[campana]

        assert (r["monto"], r["monto_ars"]) == (Decimal("2.00"), None)

    def test_a_campaign_with_nothing_credited_has_zeros_and_its_whole_cap(self, engine: Engine) -> None:
        campana = w.campana(engine, [w.grupo(engine, [ROUTERS])], tope_unidades=5, tope_monto="100.00")

        r = _resumenes(engine, campana)[campana]

        assert (r["lineas"], r["unidades"], r["monto"], r["monto_ars"]) == (0, 0, Decimal("0"), Decimal("0"))
        assert (r["tope_unidades_restantes"], r["tope_monto_restante"], r["por_canal"]) == (5, Decimal("100.00"), [])


class TestPendientesBase:
    def test_counts_the_percentage_sales_the_allocator_skipped_for_their_unknown_base(self, engine: Engine) -> None:
        grupo = w.grupo(engine, [ROUTERS])
        porcentaje = w.campana(engine, [grupo], tipo="porcentaje", monto_unit=None, porcentaje="10")
        por_unidad = w.campana(engine, [grupo])
        anulada = w.campana(engine, [grupo], tipo="porcentaje", monto_unit=None, porcentaje="10", estado="anulada")
        for dia in (D(2026, 11, 2), D(2026, 11, 3)):
            ref = w.venta(engine, "ml", 2964, 1, dia)
            w.execute(engine, "UPDATE ml_sale_lines SET gross = 0, mcosto = 0 WHERE item_row_id = :r", r=ref)
        _fuera(engine, 2964, 1, D(2026, 11, 4), costo="1000.00")
        w.venta(engine, "ml", 2964, 1, D(2026, 12, 2))  # after the campaign
        result = _recalcular(engine, porcentaje, por_unidad)

        r = _resumenes(engine, porcentaje, por_unidad, anulada)

        assert result.pendientes_base == {porcentaje: 2}
        assert {cid: r[cid]["pendientes_base"] for cid in r} == {porcentaje: 2, por_unidad: 0, anulada: 0}


class TestRecalculo:
    def test_the_state_of_each_campaign_in_the_recompute_queue(self, engine: Engine) -> None:
        grupo = w.grupo(engine, [ROUTERS])
        al_dia, en_cola, fallida, detenida = (w.campana(engine, [grupo]) for _ in range(4))
        w.execute(
            engine, "INSERT INTO sell_out_dirty (campana_id) VALUES (:a), (:b), (:c)", a=en_cola, b=fallida, c=detenida
        )
        w.execute(
            engine,
            "UPDATE sell_out_dirty SET attempts = 1, last_error = 'ValueError: sin tasa' WHERE campana_id = :c",
            c=fallida,
        )
        w.execute(
            engine,
            "UPDATE sell_out_dirty SET attempts = :n, last_error = 'ValueError: sin IVA' WHERE campana_id = :c",
            n=queue.MAX_ATTEMPTS,
            c=detenida,
        )

        r = _resumenes(engine, al_dia, en_cola, fallida, detenida)

        estados = {cid: {k: v for k, v in r[cid]["recalculo"].items() if k != "encolada_en"} for cid in r}
        assert estados == {
            al_dia: {"estado": "al_dia", "intentos": 0, "error": None, "detenida": False},
            en_cola: {"estado": "en_cola", "intentos": 0, "error": None, "detenida": False},
            fallida: {"estado": "fallida", "intentos": 1, "error": "ValueError: sin tasa", "detenida": False},
            detenida: {
                "estado": "fallida",
                "intentos": queue.MAX_ATTEMPTS,
                "error": "ValueError: sin IVA",
                "detenida": True,
            },
        }
        assert r[al_dia]["recalculo"]["encolada_en"] is None
        assert r[en_cola]["recalculo"]["encolada_en"] is not None

    def test_a_campaign_the_allocator_holds_right_now_is_being_recomputed(self, engine: Engine) -> None:
        grupo = w.grupo(engine, [ROUTERS])
        libre, tomada = w.campana(engine, [grupo]), w.campana(engine, [grupo])
        w.execute(engine, "INSERT INTO sell_out_dirty (campana_id) VALUES (:a), (:b)", a=libre, b=tomada)
        with engine.connect() as otra:
            otra.execute(text("SELECT pg_advisory_lock(:ns, :id)"), {"ns": asignacion.LOCK_NAMESPACE, "id": tomada})
            try:
                r = _resumenes(engine, libre, tomada)
            finally:
                otra.execute(
                    text("SELECT pg_advisory_unlock(:ns, :id)"), {"ns": asignacion.LOCK_NAMESPACE, "id": tomada}
                )

        assert (r[libre]["recalculo"]["estado"], r[tomada]["recalculo"]["estado"]) == ("en_cola", "recalculando")


class TestConsultas:
    def test_the_number_of_queries_does_not_grow_with_the_campaigns(self, engine: Engine) -> None:
        grupo = w.grupo(engine, [ROUTERS])
        ids = [
            w.campana(engine, [grupo], tipo="porcentaje", monto_unit=None, porcentaje="5"),
            w.campana(engine, [grupo], moneda="USD", monto_unit="1.00", tc_modo="fijo", tipo_cambio="1000"),
            w.campana(
                engine, [grupo], tipo="porcentaje", monto_unit=None, porcentaje="2", base_porcentaje="precio_neto"
            ),
        ]
        w.venta(engine, "ml", 2964, 2, D(2026, 11, 2))
        _fuera(engine, 2964, 1, D(2026, 11, 3), costo="500.00")
        w.execute(engine, "INSERT INTO sell_out_dirty (campana_id) VALUES (:c)", c=ids[1])
        _recalcular(engine, *ids)

        def contar(*campanas: int) -> int:
            sentencias: List[str] = []

            def registrar(conn, cursor, statement, *args) -> None:
                sentencias.append(statement)

            event.listen(engine, "before_cursor_execute", registrar)
            try:
                _resumenes(engine, *campanas)
            finally:
                event.remove(engine, "before_cursor_execute", registrar)
            return len(sentencias)

        assert contar(ids[0]) == contar(*ids)


class TestDetalle:
    def test_lists_the_credited_lines_in_sale_order_one_page_at_a_time(self, engine: Engine) -> None:
        campana = w.campana(
            engine, [w.grupo(engine, [ROUTERS])], monto_unit="2.00", moneda="USD", tc_modo="fijo", tipo_cambio="1000"
        )
        tercera = w.venta(engine, "tn", 2964, 1, D(2026, 11, 5))
        primera = w.venta(engine, "ml", 2964, 2, D(2026, 11, 2))
        segunda = w.venta(engine, "fuera", 2964, 3, D(2026, 11, 3))
        _recalcular(engine, campana)

        pagina, total = _detalle(engine, campana, page=1, page_size=2)
        resto, _ = _detalle(engine, campana, page=2, page_size=2)

        assert total == 3
        assert [(x["canal"], x["venta_ref"]) for x in pagina + resto] == [
            ("ml", primera),
            ("fuera", segunda),
            ("tn", tercera),
        ]
        assert pagina[0] == {
            "id": pagina[0]["id"],
            "canal": "ml",
            "venta_ref": primera,
            "fecha_venta": D(2026, 11, 2),
            "item_id": 2964,
            "codigo": "C2964",
            "descripcion": "Producto",
            "unidades": 2,
            "monto": Decimal("4.00"),
            "tc_venta": Decimal("1000"),
            "monto_ars": Decimal("4000.00"),
        }

    def test_a_return_inside_the_campaign_shows_as_fewer_units_on_its_sale(self, engine: Engine) -> None:
        campana = w.campana(engine, [w.grupo(engine, [ROUTERS])])
        vendida = w.venta(engine, "fuera", 2964, 3, D(2026, 11, 2), cliente=55)
        w.venta(engine, "fuera", 2964, 1, D(2026, 11, 3), signo=-1, cliente=55)
        _recalcular(engine, campana)

        filas, total = _detalle(engine, campana)

        assert total == 1
        assert [(x["venta_ref"], x["unidades"], x["monto"], x["monto_ars"]) for x in filas] == [
            (vendida, 2, Decimal("20.00"), Decimal("20.00"))
        ]
