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
