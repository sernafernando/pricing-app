"""Round-trip tests for the ML publications sub-resource models (SQLite create_all).

The Postgres types are remapped by the `engine` fixture in `tests/conftest.py`; the real
DDL is covered by the Postgres migration test and the Postgres round trip in
`tests/services/ml_publications/test_subresource_models_pg.py`.
"""

from __future__ import annotations

from decimal import Decimal

from app.models.ml_publications import (
    MlItem,
    MlItemDescription,
    MlItemPrices,
    MlItemSalePrice,
    MlItemSellerPromotions,
    MlUserProduct,
    MlUserProductFamily,
    MlUserProductStock,
)

FAMILY_ID = 7695306917964170


def test_item_scoped_sub_resources_round_trip_raw_and_typed_columns(db) -> None:
    db.add(MlItemDescription(item_id="MLA1", plain_text_length=12, raw={"plain_text": "x"}, raw_hash=b"\x01"))
    db.add(
        MlItemPrices(
            item_id="MLA1",
            standard_amount=Decimal("55882.00"),
            currency_id="ARS",
            active_promotion_amount=Decimal("1509999.00"),
            raw={"prices": []},
            http_status=200,
        )
    )
    db.add(
        MlItemSalePrice(
            item_id="MLA1",
            price_id="465",
            amount=Decimal("55882.00"),
            promotion_id="OFFER-1",
            raw={"amount": 55882.0},
        )
    )
    db.add(
        MlItemSellerPromotions(
            item_id="MLA1",
            candidate_count=7,
            started_count=1,
            started_promotion_keys=["C-MLA1669550"],
            raw=[{"id": "C-MLA1669550"}],
        )
    )
    db.flush()
    db.expire_all()
    assert db.get(MlItemDescription, "MLA1").raw == {"plain_text": "x"}
    assert db.get(MlItemPrices, "MLA1").active_promotion_amount == Decimal("1509999.00")
    assert db.get(MlItemSalePrice, "MLA1").promotion_id == "OFFER-1"
    promotions = db.get(MlItemSellerPromotions, "MLA1")
    assert promotions.started_promotion_keys == ["C-MLA1669550"] and promotions.raw == [{"id": "C-MLA1669550"}]
    assert promotions.never_existed is False and promotions.first_seen_at is not None


def test_user_product_sub_resources_round_trip_exact_family_id(db) -> None:
    db.add(MlUserProduct(user_product_id="MLAU1", family_id=FAMILY_ID, name="Teclado", raw={"id": "MLAU1"}))
    db.add(MlUserProductStock(user_product_id="MLAU1", total_quantity=26, raw={"id": "MLAU1"}))
    db.add(MlUserProductFamily(family_id=FAMILY_ID, user_products_ids=["MLAU1"], raw={"family_id": FAMILY_ID}))
    db.flush()
    db.expire_all()
    assert db.get(MlUserProduct, "MLAU1").family_id == FAMILY_ID
    assert db.get(MlUserProductStock, "MLAU1").total_quantity == 26
    family = db.get(MlUserProductFamily, FAMILY_ID)
    assert family.user_products_ids == ["MLAU1"] and family.raw["family_id"] == FAMILY_ID


def test_never_existed_is_declared_like_on_the_item_table() -> None:
    """One declaration of the flag across the store: a database default only, no Python-side default."""
    models = (
        MlItemDescription,
        MlItemPrices,
        MlItemSalePrice,
        MlItemSellerPromotions,
        MlUserProduct,
        MlUserProductStock,
        MlUserProductFamily,
    )
    expected = MlItem.__table__.c.never_existed
    for model in models:
        column = model.__table__.c.never_existed
        assert column.default is None and expected.default is None, model.__name__
        assert str(column.server_default.arg) == str(expected.server_default.arg), model.__name__
