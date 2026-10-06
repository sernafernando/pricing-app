"""`MlTiendaOficial` model: defaults and primary key semantics."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.ml_tienda_oficial import MlTiendaOficial


def test_defaults_are_active_and_order_zero(db) -> None:
    db.add(MlTiendaOficial(store_id=1, nombre="Una"))
    db.flush()
    row = db.get(MlTiendaOficial, 1)
    assert row.activa is True
    assert row.orden == 0
    assert row.created_at is not None


def test_store_id_is_unique(db) -> None:
    db.add(MlTiendaOficial(store_id=7, nombre="A"))
    db.flush()
    db.add(MlTiendaOficial(store_id=7, nombre="B"))
    with pytest.raises(IntegrityError):
        db.flush()


def test_clave_is_optional_and_shared_between_stores(db) -> None:
    db.add(MlTiendaOficial(store_id=1, nombre="A"))
    db.add(MlTiendaOficial(store_id=2, nombre="B", clave="tplink"))
    db.add(MlTiendaOficial(store_id=3, nombre="B nuevo", clave="tplink"))
    db.flush()
    assert db.get(MlTiendaOficial, 1).clave is None
    assert db.get(MlTiendaOficial, 3).clave == "tplink"
