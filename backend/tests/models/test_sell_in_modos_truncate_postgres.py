"""Every TRUNCATE route to the cost modes is refused on the migrated schema (#2004 verification)."""

from __future__ import annotations
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from tests.models.test_sell_in_modos_guard_postgres import _foto, _mundo
from tests.models.test_sell_in_schema_postgres import engine  # noqa: F401

pytestmark = pytest.mark.postgres


@pytest.mark.parametrize(
    "sql",
    [
        "TRUNCATE sell_in_modos_producto",
        "TRUNCATE ONLY sell_in_modos_producto",
        "TRUNCATE TABLE sell_in_modos_producto RESTART IDENTITY CASCADE",
        "TRUNCATE sell_in_modos_producto, sell_in_consumos",
        "TRUNCATE sell_in_compras CASCADE",
        "TRUNCATE usuarios CASCADE",
        "TRUNCATE productos_erp CASCADE",
    ],
)
def test_truncate_route(engine, sql) -> None:  # noqa: F811
    _mundo(engine)
    antes = _foto(engine)
    with pytest.raises(DBAPIError):
        with engine.begin() as conn:
            conn.execute(text(sql))
    assert _foto(engine) == antes
