"""The ML shipping cost depends on the price it is evaluated at (ML price brackets).

Real case (MLA1173065146, 2026-11-12): list price 65472, sale price 41999. ML charges the seller 6790 at
41999 and 7290 from 50000 up; pricing showed 7290. The rows below are what ml-webhook stores for it,
derived from the ML responses captured that day (shipping_options/free with item_id + item_price):
list_cost at the sale price, and the cost of every bracket.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.envio_tramos import CostoEnvioTramos, costo_envio_para
from app.services.pricing_calculator import calcular_limpio, calcular_markup, precio_por_markup_goalseek

CONSTANTES = {"monto_tier3": 33000}

# ml_seller_shipping_costs rows (list_cost, cost_by_bracket) as ml-webhook stores them
MLA1173065146 = (
    6790.0,
    [
        {"min_price": 0, "list_cost": 0},
        {"min_price": 33000, "list_cost": 6790},
        {"min_price": 50000, "list_cost": 7290},
    ],
)
# MLA3489206948 (743 g billable): 7790 / 8290, list price 84788 with no promo
MLA3489206948 = (
    8290.0,
    [
        {"min_price": 0, "list_cost": 0},
        {"min_price": 33000, "list_cost": 7790},
        {"min_price": 50000, "list_cost": 8290},
    ],
)


def _row(mla: str, row: tuple) -> MagicMock:
    r = MagicMock()
    r.mla_id, r.list_cost, r.tramos = mla, row[0], row[1]
    return r


def _engine_returning(rows: list[MagicMock]) -> MagicMock:
    engine = MagicMock()
    engine.connect.return_value.__enter__.return_value.execute.return_value.fetchall.return_value = rows
    return engine


class TestRealCase:
    def test_limpio_uses_6790_at_the_41999_promo_price_not_7290(self) -> None:
        costo = CostoEnvioTramos.desde_fila(*MLA1173065146)

        limpio = calcular_limpio(41999, 21, costo, 0, constantes=CONSTANTES)

        assert limpio == pytest.approx(41999 / 1.21 - 6790 / 1.21)

    def test_limpio_uses_7290_at_the_65472_list_price(self) -> None:
        costo = CostoEnvioTramos.desde_fila(*MLA1173065146)

        assert calcular_limpio(65472, 21, costo, 0, constantes=CONSTANTES) == pytest.approx((65472 - 7290) / 1.21)

    def test_displayed_cost_is_the_list_cost_at_the_sale_price(self) -> None:
        costo = CostoEnvioTramos.desde_fila(*MLA1173065146)

        assert float(costo) == 6790.0
        assert costo_envio_para(costo, 50000) == 7290.0
        assert costo_envio_para(costo, 49999) == 6790.0

    def test_query_reads_the_brackets_and_keeps_legacy_rows_flat(self) -> None:
        from app.services.envio_real_service import _query_list_cost_by_mla

        legacy = _row("MLA1", (9000.0, None))
        with patch(
            "app.services.envio_real_service.get_mlwebhook_engine",
            return_value=_engine_returning([_row("MLA1173065146", MLA1173065146), legacy]),
        ):
            costs = _query_list_cost_by_mla(["MLA1173065146", "MLA1"])

        assert isinstance(costs["MLA1173065146"], CostoEnvioTramos)
        assert costs["MLA1173065146"].para(41999) == 6790.0
        assert type(costs["MLA1"]) is float and costs["MLA1"] == 9000.0

    def test_query_asks_for_the_brackets_without_requiring_the_column(self) -> None:
        """Before the ml-webhook migration runs the column does not exist: read it through to_jsonb(row)."""
        from app.services.envio_real_service import _query_list_cost_by_mla

        engine = _engine_returning([])
        with patch("app.services.envio_real_service.get_mlwebhook_engine", return_value=engine):
            _query_list_cost_by_mla(["MLA1"])

        sql = str(engine.connect.return_value.__enter__.return_value.execute.call_args[0][0])
        assert "to_jsonb(s) -> 'cost_by_bracket'" in sql


class TestPriceFromMarkup:
    def test_goalseek_prices_with_the_bracket_of_each_candidate_price(self) -> None:
        """A target markup that lands at ~42k must subtract 6790 (that bracket), not 7290."""
        costo = CostoEnvioTramos.desde_fila(*MLA1173065146)
        db = MagicMock()
        with (
            patch("app.services.pricing_calculator.obtener_constantes_pricing", return_value=CONSTANTES),
            patch("app.services.pricing_calculator.calcular_comision_ml_total", return_value={"comision_total": 0.0}),
        ):
            precio = precio_por_markup_goalseek(25000, 20, 21, 0, 0, costo, db=db)
            precio_6790 = precio_por_markup_goalseek(25000, 20, 21, 0, 0, 6790.0, db=db)
            precio_7290 = precio_por_markup_goalseek(25000, 20, 21, 0, 0, 7290.0, db=db)

        assert 33000 <= precio < 50000
        assert precio == precio_6790 != precio_7290
        markup = calcular_markup(calcular_limpio(precio, 21, costo, 0, constantes=CONSTANTES), 25000)
        assert markup == pytest.approx(0.20, abs=0.002)


class TestProductAggregationPerBracket:
    def _resolve(self, modo: str, mla: str | None = None) -> float:
        from app.services.envio_real_service import resolver_costos_envio_batch

        pubs = []
        for name in ("MLA1173065146", "MLA3489206948"):
            p = MagicMock()
            p.mla, p.activo, p.item_id = name, True, 22
            pubs.append(p)
        costs = {
            "MLA1173065146": CostoEnvioTramos.desde_fila(*MLA1173065146),
            "MLA3489206948": CostoEnvioTramos.desde_fila(*MLA3489206948),
        }
        with (
            patch("app.services.envio_real_service._fetch_list_cost_by_mla", return_value=costs),
            patch("app.services.envio_real_service.elecciones_por_item", return_value={22: (modo, mla)}),
        ):
            return resolver_costos_envio_batch(MagicMock(), [22], pubs_by_item={22: pubs})[22]

    def test_max_is_taken_per_bracket(self) -> None:
        costo = self._resolve("max")

        assert float(costo) == 8290.0  # MAX of the list_cost at each one's sale price, as before
        assert costo_envio_para(costo, 41999) == 7790.0
        assert costo_envio_para(costo, 65472) == 8290.0

    def test_promedio_is_taken_per_bracket(self) -> None:
        costo = self._resolve("promedio")

        assert float(costo) == pytest.approx((6790 + 8290) / 2)
        assert costo_envio_para(costo, 41999) == pytest.approx((6790 + 7790) / 2)
        assert costo_envio_para(costo, 65472) == pytest.approx((7290 + 8290) / 2)

    def test_chosen_mla_keeps_its_own_brackets(self) -> None:
        costo = self._resolve("mla", "MLA1173065146")

        assert float(costo) == 6790.0
        assert costo_envio_para(costo, 65472) == 7290.0


class TestFlatCostsUnchanged:
    def test_plain_float_cost_is_used_as_is_at_any_price(self) -> None:
        assert costo_envio_para(7290.0, 41999) == 7290.0
        assert calcular_limpio(41999, 21, 7290.0, 0, constantes=CONSTANTES) == pytest.approx((41999 - 7290) / 1.21)

    def test_below_the_free_shipping_threshold_nothing_is_subtracted(self) -> None:
        costo = CostoEnvioTramos.desde_fila(*MLA1173065146)

        assert calcular_limpio(30000, 21, costo, 0, constantes=CONSTANTES) == pytest.approx(30000 / 1.21)


class TestPromoBelowTheFreeShippingFloor:
    """List price >= 33000 with a promo under it: ml-webhook stores list_cost 0 (ML charges nothing at the sale
    price) but every bracket's cost. Pricing must keep the row: priced at >= 33000 it costs that bracket."""

    ROW = (
        0.0,
        [
            {"min_price": 0, "list_cost": 0},
            {"min_price": 33000, "list_cost": 6790},
            {"min_price": 50000, "list_cost": 7290},
        ],
    )

    def test_query_keeps_a_zero_list_cost_row_with_priced_brackets(self) -> None:
        from app.services.envio_real_service import _query_list_cost_by_mla

        zero_flat = _row("MLA_FLAT_ZERO", (0.0, None))
        with patch(
            "app.services.envio_real_service.get_mlwebhook_engine",
            return_value=_engine_returning([_row("MLA_PROMO", self.ROW), zero_flat]),
        ):
            costs = _query_list_cost_by_mla(["MLA_PROMO", "MLA_FLAT_ZERO"])

        assert list(costs) == ["MLA_PROMO"]  # a 0 without brackets is still "no cost", as before
        assert float(costs["MLA_PROMO"]) == 0.0  # displayed at its 31500 sale price: ML charges nothing
        assert costo_envio_para(costs["MLA_PROMO"], 35000) == 6790.0
        assert calcular_limpio(35000, 21, costs["MLA_PROMO"], 0, constantes=CONSTANTES) == pytest.approx(
            (35000 - 6790) / 1.21
        )

    def test_it_still_counts_in_the_product_max_per_bracket(self) -> None:
        costs = {"A": CostoEnvioTramos.desde_fila(*self.ROW), "B": CostoEnvioTramos.desde_fila(*MLA3489206948)}
        from app.services.envio_real_service import costo_envio_maximo

        costo = costo_envio_maximo(costs, None)

        assert costo_envio_para(costo, 41999) == 7790.0
        assert costo_envio_para(costo, 65472) == 8290.0


