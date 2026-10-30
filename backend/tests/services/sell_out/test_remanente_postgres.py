"""What the `monto_total` campaigns put in the Métricas ML totals with no product row (T26b2, S34/S35/S37).

Owner: "Está bien que sume al total". A campaign's "Asignado sin ventas" plus its "Sin asignar" (both as the panel
shows them: a share net of its own product's VAT when loaded with VAT, the remainder as loaded) counts ONCE, in
ARS, on the campaign's `fecha_hasta`, when the period includes it (`resumen.remanentes`). Postgres only; `_world`.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Iterator, List, Optional

import pytest
from sqlalchemy import Engine, event, literal, select, union_all
from sqlalchemy.orm import sessionmaker

from app.services.sell_out import asignacion, resumen
from tests.services.sell_out import _world as w

pytestmark = pytest.mark.postgres

D = date
TP_LINK = {"marca": "TP-LINK"}
NOV = (D(2026, 11, 1), D(2026, 11, 30))


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with w.world("sell_out_remanente") as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    yield
    w.clean(engine)


def _items(*ids: int):
    """A selectable of product ids, like the board's filtered products."""
    if not ids:
        return select(literal(0)).where(literal(False))
    return union_all(*(select(literal(i)) for i in ids))


def _remanentes(
    engine: Engine, desde: date, hasta: date, items: Optional[tuple] = None, visibles: Optional[tuple] = None
) -> resumen.Remanente:
    with sessionmaker(bind=engine)() as db:
        return resumen.remanentes(
            db,
            desde,
            hasta,
            None if items is None else _items(*items),
            visibles=None if visibles is None else _items(*visibles),
        )


def _recalcular(engine: Engine, *ids: int) -> None:
    with sessionmaker(bind=engine)() as db:
        asignacion.recalcular(db, ids)
        db.commit()


def _campana_con_reparto(engine: Engine, total: str = "1000.00", **values) -> int:
    """60 % to 2964 (which sells in the dates) and 100 fixed to 2270 (which does not): 300 unassigned."""
    campana = w.monto_total(engine, [w.grupo(engine, [TP_LINK])], total, **values)
    w.reparto(engine, campana, 2964, porcentaje="60")
    w.reparto(engine, campana, 2270, monto="100.00")
    w.venta(engine, "ml", 2964, 1, D(2026, 11, 2))
    _recalcular(engine, campana)
    return campana


