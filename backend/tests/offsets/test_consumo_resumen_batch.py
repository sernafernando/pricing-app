"""
Integration tests for the batch-prefetch refactor of the `_consumo_*` offset
resumen endpoints (PR1 scope of `dashboard-batch-prefetch`).

Covers:
- Spec Requirement 1: resumen/offset query-count bound, independent of N.
- Spec Requirement 2: byte-identical response before/after the refactor
  (verified structurally here, since this test module only exists after
  the refactor — see design.md §5.5 for the baseline-capture note).
- Spec Requirement 3: deterministic tie-break for `offset_con_limite` /
  `offset_limite` (lowest-id wins).

Both endpoints require only authentication (no extra permission), per
`app/api/endpoints/offsets_ganancia/_consumo_grupos.py` and
`_consumo_individual.py`.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# /api/offset-grupos-resumen  (_consumo_grupos.py::obtener_resumen_grupos)
# ---------------------------------------------------------------------------


class TestConsumoGruposQueryCount:
    @pytest.mark.parametrize("n_grupos", [1, 5])
    def test_resumen_query_count_bounded_independent_of_n(
        self,
        n_grupos,
        db,
        client,
        auth_headers,
        query_counter,
        offset_grupo_factory,
        offset_ganancia_factory,
        offset_grupo_resumen_factory,
    ):
        for _ in range(n_grupos):
            g = offset_grupo_factory()
            offset_ganancia_factory(grupo_id=g.id, max_unidades=10)
            offset_grupo_resumen_factory(grupo_id=g.id, total_unidades=1)

        with query_counter() as counter:
            resp = client.get("/api/offset-grupos-resumen", headers=auth_headers)

        assert resp.status_code == 200
        assert len(resp.json()) == n_grupos
        assert counter.matching("offset_grupo_resumen") <= 1
        # C=2 for offsets_ganancia: the initial `grupos_con_limites` join
        # (unrelated to this refactor, out of scope) + the ONE batched
        # `fetch_offsets_limite_por_grupo` call. Bounded, independent of N.
        assert counter.matching("offsets_ganancia") <= 2


class TestConsumoGruposTieBreak:
    def test_tie_break_uses_lowest_id_offset(
        self,
        db,
        client,
        auth_headers,
        offset_grupo_factory,
        offset_ganancia_factory,
        offset_grupo_resumen_factory,
    ):
        """Behavior pin (design.md §4): may pass incidentally on SQLite — the
        genuine RED gate for the tie-break is the unit test in
        tests/services/test_offset_resumen_service.py."""
        g = offset_grupo_factory()
        offset_ganancia_factory(grupo_id=g.id, max_unidades=100)  # lower id
        offset_ganancia_factory(grupo_id=g.id, max_unidades=999)  # higher id
        offset_grupo_resumen_factory(grupo_id=g.id, total_unidades=1)

        resp = client.get("/api/offset-grupos-resumen", headers=auth_headers)

        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        assert body[0]["max_unidades"] == 100


class TestConsumoGruposByteIdentical:
    def test_response_matches_expected_structure_for_mixed_fixture(
        self,
        db,
        client,
        auth_headers,
        offset_grupo_factory,
        offset_ganancia_factory,
        offset_grupo_resumen_factory,
    ):
        """One grupo has a resumen row, one does not (missing/None case) —
        Spec Requirement 2 byte-identical guarantee (same key order/values)."""
        g_con_resumen = offset_grupo_factory(nombre="Con Resumen")
        offset_ganancia_factory(grupo_id=g_con_resumen.id, max_unidades=50, max_monto_usd=None)
        offset_grupo_resumen_factory(
            grupo_id=g_con_resumen.id,
            total_unidades=10,
            total_monto_ars=1000,
            total_monto_usd=1.0,
            cantidad_ventas=2,
            limite_alcanzado=None,
        )

        g_sin_resumen = offset_grupo_factory(nombre="Sin Resumen")
        offset_ganancia_factory(grupo_id=g_sin_resumen.id, max_unidades=None, max_monto_usd=25.0)

        resp = client.get("/api/offset-grupos-resumen", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 2

        by_id = {row["grupo_id"]: row for row in body}

        con = by_id[g_con_resumen.id]
        assert con["grupo_nombre"] == "Con Resumen"
        assert con["total_unidades"] == 10
        assert con["max_unidades"] == 50
        assert con["max_monto_usd"] is None
        assert con["porcentaje_consumido_unidades"] == 20.0
        assert con["porcentaje_consumido_monto"] is None

        sin = by_id[g_sin_resumen.id]
        assert sin["grupo_nombre"] == "Sin Resumen"
        assert sin["total_unidades"] == 0
        assert sin["max_unidades"] is None
        assert sin["max_monto_usd"] == 25.0
        assert sin["porcentaje_consumido_unidades"] is None
        assert sin["porcentaje_consumido_monto"] == 0


# ---------------------------------------------------------------------------
# /api/offsets-con-limites-resumen
# (_consumo_individual.py::obtener_resumen_todos_offsets_con_limites)
# ---------------------------------------------------------------------------


class TestConsumoIndividualQueryCount:
    @pytest.mark.parametrize("n", [1, 5])
    def test_resumen_query_count_bounded_independent_of_n(
        self,
        n,
        db,
        client,
        auth_headers,
        query_counter,
        offset_grupo_factory,
        offset_ganancia_factory,
        offset_grupo_resumen_factory,
        offset_individual_resumen_factory,
    ):
        # grupos con límites (site: OffsetGrupoResumen + offset_limite tie-break)
        for _ in range(n):
            g = offset_grupo_factory()
            offset_ganancia_factory(grupo_id=g.id, max_unidades=10)
            offset_grupo_resumen_factory(grupo_id=g.id, total_unidades=1)

        # offsets individuales con límites (site: OffsetIndividualResumen)
        individuales = []
        for _ in range(n):
            o = offset_ganancia_factory(grupo_id=None, max_unidades=5)
            individuales.append(o)
            offset_individual_resumen_factory(offset_id=o.id, total_unidades=1)

        with query_counter() as counter:
            resp = client.get("/api/offsets-con-limites-resumen", headers=auth_headers)

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["grupos"]) == n
        assert len(body["individuales"]) == n
        assert counter.matching("offset_grupo_resumen") <= 1
        assert counter.matching("offset_individual_resumen") <= 1
        # C=3 for offsets_ganancia: `grupos_con_limites` join + ONE batched
        # `fetch_offsets_limite_por_grupo` (site 9) + the `offsets_individuales`
        # query (site 10's key source, unrelated to this refactor). Bounded,
        # independent of N.
        assert counter.matching("offsets_ganancia") <= 3


class TestConsumoIndividualTieBreak:
    def test_tie_break_uses_lowest_id_offset_for_grupo_limite(
        self,
        db,
        client,
        auth_headers,
        offset_grupo_factory,
        offset_ganancia_factory,
        offset_grupo_resumen_factory,
    ):
        """Behavior pin — genuine RED gate is the unit test on
        fetch_offsets_limite_por_grupo."""
        g = offset_grupo_factory()
        offset_ganancia_factory(grupo_id=g.id, max_unidades=100)  # lower id
        offset_ganancia_factory(grupo_id=g.id, max_unidades=999)  # higher id
        offset_grupo_resumen_factory(grupo_id=g.id, total_unidades=1)

        resp = client.get("/api/offsets-con-limites-resumen", headers=auth_headers)

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["grupos"]) == 1
        assert body["grupos"][0]["max_unidades"] == 100


class TestConsumoIndividualByteIdentical:
    def test_response_matches_expected_structure_for_mixed_fixture(
        self,
        db,
        client,
        auth_headers,
        offset_grupo_factory,
        offset_ganancia_factory,
        offset_grupo_resumen_factory,
        offset_individual_resumen_factory,
    ):
        g_con_resumen = offset_grupo_factory(nombre="G1")
        offset_ganancia_factory(grupo_id=g_con_resumen.id, max_unidades=50)
        offset_grupo_resumen_factory(grupo_id=g_con_resumen.id, total_unidades=10, limite_alcanzado="unidades")

        g_sin_resumen = offset_grupo_factory(nombre="G2")
        offset_ganancia_factory(grupo_id=g_sin_resumen.id, max_unidades=30)

        o_con_resumen = offset_ganancia_factory(grupo_id=None, max_unidades=20)
        offset_individual_resumen_factory(offset_id=o_con_resumen.id, total_unidades=5)

        o_sin_resumen = offset_ganancia_factory(grupo_id=None, max_unidades=15)

        resp = client.get("/api/offsets-con-limites-resumen", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()

        grupos_by_id = {g["id"]: g for g in body["grupos"]}
        assert grupos_by_id[g_con_resumen.id]["total_unidades"] == 10
        assert grupos_by_id[g_con_resumen.id]["limite_alcanzado"] == "unidades"
        assert grupos_by_id[g_sin_resumen.id]["total_unidades"] == 0
        assert grupos_by_id[g_sin_resumen.id]["limite_alcanzado"] is None

        individuales_by_id = {o["id"]: o for o in body["individuales"]}
        assert individuales_by_id[o_con_resumen.id]["total_unidades"] == 5
        assert individuales_by_id[o_sin_resumen.id]["total_unidades"] == 0

        assert body["totales"]["total_grupos"] == 2
        assert body["totales"]["total_individuales"] == 2
        assert body["totales"]["grupos_con_limite_alcanzado"] == 1
        assert body["totales"]["individuales_con_limite_alcanzado"] == 0
