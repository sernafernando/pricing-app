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


# ---------------------------------------------------------------------------
# /api/offset-grupos-resumen  (_consumo_grupos.py::obtener_resumen_grupos)
# ---------------------------------------------------------------------------


class TestConsumoGruposQueryCount:
    def _seed_and_count(
        self,
        n_new_grupos,
        expected_total,
        db,
        client,
        auth_headers,
        query_counter,
        offset_grupo_factory,
        offset_ganancia_factory,
        offset_grupo_resumen_factory,
    ):
        for _ in range(n_new_grupos):
            g = offset_grupo_factory()
            offset_ganancia_factory(grupo_id=g.id, max_unidades=10)
            offset_grupo_resumen_factory(grupo_id=g.id, total_unidades=1)

        with query_counter() as counter:
            resp = client.get("/api/offset-grupos-resumen", headers=auth_headers)

        assert resp.status_code == 200
        assert len(resp.json()) == expected_total
        return counter

    def test_resumen_query_count_is_flat_as_n_grows(
        self,
        db,
        client,
        auth_headers,
        query_counter,
        offset_grupo_factory,
        offset_ganancia_factory,
        offset_grupo_resumen_factory,
    ):
        """Load-bearing assertion for Spec Requirement 1 (O(1) query count):
        the resumen-table and offsets_ganancia query counts observed at N=1
        must be EXACTLY EQUAL to the counts observed at N=5 — not just
        individually bounded by some constant, which would also pass for an
        N+1 pattern as long as N stayed under the bound. Equality across N is
        what actually proves the count does not grow with N."""
        counter_n1 = self._seed_and_count(
            1,
            1,
            db,
            client,
            auth_headers,
            query_counter,
            offset_grupo_factory,
            offset_ganancia_factory,
            offset_grupo_resumen_factory,
        )
        n1_resumen = counter_n1.matching("offset_grupo_resumen")
        n1_offsets = counter_n1.matching("offsets_ganancia")

        # Seed up to N=5 total groups within the SAME test (same transaction)
        # so the two counts are directly comparable.
        counter_n5 = self._seed_and_count(
            4,
            5,
            db,
            client,
            auth_headers,
            query_counter,
            offset_grupo_factory,
            offset_ganancia_factory,
            offset_grupo_resumen_factory,
        )
        n5_resumen = counter_n5.matching("offset_grupo_resumen")
        n5_offsets = counter_n5.matching("offsets_ganancia")

        assert n5_resumen == n1_resumen, (
            f"offset_grupo_resumen query count grew with N: N=1 -> {n1_resumen}, N=5 -> {n5_resumen}"
        )
        assert n5_offsets == n1_offsets, (
            f"offsets_ganancia query count grew with N: N=1 -> {n1_offsets}, N=5 -> {n5_offsets}"
        )
        # Sanity upper bound, kept for documentation: C=2 for offsets_ganancia
        # is the initial `grupos_con_limites` join (unrelated to this
        # refactor, out of scope) + the ONE batched
        # `fetch_offsets_limite_por_grupo` call.
        assert n1_offsets <= 2
        assert n1_resumen <= 1


