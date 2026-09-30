"""Los cuatro switches, contra Postgres y por el camino COMPLETO del endpoint.

POR QUÉ EXISTE ESTE ARCHIVO. `test_filters_switches.py` cubre los cuatro
toggles, pasa entero, y no habría cazado el 500 que producción reportó: corre
sobre SQLite y solo lee los `group_key` del scope. El endpoint hace algo más
— agrupa, ordena y pagina sobre esa misma query, ya joineada contra la
subquery de switches — y ahí es donde se cae.

Peor: hasta que el frontend empezó a mandar los toggles, este camino NUNCA
CORRIÓ en producción. `_apply_switches` arranca con

    if f.include_unknown and f.include_in_dispute and f.include_mixed
       and f.include_provisional:
        return query

y los defaults de la lista son los cuatro en True, así que ese `return` se
comía todo. Código inalcanzable no es código que funciona: es código que nadie
probó.
"""

from __future__ import annotations


import pytest
from sqlalchemy import func, text

from app.models.ml_orders_ops import MlOrdersOps
from app.services.ml_sales_query.filters import SalesFilter, build_scope


def _order(session, order_id: int, pack_id: int | None = None) -> None:
    session.execute(
        text(
            "INSERT INTO ml_orders_ops "
            "(order_id, seller_id, status, ml_last_updated, date_created, pack_id, "
            " total_amount, paid_amount, currency_id) "
            "VALUES (:oid, 999, 'paid', now(), now(), :pid, 100, 100, 'ARS')"
        ),
        {"oid": order_id, "pid": pack_id},
    )


@pytest.fixture()
def slate(pg_order_metrics_triggers_db, monkeypatch):
    from app.core.config import settings
    from app.models.ml_order_metrics import MlOrderMetrics
    from app.models.ml_orders_ops import MlOperationLink
    from app.models.rma_claim_ml import RmaClaimML

    monkeypatch.setattr(settings, "ML_USER_ID", "999", raising=False)
    session = pg_order_metrics_triggers_db
    # `pg_order_metrics_triggers_engine` creates `ml_order_metrics_dirty` but
    # NOT `ml_order_metrics`, and the switch subquery outer-joins the latter.
    # Created here rather than by widening the shared fixture: this module is
    # the only one that needs it, and touching a session-scoped engine's table
    # list affects every test that borrows it.
    for tabla in (MlOrderMetrics.__table__, MlOperationLink.__table__, RmaClaimML.__table__):
        tabla.create(session.get_bind(), checkfirst=True)
    session.execute(text("DELETE FROM ml_orders_ops WHERE seller_id = 999"))
    session.commit()
    yield session
    session.execute(text("DELETE FROM ml_orders_ops WHERE seller_id = 999"))
    session.commit()


def _key_page(db, scope):
    """The endpoint's paging query: group, sort, page — the part the SQLite
    tests never exercise.

    LIMITATION, stated rather than hidden: this MIRRORS `listar_ventas`'s query
    instead of calling it, so it proves the shape works on Postgres but would
    not catch the router drifting away from it. The right fix is to extract
    that block out of the endpoint so both run the same code; declared as a
    follow-up rather than done here by surgery on a 2000-line router."""
    group_key = scope.group_key
    return (
        scope.listing_query.with_entities(
            group_key.label("group_key"),
            func.min(MlOrdersOps.date_created).label("group_date"),
        )
        .group_by(group_key)
        .order_by(
            func.min(MlOrdersOps.date_created).desc().nullslast(),
            func.max(MlOrdersOps.order_id).desc(),
        )
        .limit(50)
        .offset(0)
        .all()
    )


@pytest.mark.postgres
class TestSwitchesThroughTheEndpointQuery:
    def test_all_switches_on_pages_fine(self, slate) -> None:
        """The path that DID run in production: `_apply_switches` returns the
        query untouched, so this is the control case, not the interesting one."""
        _order(slate, 900001)
        slate.commit()
        scope = build_scope(
            slate,
            SalesFilter(include_unknown=True, include_in_dispute=True, include_mixed=True, include_provisional=True),
        )
        assert [r.group_key for r in _key_page(slate, scope)] == ["o:900001"]

    @pytest.mark.parametrize(
        "apagado",
        ["include_unknown", "include_in_dispute", "include_mixed", "include_provisional"],
    )
    def test_one_switch_off_still_pages(self, slate, apagado: str) -> None:
        """Turning ANY switch off joins the switch subquery into the listing,
        and the endpoint then groups/sorts/pages over the result. Production
        answered 500 for every one of these."""
        _order(slate, 900010)
        slate.commit()
        kwargs = {
            "include_unknown": True,
            "include_in_dispute": True,
            "include_mixed": True,
            "include_provisional": True,
        }
        kwargs[apagado] = False
        scope = build_scope(slate, SalesFilter(**kwargs))
        _key_page(slate, scope)  # must not raise