class TestReviewGaps:
    def test_ponderado_is_taken_per_bracket_with_the_same_weights(self) -> None:
        from app.services.envio_real_service import costo_ponderado

        costs = {"A": CostoEnvioTramos.desde_fila(*MLA1173065146), "B": CostoEnvioTramos.desde_fila(*MLA3489206948)}
        costo = costo_ponderado(costs, {"A": 3, "B": 1})

        assert float(costo) == pytest.approx((6790 * 3 + 8290) / 4)
        assert costo_envio_para(costo, 41999) == pytest.approx((6790 * 3 + 7790) / 4)
        assert costo_envio_para(costo, 65472) == pytest.approx((7290 * 3 + 8290) / 4)

    def test_a_flat_cost_stays_constant_across_the_brackets_of_the_others(self) -> None:
        from app.services.envio_real_service import costo_envio_maximo

        costo = costo_envio_maximo({"A": CostoEnvioTramos.desde_fila(*MLA1173065146), "LEGACY": 7000.0}, None)

        assert costo_envio_para(costo, 41999) == 7000.0  # max(6790, 7000)
        assert costo_envio_para(costo, 65472) == 7290.0  # max(7290, 7000)


class TestDisplayedCostAtTheCurrentSalePrice:
    """ml-webhook's list_cost is quoted at the sale price it saw on its last quote; a promo that starts or ends
    without an items webhook leaves it stale. Pricing's own `ml_item_sale_prices` mirror is the current price:
    with brackets, the displayed cost is the bracket of THAT price."""

    def _sale_price(self, db, mla: str, amount: float) -> None:
        from app.models.ml_publications import MlItemSalePrice

        db.add(MlItemSalePrice(item_id=mla, amount=amount, regular_amount=65472, currency_id="ARS"))
        db.flush()

    def test_promo_ended_without_webhook_shows_the_list_price_bracket(self, db) -> None:
        from app.services.envio_real_service import costos_envio_por_mla

        self._sale_price(db, "MLA1173065146", 65472)  # the promo ended: sells at list price again
        engine = _engine_returning([_row("MLA1173065146", MLA1173065146)])  # stored at the 41999 promo: 6790
        with patch("app.services.envio_real_service.get_mlwebhook_engine", return_value=engine):
            costs = costos_envio_por_mla(["MLA1173065146"], db=db)

        assert float(costs["MLA1173065146"]) == 7290.0
        assert costs["MLA1173065146"].para(41999) == 6790.0  # brackets untouched

    def test_promo_started_under_the_floor_shows_zero(self, db) -> None:
        from app.services.envio_real_service import costos_envio_por_mla

        self._sale_price(db, "MLA1173065146", 31500)
        engine = _engine_returning([_row("MLA1173065146", MLA1173065146)])
        with patch("app.services.envio_real_service.get_mlwebhook_engine", return_value=engine):
            costs = costos_envio_por_mla(["MLA1173065146"], db=db)

        assert float(costs["MLA1173065146"]) == 0.0

    def test_without_a_mirrored_price_or_brackets_the_stored_cost_stands(self, db) -> None:
        from app.services.envio_real_service import costos_envio_por_mla

        engine = _engine_returning([_row("MLA1173065146", MLA1173065146), _row("MLA1", (9000.0, None))])
        self._sale_price(db, "MLA1", 99999)
        with patch("app.services.envio_real_service.get_mlwebhook_engine", return_value=engine):
            costs = costos_envio_por_mla(["MLA1173065146", "MLA1"], db=db)

        assert float(costs["MLA1173065146"]) == 6790.0  # no mirror row: ml-webhook's value
        assert type(costs["MLA1"]) is float and costs["MLA1"] == 9000.0  # flat: as before

    def test_the_product_resolvers_display_the_current_price_too(self, db) -> None:
        from app.services.envio_real_service import resolver_costos_envio_batch

        self._sale_price(db, "MLA1173065146", 65472)
        pub = MagicMock()
        pub.mla, pub.activo, pub.item_id = "MLA1173065146", True, 22
        engine = _engine_returning([_row("MLA1173065146", MLA1173065146)])
        with (
            patch("app.services.envio_real_service.get_mlwebhook_engine", return_value=engine),
            patch("app.services.envio_real_service.elecciones_por_item", return_value={}),
        ):
            costo = resolver_costos_envio_batch(db, [22], pubs_by_item={22: [pub]})[22]

        assert float(costo) == 7290.0