class TestConsumoGruposTieBreak:
    def test_tie_break_uses_lowest_id_offset(
        self,
        db,
        client,
        auth_headers,
        query_counter,
        offset_grupo_factory,
        offset_ganancia_factory,
        offset_grupo_resumen_factory,
    ):
        """Behavior pin (design.md §4).

        NOTE: on SQLite, `offsets_ganancia.id` is an INTEGER PRIMARY KEY
        (rowid alias), so unindexed scans naturally return rows in id-
        ascending order regardless of insertion order or ORDER BY — a purely
        data-driven fixture cannot falsify a removed `.order_by(...)` on this
        backend (see the unit test in
        tests/services/test_offset_resumen_service.py for the detailed
        rationale). This test additionally inspects the emitted SQL via
        `query_counter` and asserts the ORDER BY clause is present, which
        DOES fail if `.order_by(...)` is removed from
        `fetch_offsets_limite_por_grupo`."""
        g = offset_grupo_factory()
        offset_ganancia_factory(grupo_id=g.id, max_unidades=100)  # lower id
        offset_ganancia_factory(grupo_id=g.id, max_unidades=999)  # higher id
        offset_grupo_resumen_factory(grupo_id=g.id, total_unidades=1)

        with query_counter() as counter:
            resp = client.get("/api/offset-grupos-resumen", headers=auth_headers)

        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        assert body[0]["max_unidades"] == 100
        assert any("offsets_ganancia" in s and "order by" in s and "grupo_id" in s for s in counter.statements), (
            f"expected an ORDER BY clause on offsets_ganancia.grupo_id, got: {counter.statements}"
        )


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

        # Full structural pin (Spec Requirement 2): the ENTIRE dict for each
        # row is asserted, not just a hand-picked subset of fields. Any
        # added/removed/renamed key or changed value/type fails this test.
        expected_con = {
            "grupo_id": g_con_resumen.id,
            "grupo_nombre": "Con Resumen",
            "total_unidades": 10,
            "total_monto_ars": 1000.0,
            "total_monto_usd": 1.0,
            "cantidad_ventas": 2,
            "limite_alcanzado": None,
            "fecha_limite_alcanzado": None,
            "max_unidades": 50,
            "max_monto_usd": None,
            "porcentaje_consumido_unidades": 20.0,
            "porcentaje_consumido_monto": None,
        }
        expected_sin = {
            "grupo_id": g_sin_resumen.id,
            "grupo_nombre": "Sin Resumen",
            "total_unidades": 0,
            "total_monto_ars": 0,
            "total_monto_usd": 0,
            "cantidad_ventas": 0,
            "limite_alcanzado": None,
            "fecha_limite_alcanzado": None,
            "max_unidades": None,
            "max_monto_usd": 25.0,
            "porcentaje_consumido_unidades": None,
            "porcentaje_consumido_monto": 0,
        }
        assert by_id[g_con_resumen.id] == expected_con
        assert by_id[g_sin_resumen.id] == expected_sin


# ---------------------------------------------------------------------------
# /api/offsets-con-limites-resumen
# (_consumo_individual.py::obtener_resumen_todos_offsets_con_limites)
# ---------------------------------------------------------------------------


class TestConsumoIndividualQueryCount:
    def _seed_and_count(
        self,
        n_new,
        expected_total,
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
        for _ in range(n_new):
            g = offset_grupo_factory()
            offset_ganancia_factory(grupo_id=g.id, max_unidades=10)
            offset_grupo_resumen_factory(grupo_id=g.id, total_unidades=1)

        # offsets individuales con límites (site: OffsetIndividualResumen)
        for _ in range(n_new):
            o = offset_ganancia_factory(grupo_id=None, max_unidades=5)
            offset_individual_resumen_factory(offset_id=o.id, total_unidades=1)

        with query_counter() as counter:
            resp = client.get("/api/offsets-con-limites-resumen", headers=auth_headers)

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["grupos"]) == expected_total
        assert len(body["individuales"]) == expected_total
        return counter

    def test_resumen_query_count_is_flat_as_n_grows(
        self,
        db,
        client,
        auth_headers,
        query_counter,
        offset_grupo_factory,
        offset_ganancia_factory,
        offset_grupo_resumen_factory,
        offset_individual_resumen_factory,
    ):
        """Load-bearing assertion for Spec Requirement 1 (O(1) query count):
        the resumen-table and offsets_ganancia query counts observed at N=1
        must be EXACTLY EQUAL to the counts observed at N=5 (see rationale in
        TestConsumoGruposQueryCount)."""
        counter_n1 = self._seed_and_count(
            1,
            1,
            db,
            client,
            auth_headers,
            query_counter,
            offset_grupo_factory,
            offset_ganancia_factory,
            offset_grupo_resumen_factory,
            offset_individual_resumen_factory,
        )
        n1_resumen_grupo = counter_n1.matching("offset_grupo_resumen")
        n1_resumen_individual = counter_n1.matching("offset_individual_resumen")
        n1_offsets = counter_n1.matching("offsets_ganancia")

        counter_n5 = self._seed_and_count(
            4,
            5,
            db,
            client,
            auth_headers,
            query_counter,
            offset_grupo_factory,
            offset_ganancia_factory,
            offset_grupo_resumen_factory,
            offset_individual_resumen_factory,
        )
        n5_resumen_grupo = counter_n5.matching("offset_grupo_resumen")
        n5_resumen_individual = counter_n5.matching("offset_individual_resumen")
        n5_offsets = counter_n5.matching("offsets_ganancia")

        assert n5_resumen_grupo == n1_resumen_grupo, (
            f"offset_grupo_resumen query count grew with N: N=1 -> {n1_resumen_grupo}, N=5 -> {n5_resumen_grupo}"
        )
        assert n5_resumen_individual == n1_resumen_individual, (
            f"offset_individual_resumen query count grew with N: "
            f"N=1 -> {n1_resumen_individual}, N=5 -> {n5_resumen_individual}"
        )
        assert n5_offsets == n1_offsets, (
            f"offsets_ganancia query count grew with N: N=1 -> {n1_offsets}, N=5 -> {n5_offsets}"
        )
        # Sanity upper bound, kept for documentation: C=3 for offsets_ganancia
        # is `grupos_con_limites` join + ONE batched
        # `fetch_offsets_limite_por_grupo` (site 9) + the `offsets_individuales`
        # query (site 10's key source, unrelated to this refactor).
        assert n1_offsets <= 3
        assert n1_resumen_grupo <= 1
        assert n1_resumen_individual <= 1


