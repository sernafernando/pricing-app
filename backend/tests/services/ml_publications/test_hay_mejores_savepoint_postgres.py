"""Postgres proof: hay_mejores flag update failure must not poison the promotions sync session.

A Python exception never aborts the Postgres transaction, so the failure inside the
SAVEPOINT must be a real DB error (e.g. SELECT 1/0) after a write — otherwise the
test still passes with `begin_nested` removed.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.models.ml_publications import MlItemSalePrice, MlItemSellerPromotions
from app.services import ml_promotions_hay_mejores as hay_mejores


@pytest.mark.postgres
def test_actualizar_db_failure_rolls_back_savepoint_and_leaves_session_usable(mlpub_pg, monkeypatch) -> None:
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

        def write_then_db_error(db, *_args, **_kwargs):
            row = db.query(MlItemSellerPromotions).filter(MlItemSellerPromotions.item_id == "MLA1").one()
            row.hay_mejores_ofertas = True
            db.flush()
            db.execute(text("SELECT 1/0"))

        monkeypatch.setattr(hay_mejores, "listar_mejores_candidatas", write_then_db_error)

        assert hay_mejores.actualizar_hay_mejores_ofertas(session, "MLA1") is None
        # Outer transaction still accepts commands (no aborted-txn poison).
        assert session.execute(text("SELECT 1")).scalar_one() == 1
        session.expire_all()
        row = session.get(MlItemSellerPromotions, "MLA1")
        assert row is not None
        assert row.hay_mejores_ofertas is False
    finally:
        session.close()


@pytest.mark.postgres
def test_enqueue_sql_failure_keeps_hay_mejores_flag(mlpub_pg, monkeypatch) -> None:
    """A real SQL error inside the enqueue SAVEPOINT must not undo the flag write."""
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

        monkeypatch.setattr(
            hay_mejores,
            "listar_mejores_candidatas",
            lambda *_a, **_k: [("C-1", 900.0)],
        )
        monkeypatch.setattr(
            "app.services.catalog_competition_target.mla_for_catalog_competition_refresh",
            lambda _db, _mla: "MLA1",
        )

        def boom(_db, _ids, _now):
            _db.execute(text("SELECT 1/0"))

        monkeypatch.setattr("app.services.catalog_competition_refresh_queue.enqueue", boom)

        decision = hay_mejores.actualizar_hay_mejores_ofertas(session, "MLA1")
        assert decision is not None and decision.hay_mejores is True
        assert session.execute(text("SELECT 1")).scalar_one() == 1
        session.expire_all()
        row = session.get(MlItemSellerPromotions, "MLA1")
        assert row is not None
        assert row.hay_mejores_ofertas is True
    finally:
        session.close()
