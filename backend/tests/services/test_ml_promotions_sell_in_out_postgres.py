"""Promo markups with today's sell in / sell out (promos-markup-sell-in-out, S1).

Owner: "las promos tienen que traer el % de ganancia con los sell in sell out aplicados como un % adicional".
Every promo of the panel read (`enriquecer_markup_por_promo(..., sell_in_out=True)`) and the manual / baseline
price read (`markup_para_precio_con_sell_in_out`) carry `markup_sell_in_out` next to `nuestro_markup`: the same
`limpio` of that promo's revenue, over the product's cost with sell in, plus its sell out credit (the Precios tab
rule: with sell in + sell out when there is sell out, else with sell in only). Null without sell in / sell out.
`nuestro_markup` does not move. Postgres only, like the sell in / sell out resolver it reads.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Iterator
from unittest.mock import patch

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from app.models.comision_config import ComisionListaGrupo, SubcategoriaGrupo
from app.models.comision_versionada import ComisionAdicionalCuota, ComisionBase, ComisionVersion
from app.models.pricing_constants import PricingConstants
from app.models.publicacion_ml import PublicacionML
from app.models.sell_in import SellInBonoItem
from app.services.ml_promotions_pricing import enriquecer_markup_por_promo, markup_para_precio_con_sell_in_out
from tests.services.sell._schema import throwaway_schema
from tests.services.sell_in import _world as si
from tests.services.sell_out import _world as so
from tests.services.test_productos_sell_in_out_postgres import _install as install_products

pytestmark = pytest.mark.postgres

ROUTER = 2964  # TP-LINK Routers, iva 21, cost 50000 ARS (`test_productos_sell_in_out_postgres._install`)
COSTO = 50000.0
MLA = "MLA2964"
HOY = date.today()  # the resolver prices what the next sale gets today
DESDE, HASTA = HOY - timedelta(days=5), HOY + timedelta(days=30)

PRICING_TABLES = [
    PublicacionML.__table__,
    PricingConstants.__table__,
    ComisionVersion.__table__,
    ComisionBase.__table__,
    ComisionAdicionalCuota.__table__,
    ComisionListaGrupo.__table__,
    SubcategoriaGrupo.__table__,
]
TABLES = list(dict.fromkeys([*si.TABLES, SellInBonoItem.__table__, *so.TABLES, *PRICING_TABLES]))
STUBS = [*si.STUBS, so.STUBS[-1]]


def _install(engine: Engine) -> None:
    install_products(engine)
    with sessionmaker(bind=engine)() as db:  # the ORM fills the constants' defaults, as production rows have
        db.add(
            PricingConstants(
                monto_tier1=15000,
                monto_tier2=24000,
                monto_tier3=33000,
                comision_tier1=1095,
                comision_tier2=2190,
                comision_tier3=2628,
                varios_porcentaje=6.5,
                grupo_comision_default=1,
                markup_adicional_cuotas=4.0,
                comision_tienda_nube=1.0,
                fecha_desde=date(2000, 1, 1),
            )
        )
        version = ComisionVersion(nombre="t", fecha_desde=date(2000, 1, 1), activo=True)
        db.add(version)
        db.flush()
        db.add(ComisionBase(version_id=version.id, grupo_id=5, comision_base=13.0))
        db.add(SubcategoriaGrupo(subcat_id=11, grupo_id=5))
        db.add(PublicacionML(mla=MLA, item_id=ROUTER, pricelist_id=4, activo=True))
        db.commit()


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with throwaway_schema("promos_sio", TABLES, STUBS, after=_install) as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    yield
    si.clean(engine)
    so.clean(engine)


def _promos() -> list[dict]:
    """A seller-funded promo and an ML co-funded one (its revenue adds ML's share)."""
    return [
        {
            "mla": MLA,
            "promotion_id": "P-SELLER",
            "promotion_type": "SELLER_CAMPAIGN",
            "status": "started",
            "price": 60500,
            "original_price": 70000,
            "payload": {},
        },
        {
            "mla": MLA,
            "promotion_id": "P-SMART",
            "promotion_type": "SMART",
            "status": "candidate",
            "price": 55000,
            "original_price": 70000,
            "payload": {"meli_percentage": 5},
        },
    ]


def _enrich(engine: Engine, *, sell_in_out: bool = True) -> list[dict]:
    with sessionmaker(bind=engine, autoflush=False)() as db:
        with patch("app.services.ml_promotions_pricing.resolver_costo_envio", return_value=0.0):
            return enriquecer_markup_por_promo(db, MLA, _promos(), sell_in_out=sell_in_out)


def _limpio(markup_pct: float) -> float:
    """The promo's net, back from its plain markup over the plain cost (`calcular_markup`)."""
    return COSTO * (1 + markup_pct / 100)


def _lote_y_campana(engine: Engine, **campana) -> None:
    si.compra(engine, [(ROUTER, 2, "2000.00")], HOY - timedelta(days=30))  # 1000 ARS of sell in per unit
    gid = so.grupo(engine, [{"item_id": ROUTER}])
    so.campana(engine, [gid], DESDE, HASTA, **({"monto_unit": "500.00"} | campana))


class TestPromosDelPanel:
    def test_with_sell_in_and_sell_out_each_promo_gets_its_markup_with_both(self, engine) -> None:
        _lote_y_campana(engine)

        promos = _enrich(engine)

        for promo in promos:
            esperado = round(((_limpio(promo["nuestro_markup"]) + 500) / (COSTO - 1000) - 1) * 100, 2)
            assert promo["markup_sell_in_out"] == pytest.approx(esperado, abs=0.01)

    def test_with_sell_in_only_it_is_the_markup_over_the_cost_with_sell_in(self, engine) -> None:
        si.compra(engine, [(ROUTER, 2, "2000.00")], HOY - timedelta(days=30))

        promos = _enrich(engine)

        for promo in promos:
            esperado = round((_limpio(promo["nuestro_markup"]) / (COSTO - 1000) - 1) * 100, 2)
            assert promo["markup_sell_in_out"] == pytest.approx(esperado, abs=0.01)

    def test_a_net_price_percentage_sell_out_is_on_the_promo_consumer_price(self, engine) -> None:
        gid = so.grupo(engine, [{"item_id": ROUTER}])
        so.campana(
            engine,
            [gid],
            DESDE,
            HASTA,
            tipo="porcentaje",
            monto_unit=None,
            porcentaje="10",
            base_porcentaje="precio_neto",
        )

        seller, smart = _enrich(engine)

        credito_seller = 60500 / 1.21 * 0.10  # 10 % of the promo price without VAT
        credito_smart = 55000 / 1.21 * 0.10
        assert seller["markup_sell_in_out"] == pytest.approx(
            round(((_limpio(seller["nuestro_markup"]) + credito_seller) / COSTO - 1) * 100, 2), abs=0.01
        )
        assert smart["markup_sell_in_out"] == pytest.approx(
            round(((_limpio(smart["nuestro_markup"]) + credito_smart) / COSTO - 1) * 100, 2), abs=0.01
        )

    def test_without_sell_in_or_sell_out_it_is_null(self, engine) -> None:
        promos = _enrich(engine)

        assert [p["markup_sell_in_out"] for p in promos] == [None, None]
        assert all(p["nuestro_markup"] is not None for p in promos)

    def test_nuestro_markup_does_not_move(self, engine) -> None:
        sin = [p["nuestro_markup"] for p in _enrich(engine)]
        _lote_y_campana(engine)

        con = _enrich(engine)

        assert [p["nuestro_markup"] for p in con] == sin
        assert all(p["markup_sell_in_out"] is not None for p in con)

    def test_callers_that_do_not_ask_for_it_get_no_field(self, engine) -> None:
        _lote_y_campana(engine)

        promos = _enrich(engine, sell_in_out=False)

        assert all("markup_sell_in_out" not in p for p in promos)


class TestPrecioManualYVigente:
    def test_a_price_gets_its_markup_with_sell_in_and_sell_out(self, engine) -> None:
        _lote_y_campana(engine)

        with sessionmaker(bind=engine, autoflush=False)() as db:
            with patch("app.services.ml_promotions_pricing.resolver_costo_envio", return_value=0.0):
                nuestro, con_sio = markup_para_precio_con_sell_in_out(db, MLA, 60500.0)

        assert nuestro is not None
        assert con_sio == pytest.approx(round(((_limpio(nuestro) + 500) / (COSTO - 1000) - 1) * 100, 2), abs=0.01)

    def test_without_sell_in_or_sell_out_only_the_markup_comes(self, engine) -> None:
        with sessionmaker(bind=engine, autoflush=False)() as db:
            with patch("app.services.ml_promotions_pricing.resolver_costo_envio", return_value=0.0):
                nuestro, con_sio = markup_para_precio_con_sell_in_out(db, MLA, 60500.0)

        assert nuestro is not None
        assert con_sio is None

    def test_an_unknown_publication_gives_neither(self, engine) -> None:
        with sessionmaker(bind=engine, autoflush=False)() as db:
            assert markup_para_precio_con_sell_in_out(db, "MLA0", 60500.0) == (None, None)
