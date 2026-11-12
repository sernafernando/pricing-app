"""Promo markups with today's sell in / sell out (promos-markup-sell-in-out, S1).

Owner: "las promos tienen que traer el % de ganancia con los sell in sell out aplicados como un % adicional".
Every promo of the panel read (`enriquecer_markup_por_promo(..., sell_in_out=True)`) and the manual / baseline
price read (`markup_para_precio_con_sell_in_out`) carry `markup_sell_in_out` next to `nuestro_markup`: the same
`limpio` of that promo's revenue, over the product's cost with sell in, plus its sell out credit (the Precios tab
rule: with sell in + sell out when there is sell out, else with sell in only). Null without sell in / sell out.
`nuestro_markup` does not move. Postgres only, like the sell in / sell out resolver it reads.
"""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from datetime import date, timedelta
from types import SimpleNamespace
from typing import Iterator, Optional
from unittest.mock import patch

import pytest
from sqlalchemy import Engine, event, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session, sessionmaker

from app.models.comision_config import ComisionListaGrupo, SubcategoriaGrupo
from app.models.comision_versionada import ComisionAdicionalCuota, ComisionBase, ComisionVersion
from app.models.pricing_constants import PricingConstants
from app.models.producto import ProductoERP
from app.models.publicacion_ml import PublicacionML
from app.models.sell_in import SellInBonoItem
from app.routers.ml_promotions import obtener_promociones_item
from app.services import ml_promotions_hay_mejores as hay_mejores
from app.services.envio_real_service import CostosEnvio
from app.services.ml_promotions_pricing import (
    enriquecer_markup_por_promo,
    markup_para_precio_con_sell_in_out,
    resolver_sell_in_out_para_mlas,
)
from app.services.ml_publications.view import detail, markup_service
from app.services.ml_publications.view.markup import UnitInputs
from app.services.ml_publications.view.markup_inputs import PublicationInputs
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


HEADER_PRICE = 60500.0  # the publication's sale price: the header prices it, the seller promo matches it


def _store_inputs(db: Session, item_ids: Optional[list[str]] = None, f=None) -> dict[str, PublicationInputs]:
    """Stands in for the publication store read (`fetch_inputs`, S11): each `publicaciones_ml` row of this world is
    a classic-list publication of its product, at `HEADER_PRICE`, with the product's own ERP fields."""
    out: dict[str, PublicationInputs] = {}
    for mla in item_ids or []:
        publicacion = db.query(PublicacionML).filter(PublicacionML.mla == mla).first()
        if publicacion is None:
            continue
        producto = db.query(ProductoERP).filter(ProductoERP.item_id == publicacion.item_id).first()
        unit = UnitInputs(
            item_id=mla,
            listing_type_id="gold_special",
            tags=(),
            sale_terms_campaign=None,
            sale_price=HEADER_PRICE,
            item_price=None,
            producto_item_id=producto.item_id,
            costo=None if producto.costo is None else float(producto.costo),
            moneda_costo=producto.moneda_costo,
            iva=float(producto.iva),
            envio=0.0,
            subcategoria_id=producto.subcategoria_id,
        )
        out[mla] = PublicationInputs(mla, unit, ())
    return out


@contextmanager
def _tienda() -> Iterator[None]:
    """The header unit's reads: the store stand-in above and no real shipping cost (mlwebhook is another DB)."""
    with ExitStack() as stack:
        stack.enter_context(patch.object(markup_service, "fetch_inputs", _store_inputs))
        stack.enter_context(patch("app.services.ml_promotions_pricing.fetch_inputs", _store_inputs))
        stack.enter_context(patch.object(markup_service, "resolver_costos_envio_mlas", lambda *a, **k: CostosEnvio()))
        yield


def _enrich(engine: Engine, *, sell_in_out: bool = True) -> list[dict]:
    with sessionmaker(bind=engine, autoflush=False)() as db:
        with _tienda():
            return enriquecer_markup_por_promo(db, MLA, _promos(), sell_in_out=sell_in_out)