class TestGoalseekAtThe50000Step:
    """Shipping rises 500 at 50000 (6790 -> 7290 for MLA1173065146), so limpio drops ~413 there and only climbs back
    to its 49999 level at 50499. Limpio targets in that band are met by TWO prices (one under 50000, one over);
    the bisection settles on the higher one, within its usual rounding tolerance. Measured 2026-11-12."""

    BASE = 30000.0

    def _seek(self, target_limpio: float) -> tuple[float, float]:
        costo = CostoEnvioTramos.desde_fila(*MLA1173065146)
        markup = (target_limpio - self.BASE) / self.BASE * 100
        with (
            patch("app.services.pricing_calculator.obtener_constantes_pricing", return_value=CONSTANTES),
            patch("app.services.pricing_calculator.calcular_comision_ml_total", return_value={"comision_total": 0.0}),
        ):
            precio = precio_por_markup_goalseek(self.BASE, markup, 21, 0, 0, costo, db=MagicMock())
        obtenido = calcular_markup(calcular_limpio(precio, 21, costo, 0, constantes=CONSTANTES), self.BASE) * 100
        return precio, obtenido - markup

    def test_the_step_is_413_and_recovers_at_50499(self) -> None:
        costo = CostoEnvioTramos.desde_fila(*MLA1173065146)
        limpio = lambda p: calcular_limpio(p, 21, costo, 0, constantes=CONSTANTES)  # noqa: E731

        assert limpio(49999) - limpio(50000) == pytest.approx(412.4, abs=0.1)
        assert limpio(50499) == pytest.approx(limpio(49999))

    def test_a_target_inside_the_band_settles_above_50000_within_tolerance(self) -> None:
        precio, diff = self._seek(35400)  # also met at 49624, under the step

        assert 50000 <= precio < 50499
        assert abs(diff) < 0.1  # percentage points, the same rounding slack as anywhere else
        costo = CostoEnvioTramos.desde_fila(*MLA1173065146)
        assert calcular_limpio(49624, 21, costo, 0, constantes=CONSTANTES) == pytest.approx(35400, abs=1)

    def test_a_target_under_the_band_stays_under_50000(self) -> None:
        precio, diff = self._seek(35290)

        assert 33000 <= precio < 50000
        assert abs(diff) < 0.1