class TestRemanentes:
    def test_the_shares_without_sales_and_the_unassigned_count_once_on_the_end_date(self, engine: Engine) -> None:
        _campana_con_reparto(engine)

        assert _remanentes(engine, *NOV) == resumen.Remanente(Decimal("400.00"), 0, 0)
        # The end date inside a one-day period counts; a period that ends before it does not.
        assert _remanentes(engine, D(2026, 11, 30), D(2026, 11, 30)).monto_ars == Decimal("400.00")
        assert _remanentes(engine, D(2026, 11, 1), D(2026, 11, 29)) == resumen.Remanente(Decimal("0"), 0, 0)

    def test_loaded_with_vat_the_share_is_net_of_its_product_vat_and_the_remainder_stays_as_loaded(
        self, engine: Engine
    ) -> None:
        # S37 (corrected): 2270's 110.50 is applied to that product, net of its 10.5 % (100.00); the 889.50 nobody
        # was given keeps its VAT.
        campana = w.monto_total(engine, [w.grupo(engine, [TP_LINK])], "1000.00", monto_incluye_iva=True)
        w.reparto(engine, campana, 2270, monto="110.50")

        assert _remanentes(engine, *NOV).monto_ars == Decimal("989.50")

    def test_a_negative_total_lowers_the_total(self, engine: Engine) -> None:
        w.monto_total(engine, [w.grupo(engine, [TP_LINK])], "-1000.00")

        assert _remanentes(engine, *NOV).monto_ars == Decimal("-1000.00")

    def test_only_active_monto_total_campaigns(self, engine: Engine) -> None:
        w.monto_total(engine, [w.grupo(engine, [TP_LINK])], "1000.00", estado="anulada")
        w.campana(engine, [w.grupo(engine, [TP_LINK])])

        assert _remanentes(engine, *NOV) == resumen.Remanente(Decimal("0"), 0, 0)

    def test_a_usd_campaign_converts_at_its_rate_on_the_end_date(self, engine: Engine) -> None:
        grupo = w.grupo(engine, [TP_LINK])
        w.monto_total(engine, [grupo], "10.00", moneda="USD", tc_modo="fijo", tipo_cambio="1000")
        w.monto_total(engine, [grupo], "1.00", moneda="USD", tc_modo="dia_venta")
        w.tipo_cambio(engine, D(2026, 11, 29), 1100)
        w.tipo_cambio(engine, D(2026, 12, 5), 9999)  # after the end date: not its rate

        assert _remanentes(engine, *NOV) == resumen.Remanente(Decimal("11100.00"), 0, 0)

    def test_al_cobro_without_its_rate_is_an_estimate_and_no_rate_is_pending_never_zero(self, engine: Engine) -> None:
        grupo = w.grupo(engine, [TP_LINK])
        w.monto_total(engine, [grupo], "2.00", moneda="USD", tc_modo="al_cobro")
        assert _remanentes(engine, *NOV) == resumen.Remanente(Decimal("0"), 1, 0)

        w.tipo_cambio(engine, D(2026, 12, 5), 1200)  # the latest BNA
        assert _remanentes(engine, *NOV) == resumen.Remanente(Decimal("2400.00"), 0, 1)

    def test_a_campaign_with_nothing_left_counts_no_pending_nor_estimate(self, engine: Engine) -> None:
        # Its whole total went to a product with a written row: nothing to add, so no rate is needed either.
        grupo = w.grupo(engine, [TP_LINK])
        for tc_modo in ("dia_venta", "al_cobro"):
            campana = w.monto_total(engine, [grupo], "10.00", moneda="USD", tc_modo=tc_modo)
            w.reparto(engine, campana, 2964, porcentaje="100")
            w.execute(
                engine,
                "INSERT INTO sell_out_consumos (campana_id, canal, venta_ref, item_id, fecha_venta, unidades, monto) "
                "VALUES (:c, 'ml', :r, 2964, '2026-11-02', 1, 10)",
                c=campana,
                r=campana,
            )
        assert _remanentes(engine, *NOV) == resumen.Remanente(Decimal("0"), 0, 0)
        w.tipo_cambio(engine, D(2026, 12, 5), 1200)  # a latest BNA: the al_cobro one would be an estimate
        assert _remanentes(engine, *NOV) == resumen.Remanente(Decimal("0"), 0, 0)
        assert not resumen.Remanente(Decimal("0"), 0, 0).suma
        assert resumen.Remanente(Decimal("0"), 1, 0).suma and resumen.Remanente(Decimal("-1"), 0, 0).suma

    def test_a_scoped_viewer_counts_its_products_shares_and_the_unassigned_only_with_the_whole_reach(
        self, engine: Engine
    ) -> None:
        # 2964 sells (no remainder), 2270 has 100 without sales, 300 unassigned; the reach is 2964 and 2270.
        _campana_con_reparto(engine)

        assert _remanentes(engine, *NOV, visibles=(2270,)).monto_ars == Decimal("100.00")
        assert _remanentes(engine, *NOV, visibles=(2964,)) == resumen.Remanente(Decimal("0"), 0, 0)
        assert _remanentes(engine, *NOV, visibles=(2964, 2270)).monto_ars == Decimal("400.00")

    def test_with_products_given_only_a_campaign_reaching_one_of_them_counts(self, engine: Engine) -> None:
        _campana_con_reparto(engine)

        assert _remanentes(engine, *NOV, items=(2964,)).monto_ars == Decimal("400.00")
        assert _remanentes(engine, *NOV, items=(950,)).monto_ars == Decimal("0")
        assert _remanentes(engine, *NOV, items=()).monto_ars == Decimal("0")

    def test_a_split_that_cannot_stand_counts_nothing(self, engine: Engine) -> None:
        # A product without VAT on a campaign loaded with VAT: the allocator fails it, so nothing is known.
        w.execute(engine, "UPDATE productos_erp SET iva = NULL WHERE item_id = 2270")
        campana = w.monto_total(engine, [w.grupo(engine, [TP_LINK])], "1000.00", monto_incluye_iva=True)
        w.reparto(engine, campana, 2270, monto="100.00")
        try:
            assert _remanentes(engine, *NOV) == resumen.Remanente(Decimal("0"), 0, 0)
        finally:
            w.execute(engine, "UPDATE productos_erp SET iva = 10.5 WHERE item_id = 2270")

    def test_the_statement_count_does_not_grow_with_the_campaigns(self, engine: Engine) -> None:
        def contar() -> int:
            statements: List[str] = []

            def registrar(conn, cursor, statement, *args) -> None:
                statements.append(statement)

            event.listen(engine, "before_cursor_execute", registrar)
            try:
                _remanentes(engine, *NOV, items=(2964,))
            finally:
                event.remove(engine, "before_cursor_execute", registrar)
            return len(statements)

        assert contar() == 1  # none in the period: the lookup only
        grupo = w.grupo(engine, [TP_LINK])
        w.monto_total(engine, [grupo], "10.00", moneda="USD", tc_modo="dia_venta", monto_incluye_iva=True)
        uno = contar()
        for _ in range(4):
            c = w.monto_total(engine, [grupo], "10.00", moneda="USD", tc_modo="dia_venta", monto_incluye_iva=True)
            w.reparto(engine, c, 2964, porcentaje="10")
        assert contar() == uno <= 6
