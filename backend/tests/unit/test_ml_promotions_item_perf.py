"""
`GET /promociones/item/{mla}` does not hit the database once per promo
(perf/productos-promos-first-load, N+1 PR).

Production profile (item 4293, 50 MLAs, 607 promos): 1,180 statements and 1.8 s,
of which 690 statements / 952 ms were `obtener_constantes_pricing`, called by
`calcular_comision_ml_total` and `calcular_limpio` for EVERY promo because
`_calcular_nuestro_markup` passed `db=db` and no `constantes`.

Layout:
  * characterization — the markups for a set of promos (ARS and USD cost, every
    price tier, co-funding and boost, the shipping-average fallback) are pinned
    from `origin/main` BEFORE the change and must not move.
  * RED structural — pricing constants and the group shipping average are
    resolved at most once per item request, however many promos it lists.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date
from unittest.mock import patch

import pytest
from sqlalchemy import event

from app.models.comision_config import SubcategoriaGrupo
from app.models.comision_versionada import ComisionBase, ComisionVersion
from app.models.pricing_constants import PricingConstants
from app.models.producto import ProductoERP
from app.models.publicacion_ml import PublicacionML
from app.models.tipo_cambio import TipoCambio
from app.services.ml_promotions_pricing import (
    _markup_con_contexto,
    _resolve_pricing_context,
    enriquecer_markup_por_promo,
)

SUBCAT = 77


def _promo(kind: str, status: str, price, original, suggested=None, payload=None) -> dict:
    return {
        "mla": "MLA1",
        "promotion_id": f"P-{kind}-{status}-{price}",
        "promotion_type": kind,
        "status": status,
        "price": price,
        "original_price": original,
        "suggested_discounted_price": suggested,
        "payload": payload or {},
    }


# Every price tier of the ML commission (<15k, <24k, <33k, >=33k), a co-funded SMART, a boosted SMART, a
# candidate priced by its suggestion, and one with no usable price (None).
PROMOS = [
    _promo("SELLER_CAMPAIGN", "started", 9000, 10000),
    _promo("DEAL", "candidate", 0, 20000, suggested=18000),
    _promo("SMART", "started", 22000, 28178, payload={"meli_percentage": 1.4}),
    _promo(
        "SMART",
        "candidate",
        30000,
        35000,
        payload={"meli_percentage": 8, "boosted_offer": True, "discount_meli_boost_amount": 555},
    ),
    _promo("PRICE_MATCHING", "started", 41000, 45000, payload={"meli_percentage": 3}),
    _promo("DEAL", "candidate", 0, 1000),
]


@pytest.fixture
def world(db):
    db.add(
        PricingConstants(
            monto_tier1=15000,
            monto_tier2=24000,
            monto_tier3=33000,
            comision_tier1=1095,
            comision_tier2=2190,
            comision_tier3=2628,
            varios_porcentaje=7.5,  # NOT the 6.5 default: a wrong/missing constants lookup would show
            grupo_comision_default=1,
            markup_adicional_cuotas=4.0,
            comision_tienda_nube=1.0,
            fecha_desde=date(2000, 1, 1),
        )
    )
    version = ComisionVersion(nombre="perf", fecha_desde=date(2000, 1, 1), activo=True)
    db.add(version)
    db.flush()
    db.add(ComisionBase(version_id=version.id, grupo_id=5, comision_base=13.0))
    db.add(SubcategoriaGrupo(subcat_id=SUBCAT, grupo_id=5))
    db.add(TipoCambio(moneda="USD", fecha=date(2000, 1, 1), venta=1200.0))
    # The product (no own shipping cost) and a neighbour in the same group that sets the group average.
    db.add(
        ProductoERP(
            item_id=1,
            codigo="P1",
            descripcion="Producto 1",
            costo=10.0,
            moneda_costo="USD",
            iva=21.0,
            subcategoria_id=SUBCAT,
            envio=0,
            activo=True,
        )
    )
    db.add(
        ProductoERP(
            item_id=2,
            codigo="P2",
            descripcion="Vecino",
            costo=100.0,
            moneda_costo="ARS",
            iva=21.0,
            subcategoria_id=SUBCAT,
            envio=2000,
            activo=True,
        )
    )
    db.add(PublicacionML(mla="MLA1", item_id=1, pricelist_id=4, activo=True))
    db.commit()
    return db


@contextmanager
def _count_statements(db, *needles: str):
    counts = {needle: 0 for needle in needles}

    def _before(conn, cursor, statement, params, context, executemany):
        for needle in needles:
            if needle in statement:
                counts[needle] += 1

    engine = db.get_bind()
    event.listen(engine, "before_cursor_execute", _before)
    try:
        yield counts
    finally:
        event.remove(engine, "before_cursor_execute", _before)


def _run(db, promos=None):
    promos = [dict(p) for p in (PROMOS if promos is None else promos)]
    with patch("app.services.ml_promotions_pricing.resolver_costo_envio", return_value=0.0):
        return enriquecer_markup_por_promo(db, "MLA1", promos)


# USD cost 10 * 1200 = 12000 ARS, IVA 21, commission base 13 %, shipping 0 -> group average 2000, varios 7.5 %.
# Pinned from origin/main before the change (`pytest -k characterization`, values printed with repr).
PINNED_MARKUPS = [
    -58.26446280991735,
    -16.528925619834702,
    7.531826033057865,
    68.85141184573003,
    118.10089531680444,
    None,
]
# The plain-price chain (`markup_para_precio` / catalog competitors) at three tiers, same context.
PINNED_PLAIN = [(5000.0, -80.16528925619835), (20000.0, -5.578512396694224), (40000.0, 105.2341597796143)]


class TestCharacterization:
    def test_markups_are_pinned(self, world) -> None:
        result = _run(world)

        assert [p["nuestro_markup"] for p in result] == [
            pytest.approx(v) if v is not None else None for v in PINNED_MARKUPS
        ]

    def test_plain_price_markups_with_a_resolved_context_are_pinned(self, world) -> None:
        with patch("app.services.ml_promotions_pricing.resolver_costo_envio", return_value=0.0):
            context = _resolve_pricing_context(world, "MLA1")
        assert context is not None

        for price, expected in PINNED_PLAIN:
            assert _markup_con_contexto(world, context, price) == pytest.approx(expected)


class TestStatementsPerItemRequest:
    def test_pricing_constants_are_read_once_for_many_promos(self, world) -> None:
        with _count_statements(world, "pricing_constants") as counts:
            _run(world)

        assert counts["pricing_constants"] <= 1

    def test_group_shipping_average_is_read_at_most_once(self, world) -> None:
        with _count_statements(world, "avg(productos_erp.envio)", "AVG(productos_erp.envio)") as counts:
            _run(world)

        assert sum(counts.values()) <= 1

    def test_statements_do_not_grow_with_the_number_of_promos(self, world) -> None:
        with _count_statements(world, "SELECT") as few:
            _run(world, PROMOS[3:5])
        with _count_statements(world, "SELECT") as many:
            _run(world, PROMOS * 5)

        assert many["SELECT"] == few["SELECT"]

    def test_markup_con_contexto_reuses_the_context_constants(self, world) -> None:
        with patch("app.services.ml_promotions_pricing.resolver_costo_envio", return_value=0.0):
            context = _resolve_pricing_context(world, "MLA1")
        with _count_statements(world, "pricing_constants") as counts:
            for price in (5000.0, 20000.0, 40000.0):
                _markup_con_contexto(world, context, price)

        assert counts["pricing_constants"] == 0
