"""prefetch_criterios: one IN SELECT for many MLAs (pool-exhaustion invariant)."""

from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import event

from app.models.ml_hay_mejores_criterios import MlHayMejoresCriterios
from app.services.ml_hay_mejores_criterios_service import get_criterios, prefetch_criterios


@contextmanager
def _count_selects(db):
    counts = {"SELECT": 0}

    def _before(conn, cursor, statement, params, context, executemany):
        if "SELECT" in statement:
            counts["SELECT"] += 1

    engine = db.get_bind()
    event.listen(engine, "before_cursor_execute", _before)
    try:
        yield counts
    finally:
        event.remove(engine, "before_cursor_execute", _before)


class TestPrefetchCriterios:
    def test_one_select_for_many_mlas_then_cache_hits(self, db) -> None:
        db.add(MlHayMejoresCriterios(item_id="MLA1", c1_activo=True))
        db.commit()
        mlas = [f"MLA{n}" for n in range(1, 11)]

        with _count_selects(db) as counts:
            prefetch_criterios(db, mlas)
        assert counts["SELECT"] == 1

        with _count_selects(db) as counts:
            for mla in mlas:
                get_criterios(db, mla)
        assert counts["SELECT"] == 0
        assert get_criterios(db, "MLA1").c1_activo is True
        assert get_criterios(db, "MLA2").exists is False
