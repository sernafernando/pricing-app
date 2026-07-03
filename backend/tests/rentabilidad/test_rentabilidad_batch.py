"""
Integration tests for the batch-prefetch refactor of the 3 `rentabilidad_*`
dashboard endpoints (PR2 scope of `dashboard-batch-prefetch`, Task 4).

Covers:
- Spec Requirement 1: resumen-table query-count bound, independent of N.
  IMPORTANT (design.md §5.1): these endpoints also run per-group/per-offset
  `func.sum(...)` aggregate helpers that are OUT OF SCOPE and remain
  O(distinct-groups). We therefore assert ONLY the resumen-table query count
  via `query_counter.matching(...)`, never `counter.total`.
- Spec Requirement 2: byte-identical response for the same fixture (structural
  determinism pin — this test module is created after the refactor, so the
  "before" comparison is a same-request-twice determinism check, per
  design.md §5.5 caveat, not a literal pre/post-change diff).

All three endpoints (`/api/rentabilidad`, `/api/rentabilidad-tienda-nube`,
`/api/rentabilidad-fuera`) require only `fecha_desde`/`fecha_hasta` and
authentication (admin role avoids the marca/PM permission filter so the
resultado set is deterministic and independent of `MarcaPM` seeding).
"""

from __future__ import annotations

from datetime import date

import pytest

# `rentabilidad_fuera.py` queries `ventas_fuera_ml_metricas` via raw SQL and
# only imports `VentaFueraMLMetrica` lazily inside unrelated endpoint
# functions in `ventas_fuera_ml.py`, so the table is never registered on
# `Base.metadata` for the in-memory test DB unless something imports the
# model at collection time. Force that here so `Base.metadata.create_all`
# (session-scoped `engine` fixture) creates the table.
from app.models.venta_fuera_ml_metrica import VentaFueraMLMetrica  # noqa: F401
from app.models.venta_tienda_nube_metrica import VentaTiendaNubeMetrica  # noqa: F401


FECHA_DESDE = "2026-01-01"
FECHA_HASTA = "2026-01-31"

ENDPOINTS = [
    "/api/rentabilidad",
    "/api/rentabilidad-tienda-nube",
    "/api/rentabilidad-fuera",
]


def _seed_grupos_e_individuales(
    n,
    offset_grupo_factory,
    offset_ganancia_factory,
    offset_grupo_resumen_factory,
    offset_individual_resumen_factory,
):
    """Seed n distinct grupos (with resumen) and n distinct individual
    limited offsets (with resumen), all vigentes for the fixed date window."""
    for _ in range(n):
        g = offset_grupo_factory()
        offset_ganancia_factory(grupo_id=g.id, max_unidades=10, fecha_desde=date(2026, 1, 1))
        offset_grupo_resumen_factory(grupo_id=g.id, total_unidades=1)

        ind = offset_ganancia_factory(grupo_id=None, max_unidades=10, fecha_desde=date(2026, 1, 1))
        offset_individual_resumen_factory(offset_id=ind.id, total_unidades=1)


@pytest.mark.parametrize("endpoint", ENDPOINTS)
class TestRentabilidadResumenQueryCount:
    def test_resumen_query_count_is_flat_as_n_grows(
        self,
        endpoint,
        db,
        client,
        admin_auth_headers,
        query_counter,
        offset_grupo_factory,
        offset_ganancia_factory,
        offset_grupo_resumen_factory,
        offset_individual_resumen_factory,
    ):
        # N = 1 baseline
        _seed_grupos_e_individuales(
            1,
            offset_grupo_factory,
            offset_ganancia_factory,
            offset_grupo_resumen_factory,
            offset_individual_resumen_factory,
        )
        db.commit()

        with query_counter() as counter_n1:
            resp1 = client.get(
                endpoint,
                params={"fecha_desde": FECHA_DESDE, "fecha_hasta": FECHA_HASTA},
                headers=admin_auth_headers,
            )
        assert resp1.status_code == 200
        grupo_count_n1 = counter_n1.matching("offset_grupo_resumen")
        individual_count_n1 = counter_n1.matching("offset_individual_resumen")

        # Grow to N = 5 distinct groups/offsets
        _seed_grupos_e_individuales(
            4,
            offset_grupo_factory,
            offset_ganancia_factory,
            offset_grupo_resumen_factory,
            offset_individual_resumen_factory,
        )
        db.commit()

        with query_counter() as counter_n_many:
            resp2 = client.get(
                endpoint,
                params={"fecha_desde": FECHA_DESDE, "fecha_hasta": FECHA_HASTA},
                headers=admin_auth_headers,
            )
        assert resp2.status_code == 200
        grupo_count_n_many = counter_n_many.matching("offset_grupo_resumen")
        individual_count_n_many = counter_n_many.matching("offset_individual_resumen")

        # O(1): the resumen-table query count must stay EQUAL (flat), not
        # merely bounded, as N grows from 1 to 5 distinct groups/offsets.
        assert grupo_count_n_many == grupo_count_n1
        assert individual_count_n_many == individual_count_n1
        assert grupo_count_n1 <= 1
        assert individual_count_n1 <= 1

    def test_response_is_deterministic_for_same_fixture(
        self,
        endpoint,
        db,
        client,
        admin_auth_headers,
        offset_grupo_factory,
        offset_ganancia_factory,
        offset_grupo_resumen_factory,
        offset_individual_resumen_factory,
    ):
        _seed_grupos_e_individuales(
            3,
            offset_grupo_factory,
            offset_ganancia_factory,
            offset_grupo_resumen_factory,
            offset_individual_resumen_factory,
        )
        db.commit()

        params = {"fecha_desde": FECHA_DESDE, "fecha_hasta": FECHA_HASTA}
        resp_a = client.get(endpoint, params=params, headers=admin_auth_headers)
        resp_b = client.get(endpoint, params=params, headers=admin_auth_headers)

        assert resp_a.status_code == 200
        assert resp_b.status_code == 200
        assert resp_a.json() == resp_b.json()