def _limpio(markup_pct: float) -> float:
    """The promo's net, back from its plain markup over the plain cost (`calcular_markup`)."""
    return COSTO * (1 + markup_pct / 100)


def _lote_y_campana(engine: Engine, **campana) -> None:
    si.compra(engine, [(ROUTER, 2, "2000.00")], HOY - timedelta(days=30))  # 1000 ARS of sell in per unit
    gid = so.grupo(engine, [{"item_id": ROUTER}])
    so.campana(engine, [gid], DESDE, HASTA, **({"monto_unit": "500.00"} | campana))


class TestPromoIgualAlHeader:
    """S11 (owner, 2026-11-12): "se están contradiciendo los markups". A promo at the header's price shows the
    header's "Markup" and "c/ sell in/out" (`view.detail`: `compute_detail` and `_sell_in_out`)."""

    def test_a_promo_at_the_header_price_shows_both_header_markups(self, engine) -> None:
        _lote_y_campana(engine)
        links = [SimpleNamespace(variation_id=0, product_id=ROUTER, iva=21.0, match_status="linked")]
        with sessionmaker(bind=engine, autoflush=False)() as db, _tienda():
            found = markup_service.compute_detail(db, db, MLA)
            header = detail._sell_in_out(db, links, found, mla=MLA)
            promo = enriquecer_markup_por_promo(db, MLA, [_promos()[0]], sell_in_out=True)[0]

        assert found.breakdown.price == promo["price"] == HEADER_PRICE
        assert header is not None and header["markups_sell_in_out"][detail.SELL_IN_OUT_KEY] is not None
        assert promo["nuestro_markup"] == pytest.approx(found.breakdown.markup)
        assert promo["markup_sell_in_out"] == pytest.approx(header["markups_sell_in_out"][detail.SELL_IN_OUT_KEY])


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

    def test_a_net_price_percentage_sell_out_is_on_the_same_revenue_as_the_promo_markup(self, engine) -> None:
        """Owner, 2026-11-06: "se calcula sobre lo que nos dejaría la promo como el mark up que se muestra hoy en
        las promos, no tendría sentido tomarla de dos valores distintos" -> the base is `nuestro_markup`'s revenue:
        the promo price plus ML's co-funding, neither the bare consumer price nor the Clásica list price."""
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

        revenue_seller = 60500  # seller-funded: no co-funding
        revenue_smart = 55000 + 0.05 * 70000  # co-funded SMART: price + meli_percentage of the original price
        credito_seller = revenue_seller / 1.21 * 0.10  # 10 % of the revenue without VAT
        credito_smart = revenue_smart / 1.21 * 0.10
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

    def test_a_promo_without_markup_gets_no_sell_in_out_figure(self, engine) -> None:
        """The extra figure goes with the markup: never "N/A" next to "c/ sell in/out X%" (review advisory)."""
        _lote_y_campana(engine)

        with patch("app.services.ml_promotions_pricing.unit_markup", side_effect=ValueError("sin markup")):
            promos = _enrich(engine)

        assert [p["nuestro_markup"] for p in promos] == [None, None]
        assert [p["markup_sell_in_out"] for p in promos] == [None, None]

    def test_callers_that_do_not_ask_for_it_get_no_field(self, engine) -> None:
        _lote_y_campana(engine)

        promos = _enrich(engine, sell_in_out=False)

        assert all("markup_sell_in_out" not in p for p in promos)


def _resolver_que_falla(db, *args, **kwargs):
    """A sell in / sell out read that fails INSIDE the database: Postgres aborts the transaction it runs in."""
    db.execute(text("SELECT * FROM tabla_que_no_existe"))


def _lectura_real(db, *args, **kwargs):
    """Stands in for the router's later reads (`motivo_sin_consulta_ml`, `_marcar_escrituras_no_aplicadas`) with a
    real statement on the same session: it fails if the sell in / sell out failure left the transaction aborted."""
    db.query(PublicacionML).filter(PublicacionML.mla == MLA).count()


