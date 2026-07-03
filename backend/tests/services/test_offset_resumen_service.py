"""
Unit tests for `app.services.offset_resumen_service`.

Strict TDD — written BEFORE the module exists. The genuine RED gate is the
import error below (module absent), not any SQLite ordering incidental pass.

Covers Spec Requirement 3 (deterministic tie-break) and Requirement 4
(shared helper contract).
"""

from __future__ import annotations

from app.services.offset_resumen_service import (
    fetch_offsets_limite_por_grupo,
    fetch_resumenes_grupo,
    fetch_resumenes_individuales,
)


class TestFetchResumenesGrupo:
    def test_empty_input_returns_empty_dict_without_querying(self, db, query_counter):
        with query_counter() as counter:
            result = fetch_resumenes_grupo(db, [])
        assert result == {}
        assert counter.total == 0

    def test_dict_keyed_by_grupo_id_for_present_rows(self, db, offset_grupo_factory, offset_grupo_resumen_factory):
        g1 = offset_grupo_factory()
        g2 = offset_grupo_factory()
        r1 = offset_grupo_resumen_factory(grupo_id=g1.id, total_unidades=5)
        r2 = offset_grupo_resumen_factory(grupo_id=g2.id, total_unidades=7)

        result = fetch_resumenes_grupo(db, [g1.id, g2.id])

        assert result[g1.id].id == r1.id
        assert result[g2.id].id == r2.id

    def test_missing_id_absent_not_none(self, db, offset_grupo_factory, offset_grupo_resumen_factory):
        g1 = offset_grupo_factory()
        g2 = offset_grupo_factory()  # no resumen
        offset_grupo_resumen_factory(grupo_id=g1.id)

        result = fetch_resumenes_grupo(db, [g1.id, g2.id])

        assert g1.id in result
        assert g2.id not in result


class TestFetchResumenesIndividuales:
    def test_empty_input_returns_empty_dict_without_querying(self, db, query_counter):
        with query_counter() as counter:
            result = fetch_resumenes_individuales(db, [])
        assert result == {}
        assert counter.total == 0

    def test_dict_keyed_by_offset_id_for_present_rows(
        self, db, offset_ganancia_factory, offset_individual_resumen_factory
    ):
        o1 = offset_ganancia_factory()
        o2 = offset_ganancia_factory()
        r1 = offset_individual_resumen_factory(offset_id=o1.id, total_unidades=3)
        r2 = offset_individual_resumen_factory(offset_id=o2.id, total_unidades=9)

        result = fetch_resumenes_individuales(db, [o1.id, o2.id])

        assert result[o1.id].id == r1.id
        assert result[o2.id].id == r2.id

    def test_missing_id_absent_not_none(self, db, offset_ganancia_factory, offset_individual_resumen_factory):
        o1 = offset_ganancia_factory()
        o2 = offset_ganancia_factory()  # no resumen
        offset_individual_resumen_factory(offset_id=o1.id)

        result = fetch_resumenes_individuales(db, [o1.id, o2.id])

        assert o1.id in result
        assert o2.id not in result


class TestFetchOffsetsLimitePorGrupo:
    def test_empty_input_returns_empty_dict_without_querying(self, db, query_counter):
        with query_counter() as counter:
            result = fetch_offsets_limite_por_grupo(db, [])
        assert result == {}
        assert counter.total == 0

    def test_single_matching_row_per_group_is_returned(self, db, offset_grupo_factory, offset_ganancia_factory):
        g1 = offset_grupo_factory()
        o1 = offset_ganancia_factory(grupo_id=g1.id, max_unidades=50)

        result = fetch_offsets_limite_por_grupo(db, [g1.id])

        assert result[g1.id].id == o1.id
        assert result[g1.id].max_unidades == 50

    def test_tie_break_selects_lowest_id_row(self, db, offset_grupo_factory, offset_ganancia_factory, query_counter):
        """Spec Requirement 3: two OffsetGanancia rows in the same grupo — the
        lowest-id row wins, regardless of DB row-return order.

        NOTE on why this test also pins the ORDER BY clause directly: on
        SQLite, `offsets_ganancia.id` is an INTEGER PRIMARY KEY, which SQLite
        aliases to the table's internal rowid. A plain (unindexed) table scan
        over such a table is returned in rowid order — i.e. id-ascending —
        REGARDLESS of insertion order or ORDER BY. That means no amount of
        fixture data reordering can make SQLite return this query's rows out
        of id order, so a purely data-driven tie-break assertion cannot
        falsify a removed `.order_by(...)` on this backend. The only backend-
        independent way to prove the ORDER BY clause is actually present (and
        therefore that the tie-break is a genuine, engineered guarantee, not
        an artifact of SQLite's scan order) is to inspect the emitted SQL
        text via `query_counter` and assert the ORDER BY clause is there.
        """
        g1 = offset_grupo_factory()
        low = offset_ganancia_factory(grupo_id=g1.id, max_unidades=100)  # created first -> lower id
        offset_ganancia_factory(grupo_id=g1.id, max_unidades=999)  # created second -> higher id

        with query_counter() as counter:
            result = fetch_offsets_limite_por_grupo(db, [g1.id])

        assert result[g1.id].id == low.id
        assert result[g1.id].max_unidades == 100
        assert any("offsets_ganancia" in s and "order by" in s and "grupo_id" in s for s in counter.statements), (
            f"expected an ORDER BY clause on offsets_ganancia.grupo_id, got: {counter.statements}"
        )

    def test_no_matching_rows_absent_from_dict(self, db, offset_grupo_factory):
        g1 = offset_grupo_factory()  # no offsets at all

        result = fetch_offsets_limite_por_grupo(db, [g1.id])

        assert g1.id not in result
