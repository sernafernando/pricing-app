"""S11b: the PxQ tier markup prices the list ML charges the item, like the publication header.

Owner (2026-11-12), on the promo card vs the header: "se están contradiciendo los markups" -> "arreglalo ya están
calculando con esos markups". The PxQ context had the same defect as the promo markup (A): its commission came from
the stored `publicaciones_ml.pricelist_id` instead of `resolve_pricelist` on the ML item (listing type, campaign tag,
then the installments sale term), which is what the header prices (`view/markup.py`).

Runs over the real store migrations (`ml_items`, its sale-term campaign column) in a throwaway schema.
"""

from __future__ import annotations

import json
from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.models.comision_config import SubcategoriaGrupo
from app.models.comision_versionada import ComisionAdicionalCuota, ComisionBase, ComisionVersion
from app.services.pxq_pricing_context import PxqPricingContext, PxqPricingUnavailable, resolve_pxq_pricing_context
from tests.services.ml_publications.conftest import env, mlpub_pg  # noqa: F401
from tests.services.ml_publications.view import seed

pytestmark = pytest.mark.postgres

MLA = "MLA1"
PRODUCT = 70
BASE = 15.5
ADICIONAL_POR_CUOTAS = {3: 2.0, 6: 4.0, 9: 7.0, 12: 10.0}


@pytest.fixture()
def conn(env):  # noqa: F811
    for model in (ComisionVersion, ComisionBase, ComisionAdicionalCuota, SubcategoriaGrupo):
        model.__table__.create(bind=env)
    with env.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        yield connection


@pytest.fixture()
def db(env, conn):  # noqa: F811
    session = sessionmaker(bind=env, autocommit=False, autoflush=False)()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def _terms(campaign: str) -> str:
    return json.dumps({"sale_terms": [{"id": "INSTALLMENTS_CAMPAIGN", "value_name": campaign}]})


def _seed(conn, db, stored_pricelist: int, in_store: bool = True, **item) -> None:
    seed.add_product(conn, PRODUCT, "C70", "Producto 70")
    seed.add_cost(conn, PRODUCT, 40000.0)
    conn.execute(
        text(
            "INSERT INTO publicaciones_ml (mla, item_id, codigo, pricelist_id, activo) VALUES (:m, :i, 'C70', :p, true)"
        ),
        {"m": MLA, "i": PRODUCT, "p": stored_pricelist},
    )
    if in_store:
        seed.add_item(conn, MLA, **item)
        seed.add_link(conn, MLA, PRODUCT)
    version = ComisionVersion(nombre="S11b", fecha_desde=date(2000, 1, 1), activo=True)
    db.add(version)
    db.flush()
    db.add(ComisionBase(version_id=version.id, grupo_id=1, comision_base=BASE))
    for cuotas, adicional in ADICIONAL_POR_CUOTAS.items():
        db.add(ComisionAdicionalCuota(version_id=version.id, cuotas=cuotas, adicional=adicional))
    db.flush()


# The stored list says one thing, the ML item another: the item wins (9x by tag, 12x by sale term, classic).
CASES = {
    "nine_by_tag": (17, dict(listing_type_id="gold_pro", tags=["9x_campaign"]), BASE + ADICIONAL_POR_CUOTAS[9]),
    "twelve_by_sale_term": (4, dict(listing_type_id="gold_pro", raw=_terms("12x_campaign")), BASE + 10.0),
    "six_without_campaign": (4, dict(listing_type_id="gold_pro"), BASE + ADICIONAL_POR_CUOTAS[6]),
    "classic": (23, dict(listing_type_id="gold_special"), BASE),
}


@pytest.mark.parametrize("stored, item, expected", list(CASES.values()), ids=list(CASES))
def test_commission_follows_the_list_ml_charges_the_item(conn, db, stored, item, expected) -> None:
    _seed(conn, db, stored, **item)

    context = resolve_pxq_pricing_context(db, MLA)

    assert isinstance(context, PxqPricingContext)
    assert context.comision_base_pct == pytest.approx(expected)
    assert context.costo_ars == pytest.approx(40000.0)


@pytest.mark.parametrize(
    "item, reason",
    [
        (dict(listing_type_id="gold_special", tags=["pcj-co-funded"]), "cofinanciada"),
        (dict(listing_type_id="free"), "sin_lista"),
    ],
    ids=["cofinanciada", "sin_lista"],
)
def test_an_item_with_no_list_of_ours_reports_the_header_reason(conn, db, item, reason) -> None:
    """No list of ours for the item (`resolve_pricelist` gives none): its reason, never the stored list instead."""
    _seed(conn, db, 4, **item)

    context = resolve_pxq_pricing_context(db, MLA)

    assert isinstance(context, PxqPricingUnavailable)
    assert context.reason == reason


def test_a_publication_not_in_the_store_reports_sin_item_ml(conn, db) -> None:
    """Without the ML item there is no list to price: never the stored list instead."""
    _seed(conn, db, 4, in_store=False)

    assert resolve_pxq_pricing_context(db, MLA) == PxqPricingUnavailable("sin_item_ml")


def test_cost_iva_and_subcategory_come_from_the_product_the_store_links(conn, db) -> None:
    """S11b: `publicaciones_ml.item_id` names product 70, the item-level store link product 71 (another cost, IVA
    and subcategory group): the PxQ context prices product 71, as the header does."""
    _seed(conn, db, 4, listing_type_id="gold_special")
    seed.add_product(conn, 71, "C71", "Producto 71", subcategoria_id=3845)
    seed.add_cost(conn, 71, 65000.0, iva=10.5)
    conn.execute(text("UPDATE ml_item_product_links SET producto_item_id = 71 WHERE item_id = :m"), {"m": MLA})
    db.add(SubcategoriaGrupo(subcat_id=3845, grupo_id=2))
    version = db.query(ComisionVersion).one()
    db.add(ComisionBase(version_id=version.id, grupo_id=2, comision_base=12.0))
    db.flush()

    context = resolve_pxq_pricing_context(db, MLA)

    assert context == PxqPricingContext(costo_ars=65000.0, comision_base_pct=12.0, iva=10.5, grupo_id=2)