class TestFallaDelSellInOut:
    """The panel read is fail-soft: a failing sell in / sell out read (in its SAVEPOINT) nulls only the extra figure."""

    def test_the_item_read_still_answers_with_its_markups_and_a_usable_session(self, engine) -> None:
        _lote_y_campana(engine)
        sin_falla = [p["nuestro_markup"] for p in _enrich(engine)]

        with sessionmaker(bind=engine, autoflush=False)() as db:
            with (
                _tienda(),
                patch("app.services.ml_promotions_pricing.resolver_sell_in_out_batch", side_effect=_resolver_que_falla),
                patch("app.routers.ml_promotions.fetch_item_promotions", return_value=_promos()),
                patch("app.routers.ml_promotions.motivo_sin_consulta_ml", side_effect=_lectura_real),
                patch(
                    "app.routers.ml_promotions._marcar_escrituras_no_aplicadas",
                    side_effect=lambda db, mla, promos: _lectura_real(db) or [],
                ),
            ):
                respuesta = obtener_promociones_item(MLA, current_user=None, db=db)

            assert db.query(PublicacionML).count() == 1  # the session still serves reads after the savepoint

        assert respuesta.count == 2
        assert [p.nuestro_markup for p in respuesta.promotions] == sin_falla
        assert all(p.nuestro_markup is not None for p in respuesta.promotions)
        assert [p.markup_sell_in_out for p in respuesta.promotions] == [None, None]

    def test_the_failure_really_aborts_a_transaction_without_the_savepoint(self, engine) -> None:
        """Guards the test above: the stand-in failure does poison a plain transaction."""
        with sessionmaker(bind=engine, autoflush=False)() as db:
            with pytest.raises(ProgrammingError):
                _resolver_que_falla(db)
            with pytest.raises(Exception, match="current transaction is aborted"):
                _lectura_real(db)

    def test_the_price_read_keeps_its_markup(self, engine) -> None:
        _lote_y_campana(engine)

        with sessionmaker(bind=engine, autoflush=False)() as db:
            with (
                _tienda(),
                patch("app.services.ml_promotions_pricing.resolver_sell_in_out_batch", side_effect=_resolver_que_falla),
            ):
                nuestro, con_sio = markup_para_precio_con_sell_in_out(db, MLA, 60500.0)
            assert db.query(PublicacionML).count() == 1

        assert nuestro is not None
        assert con_sio is None


class TestPrecioManualYVigente:
    def test_a_price_gets_its_markup_with_sell_in_and_sell_out(self, engine) -> None:
        _lote_y_campana(engine)

        with sessionmaker(bind=engine, autoflush=False)() as db:
            with _tienda():
                nuestro, con_sio = markup_para_precio_con_sell_in_out(db, MLA, 60500.0)

        assert nuestro is not None
        assert con_sio == pytest.approx(round(((_limpio(nuestro) + 500) / (COSTO - 1000) - 1) * 100, 2), abs=0.01)

    def test_without_sell_in_or_sell_out_only_the_markup_comes(self, engine) -> None:
        with sessionmaker(bind=engine, autoflush=False)() as db:
            with _tienda():
                nuestro, con_sio = markup_para_precio_con_sell_in_out(db, MLA, 60500.0)

        assert nuestro is not None
        assert con_sio is None

    def test_an_unknown_publication_gives_neither(self, engine) -> None:
        with sessionmaker(bind=engine, autoflush=False)() as db:
            assert markup_para_precio_con_sell_in_out(db, "MLA0", 60500.0) == (None, None)


def _contar(engine: Engine, needle: str):
    """Counts the statements on `engine` that mention `needle` while the context is open."""
    conteo = {"n": 0}

    def _antes(conn, cursor, statement, params, context, executemany):
        if needle in statement:
            conteo["n"] += 1

    class _Ctx:
        def __enter__(self):
            event.listen(engine, "before_cursor_execute", _antes)
            return conteo

        def __exit__(self, *exc):
            event.remove(engine, "before_cursor_execute", _antes)
            return False

    return _Ctx()


