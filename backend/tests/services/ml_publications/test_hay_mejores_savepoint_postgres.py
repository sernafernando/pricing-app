"""Postgres proof: hay_mejores flag update failure must not poison the promotions sync session."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.models.ml_publications import MlItemSalePrice, MlItemSellerPromotions
from app.services import ml_promotions_hay_mejores as hay_mejores


@pytest.mark.postgres
def test_actualizar_failure_rolls_back_savepoint_and_leaves_session_usable(mlpub_pg, monkeypatch) -> None:
    session = sessionmaker(bind=mlpub_pg)()
    try:
        session.add(
            MlItemSellerPromotions(
                item_id="MLA1",
                candidate_count=1,
                started_promotion_keys=[],
                raw=[{"id": "C-1", "type": "SMART", "status": "candidate", "price": 900}],
                hay_mejores_ofertas=False,
            )
        )
        session.add(MlItemSalePrice(item_id="MLA1", amount=Decimal("1000.00"), raw={"amount": 1000}))
        session.commit()

        def boom(*_args, **_kwargs):
            raise RuntimeError("forced hay_mejores failure")

        monkeypatch.setattr(hay_mejores, "listar_mejores_candidatas", boom)

        assert hay_mejores.actualizar_hay_mejores_ofertas(session, "MLA1") is None
        # Outer transaction still accepts commands (no PendingRollbackError / aborted txn).
        assert session.execute(text("SELECT 1")).scalar_one() == 1
        row = session.get(MlItemSellerPromotions, "MLA1")
        assert row is not None
        assert row.hay_mejores_ofertas is False
    finally:
        session.close()
