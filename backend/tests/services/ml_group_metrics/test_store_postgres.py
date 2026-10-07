"""`store_group_metrics` against a REAL Postgres connection.

The dialect branch in `store_group_metrics` runs ONLY when the bind is
postgresql, so the SQLite suite never executes it -- it is money-path code
with no coverage at all until this file exists. A review flagged that the
`.values(member_order_ids=...)` call could pin the compiled INSERT to that
single column and silently drop the rest, which would surface as a NOT NULL
violation on `gauss_status`/`formula_version`/`computed_at`.

This does not argue about it: it runs the real thing and looks.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import text

from app.services.ml_group_metrics.compute import GroupMetrics
from app.services.ml_group_metrics.store import store_group_metrics
from app.services.order_metrics.constants import CURRENT_FORMULA_VERSION


@pytest.fixture()
def slate(pg_order_metrics_triggers_db):
    session = pg_order_metrics_triggers_db
    session.execute(text("DELETE FROM ml_group_metrics"))
    session.commit()
    yield session
    session.execute(text("DELETE FROM ml_group_metrics"))
    session.commit()


def _metrics(group_key: str, total_gauss="50.00") -> GroupMetrics:
    return GroupMetrics(
        group_key=group_key,
        neto=Decimal("100.00"),
        neto_sin_iva=Decimal("82.64"),
        costo_mercaderia=Decimal("30.00"),
        total_gauss=Decimal(total_gauss),
        markup_pct=Decimal("166.67"),
        gauss_status="ok",
        gross_amount=Decimal("1250.50"),
        currency_id="ARS",
        member_order_ids=[1, 2],
    )


@pytest.mark.postgres
class TestStoreGroupMetricsOnPostgres:
    def test_every_column_survives_the_insert(self, slate):
        """If `.values()` pinned the compiled INSERT to `member_order_ids`
        alone, the NOT NULL columns would be missing and this would raise."""
        store_group_metrics(slate, {"p:9500": _metrics("p:9500")})
        slate.commit()

        fila = slate.execute(
            text(
                "SELECT gauss_status, formula_version, computed_at, member_order_ids, "
                "total_gauss, gross_amount, currency_id "
                "FROM ml_group_metrics WHERE group_key = 'p:9500'"
            )
        ).one()
        assert fila.gauss_status == "ok"
        assert fila.formula_version == CURRENT_FORMULA_VERSION
        assert fila.computed_at is not None
        assert list(fila.member_order_ids) == [1, 2]
        assert fila.total_gauss == Decimal("50.00")
        assert fila.gross_amount == Decimal("1250.50")
        assert fila.currency_id == "ARS"

    def test_a_batch_of_several_groups_inserts_them_all(self, slate):
        """executemany is the shape the live path actually uses -- one call
        per drained batch, not one per group."""
        store_group_metrics(
            slate,
            {
                "p:9510": _metrics("p:9510", total_gauss="10.00"),
                "p:9511": _metrics("p:9511", total_gauss="20.00"),
                "o:9512": _metrics("o:9512", total_gauss="30.00"),
            },
        )
        slate.commit()

        total = slate.execute(text("SELECT COUNT(*) FROM ml_group_metrics")).scalar()
        assert total == 3

    def test_the_upsert_path_updates_instead_of_raising(self, slate):
        store_group_metrics(slate, {"p:9520": _metrics("p:9520", total_gauss="10.00")})
        slate.commit()
        store_group_metrics(slate, {"p:9520": _metrics("p:9520", total_gauss="99.00")})
        slate.commit()

        valor = slate.execute(text("SELECT total_gauss FROM ml_group_metrics WHERE group_key = 'p:9520'")).scalar()
        assert valor == Decimal("99.00")