class TestRankingConSellInOut:
    """S5 (owner: "va a tener que usar el sell in sell out"): hay_mejores compares the markups with sell in /
    sell out, read once and shared by the status quo and every candidate."""

    def test_the_real_chain_compares_the_sell_in_out_markups_on_both_sides(self, engine) -> None:
        _lote_y_campana(engine)
        candidata = {
            "id": "P-SMART",
            "type": "SMART",
            "status": "candidate",
            "price": 55000,
            "original_price": 70000,
            "meli_percentage": 5,
        }
        comparados: list = []
        real = hay_mejores.es_mejor_oferta

        def _espia(*args):
            comparados.append(args)
            return real(*args)

        with sessionmaker(bind=engine, autoflush=False)() as db:
            with (
                _tienda(),
                patch.object(hay_mejores, "es_mejor_oferta", side_effect=_espia),
            ):
                hay_mejores.listar_mejores_candidatas(db, MLA, [candidata], 60500.0, raw_promotions=[candidata])
                vigente = markup_para_precio_con_sell_in_out(db, MLA, 60500.0)
                promo = enriquecer_markup_por_promo(
                    db, MLA, [hay_mejores.normalizar_entrada_seller_promo(candidata)], sell_in_out=True
                )[0]

        assert vigente.markup_sell_in_out is not None and promo["markup_sell_in_out"] is not None
        assert comparados == [(55000.0, promo["markup_sell_in_out"], 60500.0, vigente.markup_sell_in_out)]

    def test_one_read_serves_many_publications(self, engine) -> None:
        _lote_y_campana(engine)
        with engine.begin() as conn:
            for mla, item in (("MLA2270", 2270), ("MLA950", 950)):
                conn.execute(
                    text("INSERT INTO publicaciones_ml (mla, item_id, pricelist_id, activo) VALUES (:m, :i, 4, true)"),
                    {"m": mla, "i": item},
                )
        try:
            with sessionmaker(bind=engine, autoflush=False)() as db, _tienda():
                with _contar(engine, "sell_out_campanas") as una:
                    resolver_sell_in_out_para_mlas(db, [MLA])
                with _contar(engine, "sell_out_campanas") as tres:
                    batch = resolver_sell_in_out_para_mlas(db, [MLA, "MLA2270", "MLA950"])
                with (
                    _contar(engine, "sell_out_campanas") as ranking,
                    _tienda(),
                ):
                    for mla in (MLA, "MLA2270", "MLA950"):
                        hay_mejores.listar_mejores_candidatas(db, mla, [], 60500.0, sell_in_out_batch=batch)
        finally:
            with engine.begin() as conn:
                conn.execute(text("DELETE FROM publicaciones_ml WHERE mla IN ('MLA2270', 'MLA950')"))

        assert una["n"] >= 1
        assert tres["n"] == una["n"]  # the same queries for one publication or three
        assert ranking["n"] == 0  # ranking with the read already done reads nothing more

    def test_a_failed_read_is_read_once_and_compares_both_sides_plain(self, engine) -> None:
        _lote_y_campana(engine)
        candidata = {
            "id": "P-SMART",
            "type": "SMART",
            "status": "candidate",
            "price": 55000,
            "original_price": 70000,
            "meli_percentage": 5,
        }
        comparados: list = []
        real = hay_mejores.es_mejor_oferta

        def _espia(*args):
            comparados.append(args)
            return real(*args)

        with sessionmaker(bind=engine, autoflush=False)() as db:
            with _tienda():
                vigente = markup_para_precio_con_sell_in_out(db, MLA, 60500.0)
                promo = enriquecer_markup_por_promo(
                    db, MLA, [hay_mejores.normalizar_entrada_seller_promo(candidata)], sell_in_out=True
                )[0]
            with (
                _tienda(),
                patch(
                    "app.services.ml_promotions_pricing.resolver_sell_in_out_batch", side_effect=RuntimeError("caída")
                ) as lectura,
                patch.object(hay_mejores, "es_mejor_oferta", side_effect=_espia),
            ):
                hay_mejores.listar_mejores_candidatas(db, MLA, [candidata], 60500.0, raw_promotions=[candidata])

        assert lectura.call_count == 1  # the shared read; neither side retries it
        assert comparados == [(55000.0, promo["nuestro_markup"], 60500.0, vigente.nuestro_markup)]
