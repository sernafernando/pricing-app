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


def test_a_duplicated_requested_mla_still_has_one_owner(db):
    from sqlalchemy import literal, union_all

    _publish(db, 1, "MLA1", 10)
    asked = union_all(select(literal("MLA1")), select(literal("MLA1")))
    assert db.execute(ads_owner_select(sqlite=True, mlas=select(asked.c[0]))).all() == [("MLA1", 10)]


def test_a_requested_mla_without_publication_still_falls_back_to_its_last_sale(db):
    from sqlalchemy import literal, union_all

    _sell(db, 900, 10, "MLA2", 31)
    _sell(db, 901, 20, "MLA2", 32)
    _sell(db, 902, 25, "MLA3", 40)
    asked = union_all(select(literal("MLA2")), select(literal("MLA8")))
    rows = db.execute(ads_owner_select(sqlite=True, mlas=select(asked.c[0]))).all()
    assert sorted(rows) == [("MLA2", 32), ("MLA8", NO_PRODUCT)]


def _subquery_sql(sql: str, alias: str) -> str:
    """The text of the parenthesised subquery named `alias` in `sql`."""
    end = sql.index(f") AS {alias}")
    depth = 0
    for start in range(end, -1, -1):
        depth += {")": 1, "(": -1}.get(sql[start], 0)
        if depth == 0:
            return sql[start : end + 1]
    raise AssertionError(f"unbalanced subquery {alias}")


def test_the_last_sale_fallback_reads_only_the_requested_mlas_history():
    """With `mlas`, the last-sale aggregate is restricted BEFORE its GROUP BY: Postgres does not push a filter on
    the windowed fallback down into it, and every MLA's whole sales history was aggregated to keep a few."""
    from sqlalchemy.dialects import postgresql

    from app.models.ml_orders_ops import MlOrderItemOps

    sql = str(
        ads_owner_select(sqlite=False, mlas=select(MlOrderItemOps.item_id).where(MlOrderItemOps.order_id == 1)).compile(
            dialect=postgresql.dialect()
        )
    )
    last_sale = _subquery_sql(sql, "ads_last_sale")
    assert "GROUP BY" in last_sale
    assert "ml_order_items_ops.item_id IN (SELECT" in last_sale, last_sale
