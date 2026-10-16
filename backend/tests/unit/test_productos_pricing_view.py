"""Pure rules of the shared rebate / best-offer computation
(`app.services.productos_pricing_view`), the one the Productos listing, the
tienda listing and the product detail all run."""

from __future__ import annotations

import logging
from datetime import date
from types import SimpleNamespace

import pytest

from app.services.pricing_context import PricingContext
from app.services.productos_pricing_view import calcular_mejor_oferta, calcular_rebate, cargar_ofertas_vigentes

CTX = PricingContext(
    hoy=date(2026, 1, 1),
    tipo_cambio_usd=1000.0,
    constantes={
        "monto_tier1": 15000,
        "monto_tier2": 24000,
        "monto_tier3": 33000,
        "tier1": 1095,
        "tier2": 2190,
        "tier3": 2628,
        "varios": 6.5,
    },
    subcat_to_grupo={},
    active_version_id=1,
    comision_base={1: 12.5},
    comision_adicional={},
    envio_promedio_by_grupo={},
)
PRODUCTO = SimpleNamespace(item_id=1, costo=10000.0, moneda_costo="ARS", iva=21.0, envio=0.0)


def _sin_envio(item_id, envio, grupo_id, precio):
    return 0.0


def _pricing(porcentaje):
    return SimpleNamespace(precio_lista_ml=20000.0, participa_rebate=True, porcentaje_rebate=porcentaje)


class TestRebatePercentageBounds:
    """R3-006: 100% divides by zero and more than 100% grosses the price up to a
    negative one; neither is a rebate."""

    @pytest.mark.parametrize("porcentaje", [100.0, 100.5, 150.0, -0.01, -5.0])
    def test_out_of_range_gives_no_rebate_figures_and_is_logged(self, porcentaje, caplog) -> None:
        with caplog.at_level(logging.WARNING, logger="app.services.productos_pricing_view"):
            rebate = calcular_rebate(CTX, PRODUCTO, _pricing(porcentaje), 1, _sin_envio)

        assert (rebate.precio, rebate.markup, rebate.limpio) == (None, None, None)
        assert any("porcentaje_rebate" in record.getMessage() for record in caplog.records)

    @pytest.mark.parametrize(("porcentaje", "precio"), [(0.0, 20000.0), (99.0, 2000000.0), (3.8, 20000.0 / 0.962)])
    def test_in_range_is_priced(self, porcentaje, precio) -> None:
        rebate = calcular_rebate(CTX, PRODUCTO, _pricing(porcentaje), 1, _sin_envio)

        assert rebate.precio == pytest.approx(precio)
        assert rebate.markup is not None


class TestDeterministicWinner:
    """R3-004: the lowest publication id with a current offer wins, and per MLA
    the lowest offer id -- whatever order the rows come back in."""

    @staticmethod
    def _oferta(oferta_id, mla, precio_final):
        return SimpleNamespace(
            id=oferta_id,
            mla=mla,
            precio_final=precio_final,
            pvp_seller=precio_final + 1000,
            aporte_meli_porcentaje=None,
            fecha_hasta=date(2099, 12, 31),
        )

    def test_publications_in_any_order(self) -> None:
        pubs = [SimpleNamespace(id=7, mla="B", pricelist_id=4), SimpleNamespace(id=3, mla="A", pricelist_id=4)]
        ofertas = {"A": self._oferta(1, "A", 15000.0), "B": self._oferta(2, "B", 16000.0)}

        oferta = calcular_mejor_oferta(CTX, PRODUCTO, pubs, ofertas, 1, _sin_envio)

        assert oferta.precio == 15000.0

    def test_two_current_offers_on_one_mla_in_any_order(self) -> None:
        pub = SimpleNamespace(id=1, item_id=1, mla="A", pricelist_id=4)
        rows = {"pubs": [pub], "ofertas": [self._oferta(20, "A", 18000.0), self._oferta(10, "A", 17000.0)]}

        class _Query:
            def __init__(self, key):
                self.key = key

            def filter(self, *args):
                return self

            def order_by(self, *args):
                return self

            def all(self):
                return rows[self.key]

        class _Db:
            def query(self, model):
                return _Query("pubs" if model.__name__ == "PublicacionML" else "ofertas")

        _, ofertas_by_mla, _ = cargar_ofertas_vigentes(_Db(), [1], date(2026, 1, 1))

        assert ofertas_by_mla["A"].id == 10
