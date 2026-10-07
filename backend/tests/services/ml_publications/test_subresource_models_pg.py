"""The sub-resource models against the REAL migrations (Postgres): types and defaults match the DDL."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.orm import sessionmaker

from app.models.ml_publications import (
    MlItemDescription,
    MlItemPrices,
    MlItemSalePrice,
    MlItemSellerPromotions,
    MlUserProduct,
    MlUserProductFamily,
    MlUserProductStock,
)

FAMILY_ID = 7695306917964170


@pytest.mark.postgres
def test_models_round_trip_on_the_real_tables(mlpub_pg) -> None:
    session = sessionmaker(bind=mlpub_pg)()
    try:
        session.add_all(
            [
                MlItemDescription(item_id="MLA1", plain_text_length=3, raw={"plain_text": "abc"}, raw_hash=b"\x01"),
                MlItemPrices(item_id="MLA1", standard_amount=Decimal("1.50"), raw={"prices": []}),
                MlItemSalePrice(item_id="MLA1", amount=Decimal("1.50"), raw={"amount": 1.5}),
                MlItemSellerPromotions(
                    item_id="MLA1", candidate_count=1, started_promotion_keys=["PRICE_DISCOUNT"], raw=[{"type": "x"}]
                ),
                MlUserProduct(user_product_id="MLAU1", family_id=FAMILY_ID, raw={"id": "MLAU1"}),
                MlUserProductStock(user_product_id="MLAU1", total_quantity=26, raw={"id": "MLAU1"}),
                MlUserProductFamily(family_id=FAMILY_ID, user_products_ids=["MLAU1"], raw={"family_id": FAMILY_ID}),
            ]
        )
        session.commit()
        session.expire_all()
        assert session.get(MlItemSellerPromotions, "MLA1").raw == [{"type": "x"}]
        assert session.get(MlUserProduct, "MLAU1").family_id == FAMILY_ID
        assert session.get(MlUserProductFamily, FAMILY_ID).user_products_ids == ["MLAU1"]
        assert session.get(MlItemDescription, "MLA1").never_existed is False
    finally:
        session.close()