class TestConsumoIndividualTieBreak:
    def test_tie_break_uses_lowest_id_offset_for_grupo_limite(
        self,
        db,
        client,
        auth_headers,
        query_counter,
        offset_grupo_factory,
        offset_ganancia_factory,
        offset_grupo_resumen_factory,
    ):
        """Behavior pin — see rationale in
        tests/services/test_offset_resumen_service.py::test_tie_break_selects_lowest_id_row
        for why the SQL-inspection assertion (not fixture ordering) is the
        genuine falsifiable gate for the ORDER BY clause on SQLite."""
        g = offset_grupo_factory()
        offset_ganancia_factory(grupo_id=g.id, max_unidades=100)  # lower id
        offset_ganancia_factory(grupo_id=g.id, max_unidades=999)  # higher id
        offset_grupo_resumen_factory(grupo_id=g.id, total_unidades=1)

        with query_counter() as counter:
            resp = client.get("/api/offsets-con-limites-resumen", headers=auth_headers)

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["grupos"]) == 1
        assert body["grupos"][0]["max_unidades"] == 100
        assert any("offsets_ganancia" in s and "order by" in s and "grupo_id" in s for s in counter.statements), (
            f"expected an ORDER BY clause on offsets_ganancia.grupo_id, got: {counter.statements}"
        )


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

        # Full structural pin (Spec Requirement 2): compare the ENTIRE
        # response dict (all top-level keys + nested list-item dicts) against
        # an inline expected literal, not a hand-picked subset of fields.
        grupos_by_id = {g["id"]: g for g in body["grupos"]}
        individuales_by_id = {o["id"]: o for o in body["individuales"]}

        expected_grupo_con = {
            "tipo": "grupo",
            "id": g_con_resumen.id,
            "nombre": "G1",
            "total_unidades": 10,
            "total_monto_usd": 0,
            "max_unidades": 50,
            "max_monto_usd": None,
            "limite_alcanzado": "unidades",
        }
        expected_grupo_sin = {
            "tipo": "grupo",
            "id": g_sin_resumen.id,
            "nombre": "G2",
            "total_unidades": 0,
            "total_monto_usd": 0,
            "max_unidades": 30,
            "max_monto_usd": None,
            "limite_alcanzado": None,
        }
        expected_individual_con = {
            "tipo": "individual",
            "id": o_con_resumen.id,
            "descripcion": None,
            "nivel": "subcategoria",
            "total_unidades": 5,
            "total_monto_usd": 0,
            "max_unidades": 20,
            "max_monto_usd": None,
            "limite_alcanzado": None,
        }
        expected_individual_sin = {
            "tipo": "individual",
            "id": o_sin_resumen.id,
            "descripcion": None,
            "nivel": "subcategoria",
            "total_unidades": 0,
            "total_monto_usd": 0,
            "max_unidades": 15,
            "max_monto_usd": None,
            "limite_alcanzado": None,
        }
        expected_totales = {
            "total_grupos": 2,
            "total_individuales": 2,
            "grupos_con_limite_alcanzado": 1,
            "individuales_con_limite_alcanzado": 0,
        }

        assert grupos_by_id[g_con_resumen.id] == expected_grupo_con
        assert grupos_by_id[g_sin_resumen.id] == expected_grupo_sin
        assert individuales_by_id[o_con_resumen.id] == expected_individual_con
        assert individuales_by_id[o_sin_resumen.id] == expected_individual_sin
        assert body["totales"] == expected_totales
        assert set(body.keys()) == {"grupos", "individuales", "totales"}
