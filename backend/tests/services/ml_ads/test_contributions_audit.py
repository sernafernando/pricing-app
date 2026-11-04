"""ml-ads-aportes-robust S5 -- every load, edit and delete of an aporte leaves an `auditoria` row with before/after.

The row is added in the same transaction as the change (the sell-in bonuses' pattern: `registrar_auditoria` commits
on its own), so a rejected write leaves none. `auditoria.tipo_accion` is VARCHAR(50) holding the member NAME, so
the new `TipoAccion` members need no DDL: these tests run on real Postgres to prove the column takes them.
Campaigns, the ERP product and the user are DERIVED rows.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.models.auditoria import Auditoria, TipoAccion
from app.models.ml_ads import MlAdsCampaign
from app.models.producto import ProductoERP
from app.services.ml_ads import contributions
from tests.services.ml_ads.conftest import ADS_TABLES, restore_pg_types
from tests.services.sell._schema import throwaway_schema

pytestmark = pytest.mark.postgres

ADV, CAMP = 714700, 351001
USER = 7


@pytest.fixture()
def db():
    from tests.conftest import _patch_pg_types_for_sqlite

    restore_pg_types()
    stubs = ["CREATE TABLE usuarios (id INTEGER PRIMARY KEY)", f"INSERT INTO usuarios VALUES ({USER})"]
    tables = [*ADS_TABLES, ProductoERP.__table__, Auditoria.__table__]
    try:
        with throwaway_schema("ads_audit", tables, stubs) as engine:
            with sessionmaker(bind=engine)() as session:
                session.add(MlAdsCampaign(advertiser_id=ADV, campaign_id=CAMP, raw={}))
                session.add(ProductoERP(item_id=1, codigo="COD1", descripcion="Router", marca="TP-Link"))
                session.commit()
                yield session
    finally:
        _patch_pg_types_for_sqlite()


def _data(value: str = "30", last: date = date(2026, 10, 31), brand: str = "tp-link") -> contributions.ContributionData:
    return contributions.ContributionData(
        ADV, CAMP, "percentage", Decimal(value), date(2026, 10, 1), last, brand, "Q4 co-op"
    )


def _audit(db) -> list[tuple[str, Optional[dict], Optional[dict], int]]:
    """Each row as stored: the raw VARCHAR, so the member NAME is what Postgres holds."""
    rows = db.execute(
        text("SELECT tipo_accion, valores_anteriores, valores_nuevos, usuario_id FROM auditoria ORDER BY id")
    ).all()
    return [tuple(r) for r in rows]


def _snapshot(row_id: int, value: str = "30.00", last: str = "2026-10-31") -> dict:
    return {
        "id": row_id,
        "channel": "product_ads",
        "advertiser_id": ADV,
        "campaign_id": CAMP,
        "kind": "percentage",
        "value": value,
        "date_from": "2026-10-01",
        "date_to": last,
        "settlement": None,
        "brand": "TP-Link",
        "note": "Q4 co-op",
    }


def test_a_load_leaves_a_created_row_with_what_was_saved(db) -> None:
    row = contributions.create(db, _data(), USER)
    assert _audit(db) == [("ML_ADS_APORTE_CREADO", None, _snapshot(row.id), USER)]


def test_an_edit_leaves_the_values_before_and_after(db) -> None:
    row = contributions.create(db, _data(), USER)
    contributions.update(db, row.id, _data(value="50", last=date(2026, 10, 15)), USER)
    created, edited = _audit(db)
    assert edited == (
        "ML_ADS_APORTE_EDITADO",
        _snapshot(row.id),
        _snapshot(row.id, value="50.00", last="2026-10-15"),
        USER,
    )
    assert created[0] == "ML_ADS_APORTE_CREADO"


def test_a_delete_leaves_what_was_removed(db) -> None:
    row = contributions.create(db, _data(), USER)
    assert contributions.delete(db, row.id, USER) is True
    assert _audit(db)[-1] == ("ML_ADS_APORTE_BORRADO", _snapshot(row.id), None, USER)


def test_a_rejected_write_leaves_no_row(db) -> None:
    with pytest.raises(contributions.ContributionError):
        contributions.create(db, _data(brand="Xerox"), USER)
    db.rollback()
    row = contributions.create(db, _data(), USER)
    with pytest.raises(contributions.ContributionError):
        contributions.create(db, _data(), USER)  # overlaps the first one
    db.rollback()
    assert [tipo for tipo, *_ in _audit(db)] == ["ML_ADS_APORTE_CREADO"]
    assert _audit(db)[0][2]["id"] == row.id


def test_the_members_fit_the_varchar_column() -> None:
    names = [TipoAccion.ML_ADS_APORTE_CREADO, TipoAccion.ML_ADS_APORTE_EDITADO, TipoAccion.ML_ADS_APORTE_BORRADO]
    assert all(len(member.name) <= 50 for member in names)
