"""The owner of an MLA's ads (MA-4 / design D7): newest publication, else the product of its most recent
sale, else "sin producto". One owner per MLA, defined once."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select

from app.models.mercadolibre_item_publicado import MercadoLibreItemPublicado as M
from app.models.ml_publications import MlItemProductLink
from app.services.ml_ads.owner import NO_PRODUCT, ads_owner_select
from tests.services.ml_daily_metrics.seed import Line, seed_sale


def _publish(db, mlp_id: int, mla: str, product: int | None) -> None:
    db.add(M(mlp_id=mlp_id, mlp_publicationID=mla, item_id=product))
    db.flush()


def _sell(db, order_id: int, day: int, mla: str, product: int | None) -> None:
    seed_sale(
        db,
        order_id,
        datetime(2026, 9, day, 15, tzinfo=timezone.utc),
        [Line(product=product, mla=mla, qty=1, unit_price=Decimal("100"))],
    )


def _owners(db, *mlas: str) -> dict:
    return {mla: product for mla, product in db.execute(ads_owner_select(sqlite=True)).all() if mla in mlas}


def test_the_newest_publication_with_a_product_wins(db):
    _publish(db, 1, "MLA1", 10)
    _publish(db, 2, "MLA1", 20)
    assert _owners(db, "MLA1") == {"MLA1": 20}


def test_a_newer_publication_without_a_product_does_not_hide_the_older_owner(db):
    _publish(db, 1, "MLA1", 10)
    _publish(db, 2, "MLA1", None)
    assert _owners(db, "MLA1") == {"MLA1": 10}


def test_the_publication_beats_the_last_sale_product(db):
    _publish(db, 1, "MLA1", 10)
    _sell(db, 900, 20, "MLA1", 77)
    assert _owners(db, "MLA1") == {"MLA1": 10}


def test_without_a_publication_the_most_recent_sale_decides(db):
    _sell(db, 900, 10, "MLA2", 31)
    _sell(db, 901, 20, "MLA2", 32)
    assert _owners(db, "MLA2") == {"MLA2": 32}


def test_a_tie_on_the_sale_day_goes_to_the_higher_product_id(db):
    _sell(db, 900, 20, "MLA2", 31)
    _sell(db, 901, 20, "MLA2", 35)
    assert _owners(db, "MLA2") == {"MLA2": 35}


def test_a_sale_without_a_frozen_cost_row_is_sin_producto(db):
    _sell(db, 900, 20, "MLA3", None)
    assert _owners(db, "MLA3") == {"MLA3": NO_PRODUCT}


def test_a_linked_only_mla_is_sin_producto(db):
    db.add(
        MlItemProductLink(
            item_id="MLA4",
            source="test",
            match_status="linked",
            producto_item_id=55,
            linked_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        )
    )
    db.flush()
    owners = ads_owner_select(sqlite=True, mlas=select(MlItemProductLink.item_id))
    assert dict(db.execute(owners).all()) == {"MLA4": NO_PRODUCT}


def test_every_requested_mla_gets_exactly_one_owner(db):
    _publish(db, 1, "MLA1", 10)
    _publish(db, 2, "MLA1", 11)
    _sell(db, 900, 20, "MLA1", 12)
    _sell(db, 901, 21, "MLA1", 13)
    from sqlalchemy import literal, union_all

    asked = union_all(select(literal("MLA1")), select(literal("MLA9")))
    rows = db.execute(ads_owner_select(sqlite=True, mlas=select(asked.c[0]))).all()
    assert sorted(rows) == [("MLA1", 11), ("MLA9", NO_PRODUCT)]
