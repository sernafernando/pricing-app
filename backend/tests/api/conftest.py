"""Fixtures shared by the API tests."""

from __future__ import annotations

import pytest
from sqlalchemy import inspect

from app.models.combo_componente import ComboComponente
from tests.routers.conftest import COMBO_SEMILLA, COMPONENTE_SEMILLA


@pytest.fixture(autouse=True)
def _bom_sincronizado(request) -> None:
    """As for the router tests: the combo bill of materials starts synced for a test whose `db` has the table (sell
    in and sell out refuse an empty one). A Postgres world built without it is left alone."""
    if "db" not in request.fixturenames:
        return
    db = request.getfixturevalue("db")
    if not inspect(db.get_bind()).has_table(ComboComponente.__tablename__):
        return
    db.add(ComboComponente(combo_item_id=COMBO_SEMILLA, componente_item_id=COMPONENTE_SEMILLA, cantidad=1))
    db.commit()
