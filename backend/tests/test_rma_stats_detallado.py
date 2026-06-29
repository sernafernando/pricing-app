"""
Strict TDD tests for:
  GET /rma-seguimiento/stats/detallado   (T-3 through T-10 RED → T-13 GREEN)
  GET /rma-seguimiento/stats/drill-down  (T-14 through T-17 RED → T-19 GREEN)

All tests are written BEFORE the implementation (RED phase).
Tests fail until T-13 (detallado) and T-19 (drill-down) are implemented.
"""

from datetime import date, datetime, UTC

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.core.database import get_db
from app.main import app

# ---------------------------------------------------------------------------
# Client fixtures
# ---------------------------------------------------------------------------

BASE_URL = "/api/rma-seguimiento"
DETALLADO_URL = f"{BASE_URL}/stats/detallado"
DRILLDOWN_URL = f"{BASE_URL}/stats/drill-down"

# Date range used in most tests: January 2026
DATE_FROM = "2026-01-01"
DATE_TO = "2026-01-31"


@pytest.fixture()
def client_rma_ver(db, rma_superadmin_user):
    """TestClient where the current user IS a superadmin (has rma.ver via es_superadmin)."""

    def _override_get_db():
        yield db

    def _override_get_current_user():
        return rma_superadmin_user

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = _override_get_current_user

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c

    app.dependency_overrides.clear()


@pytest.fixture()
def client_no_ver(db, rma_no_ver_user):
    """TestClient where the current user does NOT have rma.ver."""

    def _override_get_db():
        yield db

    def _override_get_current_user():
        return rma_no_ver_user

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = _override_get_current_user

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _detallado(client, **params) -> dict:
    """Call GET /stats/detallado with the given params and return parsed JSON."""
    defaults = {"date_from": DATE_FROM, "date_to": DATE_TO}
    defaults.update(params)
    resp = client.get(DETALLADO_URL, params=defaults)
    return resp


def _drilldown(client, **params) -> dict:
    """Call GET /stats/drill-down with the given params and return response."""
    defaults = {"date_from": DATE_FROM, "date_to": DATE_TO}
    defaults.update(params)
    return client.get(DRILLDOWN_URL, params=defaults)


# ---------------------------------------------------------------------------
# T-3: 403 without rma.ver — detallado
# ---------------------------------------------------------------------------


class TestDetalladoPermission:
    def test_detallado_requires_rma_ver_403(self, client_no_ver):
        """T-3 (RED→GREEN via T-13): user without rma.ver receives HTTP 403."""
        resp = _detallado(client_no_ver)
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# T-4: Soft-delete exclusion
# ---------------------------------------------------------------------------


class TestDetalladoSoftDelete:
    def test_detallado_excludes_soft_deleted(
        self,
        client_rma_ver,
        rma_caso_factory,
        rma_item_factory,
        rma_opcion_factory,
    ):
        """T-4 (RED→GREEN via T-13): items in activo=False casos are excluded."""
        fecha = date(2026, 1, 15)

        # 40 items in ACTIVE casos
        for i in range(4):
            caso = rma_caso_factory(activo=True, fecha_caso=fecha)
            for _ in range(10):
                rma_item_factory(caso_id=caso.id)

        # 10 items in SOFT-DELETED casos
        for _ in range(2):
            caso = rma_caso_factory(activo=False, fecha_caso=fecha)
            for _ in range(5):
                rma_item_factory(caso_id=caso.id)

        resp = _detallado(client_rma_ver)
        assert resp.status_code == 200
        data = resp.json()
        assert data["totales"]["items"] == 40

        # Verify no inactive items appear in any dimension bucket
        for dim_name, dim in data["dimensiones"].items():
            total_in_dim = sum(b["cantidad"] for b in dim["buckets"])
            assert total_in_dim == 40, f"Dimension {dim_name} total {total_in_dim} != 40"


# ---------------------------------------------------------------------------
# T-5: NULL bucket completeness (LEFT JOIN with categoria in ON clause)
# ---------------------------------------------------------------------------


class TestDetalladoNullBucket:
    def test_detallado_null_bucket_completeness(
        self,
        client_rma_ver,
        rma_caso_factory,
        rma_item_factory,
        rma_opcion_factory,
    ):
        """T-5 (RED→GREEN via T-12/T-13): items with NULL estado_recepcion_id appear as 'Sin clasificar'.

        CRITICAL: categoria predicate MUST be in the LEFT JOIN ON clause, NOT in WHERE.
        If it were in WHERE, NULL rows would be dropped (inner join degradation),
        and this test would fail with suma!=50.
        """
        fecha = date(2026, 1, 15)
        opc = rma_opcion_factory("estado_recepcion", "Recibido OK", orden=1, color="green")
        caso = rma_caso_factory(activo=True, fecha_caso=fecha)

        # 42 items WITH estado_recepcion_id set
        for _ in range(42):
            rma_item_factory(caso_id=caso.id, estado_recepcion_id=opc.id)

        # 8 items with NULL estado_recepcion_id
        for _ in range(8):
            rma_item_factory(caso_id=caso.id, estado_recepcion_id=None)

        resp = _detallado(client_rma_ver)
        assert resp.status_code == 200
        data = resp.json()

        dim = data["dimensiones"]["estado_recepcion"]
        buckets = dim["buckets"]

        # Must have a "Sin clasificar" bucket with cantidad == 8
        sin_clasificar = [b for b in buckets if b["id"] is None and b["valor"] == "Sin clasificar"]
        assert len(sin_clasificar) == 1, f"Expected 1 'Sin clasificar' bucket, got {sin_clasificar}"
        assert sin_clasificar[0]["cantidad"] == 8

        # Completeness invariant: sum of ALL buckets == totales.items == 50
        total_items = data["totales"]["items"]
        assert total_items == 50
        dim_total = sum(b["cantidad"] for b in buckets)
        assert dim_total == total_items, f"Dimension total {dim_total} != totales.items {total_items}"


# ---------------------------------------------------------------------------
# T-6: Happy path — per-dimension item counts correct
# ---------------------------------------------------------------------------


class TestDetalladoHappyPath:
    def test_detallado_item_counts_happy_path(
        self,
        client_rma_ver,
        rma_caso_factory,
        rma_item_factory,
        rma_opcion_factory,
    ):
        """T-6 (RED→GREEN via T-13): bucket counts match pre-computed expected values."""
        fecha = date(2026, 1, 15)

        # Create two estado_recepcion options
        opc_ok = rma_opcion_factory("estado_recepcion", "Recibido OK", orden=1, color="green")
        opc_dan = rma_opcion_factory("estado_recepcion", "Dañado", orden=2, color="red")

        caso = rma_caso_factory(activo=True, fecha_caso=fecha)

        # 30 "Recibido OK", 15 "Dañado", 5 NULL
        for _ in range(30):
            rma_item_factory(caso_id=caso.id, estado_recepcion_id=opc_ok.id)
        for _ in range(15):
            rma_item_factory(caso_id=caso.id, estado_recepcion_id=opc_dan.id)
        for _ in range(5):
            rma_item_factory(caso_id=caso.id, estado_recepcion_id=None)

        resp = _detallado(client_rma_ver)
        assert resp.status_code == 200
        data = resp.json()

        assert data["totales"]["items"] == 50

        dim = data["dimensiones"]["estado_recepcion"]
        by_id = {b["id"]: b for b in dim["buckets"]}

        assert by_id[opc_ok.id]["cantidad"] == 30
        assert by_id[opc_dan.id]["cantidad"] == 15
        assert by_id[None]["cantidad"] == 5

        # Completeness
        assert sum(b["cantidad"] for b in dim["buckets"]) == 50


# ---------------------------------------------------------------------------
# T-7: Date toggle — item counts differ between fecha_caso and recepcion_fecha
# ---------------------------------------------------------------------------


class TestDetalladoDateToggle:
    def test_detallado_date_toggle_item_counts(
        self,
        client_rma_ver,
        rma_caso_factory,
        rma_item_factory,
    ):
        """T-7 (RED→GREEN via T-12/T-13): date_field toggle controls which column is filtered.

        casos have fecha_caso in January; items have recepcion_fecha in February.
        - date_field=fecha_caso + Jan range → items IN range
        - date_field=recepcion_fecha + Jan range → items OUT of range (recepcion in Feb)
        """
        jan_fecha = date(2026, 1, 15)
        feb_recepcion = datetime(2026, 2, 15, 10, 0, 0)  # February — outside Jan range

        caso = rma_caso_factory(activo=True, fecha_caso=jan_fecha)
        for _ in range(5):
            rma_item_factory(caso_id=caso.id, recepcion_fecha=feb_recepcion)

        # a) date_field=fecha_caso → Jan casos → items included
        resp_a = _detallado(client_rma_ver, date_field="fecha_caso")
        assert resp_a.status_code == 200
        assert resp_a.json()["totales"]["items"] > 0

        # b) date_field=recepcion_fecha + Jan range → Feb recepcion → NOT included
        resp_b = _detallado(client_rma_ver, date_field="recepcion_fecha")
        assert resp_b.status_code == 200
        assert resp_b.json()["totales"]["items"] == 0


# ---------------------------------------------------------------------------
# T-8: abiertos/cerrados ALWAYS filtered by fecha_caso, never by recepcion_fecha toggle
# ---------------------------------------------------------------------------


class TestDetalladoAbiertosInvariant:
    def test_detallado_abiertos_cerrados_always_fecha_caso(
        self,
        client_rma_ver,
        rma_caso_factory,
        rma_item_factory,
        rma_opcion_factory,
    ):
        """T-8 (RED→GREEN via T-13): abiertos+cerrados count casos by fecha_caso regardless of toggle.

        3 casos with fecha_caso in January (2 abiertos, 1 cerrado).
        Items have recepcion_fecha in February (outside Jan range).
        Call with date_field=recepcion_fecha & Jan range.
        Expected: totales.abiertos + totales.cerrados == 3, totales.items == 0.
        """
        opc_abierto = rma_opcion_factory("estado_caso", "Abierto", orden=1)
        opc_cerrado = rma_opcion_factory("estado_caso", "Cerrado", orden=2)

        feb_recepcion = datetime(2026, 2, 15, 10, 0, 0)
        jan_fecha = date(2026, 1, 10)

        # 2 abiertos
        for _ in range(2):
            caso = rma_caso_factory(activo=True, fecha_caso=jan_fecha, estado_caso_id=opc_abierto.id)
            rma_item_factory(caso_id=caso.id, recepcion_fecha=feb_recepcion)

        # 1 cerrado
        caso = rma_caso_factory(activo=True, fecha_caso=jan_fecha, estado_caso_id=opc_cerrado.id)
        rma_item_factory(caso_id=caso.id, recepcion_fecha=feb_recepcion)

        resp = _detallado(client_rma_ver, date_field="recepcion_fecha")
        assert resp.status_code == 200
        data = resp.json()

        # item-level: recepcion in Feb → 0 items in Jan range
        assert data["totales"]["items"] == 0

        # caso-level: always fecha_caso → 3 casos in Jan range
        assert data["totales"]["abiertos"] + data["totales"]["cerrados"] == 3
        assert data["totales"]["abiertos"] == 2
        assert data["totales"]["cerrados"] == 1


# ---------------------------------------------------------------------------
# T-9: Empty range — dimension completeness: Sin clasificar with cantidad 0
# ---------------------------------------------------------------------------


class TestDetalladoEmptyRange:
    def test_detallado_empty_range_dimension_completeness(
        self,
        client_rma_ver,
    ):
        """T-9 (RED→GREEN via T-13): when no data in range, all dimensions have 'Sin clasificar' with cantidad 0.

        No casos/items seeded → totales all zero.
        Every dimension must still include a 'Sin clasificar' bucket (not an empty array).
        """
        resp = _detallado(client_rma_ver)
        assert resp.status_code == 200
        data = resp.json()

        assert data["totales"]["items"] == 0
        assert data["totales"]["casos"] == 0
        assert data["totales"]["abiertos"] == 0
        assert data["totales"]["cerrados"] == 0

        expected_dims = {
            "estado_recepcion",
            "causa_devolucion",
            "apto_venta",
            "estado_proceso",
            "estado_proveedor",
            "proveedor",
        }
        assert set(data["dimensiones"].keys()) == expected_dims, "All 6 dimensions must be present"

        for dim_name, dim in data["dimensiones"].items():
            sin_cls = [b for b in dim["buckets"] if b["id"] is None and b["valor"] == "Sin clasificar"]
            assert len(sin_cls) == 1, (
                f"Dimension '{dim_name}' must have exactly one 'Sin clasificar' bucket; got {dim['buckets']}"
            )
            assert sin_cls[0]["cantidad"] == 0, (
                f"'Sin clasificar' in '{dim_name}' must have cantidad 0 for empty range"
            )


# ---------------------------------------------------------------------------
# T-10: Proveedor top-N + Otros
# ---------------------------------------------------------------------------


class TestDetalladoProveedorTopN:
    def test_detallado_proveedor_top_n_otros(
        self,
        client_rma_ver,
        rma_caso_factory,
        rma_item_factory,
    ):
        """T-10 (RED→GREEN via T-13): top-N providers shown; remainder folded into 'Otros'.

        15 distinct providers, proveedor_top_n=8.
        Expected: 8 named-provider buckets + 1 'Otros' bucket.
        'Otros'.cantidad == sum of items from providers 9-15.
        """
        fecha = date(2026, 1, 15)
        caso = rma_caso_factory(activo=True, fecha_caso=fecha)

        # Provider 1 = 20 items, Provider 2 = 19 items, ..., Provider 15 = 6 items
        # So top-8 are providers 1-8; providers 9-15 go into Otros.
        expected_otros = 0
        for i in range(1, 16):
            count = 21 - i  # Provider 1 → 20, Provider 2 → 19, ..., Provider 15 → 6
            if i > 8:
                expected_otros += count
            for _ in range(count):
                rma_item_factory(
                    caso_id=caso.id,
                    supp_id=i,
                    proveedor_nombre=f"Proveedor {i}",
                )

        resp = _detallado(client_rma_ver, proveedor_top_n=8)
        assert resp.status_code == 200
        data = resp.json()

        dim_prov = data["dimensiones"]["proveedor"]
        buckets = dim_prov["buckets"]

        named = [b for b in buckets if b["id"] is not None]
        otros = [b for b in buckets if b["valor"] == "Otros"]
        sin_cls = [b for b in buckets if b["valor"] == "Sin clasificar"]

        assert len(named) == 8, f"Expected 8 named providers, got {len(named)}: {named}"
        assert len(otros) == 1, f"Expected 1 'Otros' bucket, got {otros}"
        assert otros[0]["cantidad"] == expected_otros, (
            f"Otros.cantidad={otros[0]['cantidad']} != expected {expected_otros}"
        )
        assert len(sin_cls) == 1, "Must have 'Sin clasificar' bucket"
        assert sin_cls[0]["cantidad"] == 0  # no NULL supp_id items

        # Total invariant
        total_items = data["totales"]["items"]
        assert sum(b["cantidad"] for b in buckets) == total_items


# ---------------------------------------------------------------------------
# T-14: 403 without rma.ver — drill-down
# ---------------------------------------------------------------------------


class TestDrilldownPermission:
    def test_drilldown_requires_rma_ver_403(self, client_no_ver):
        """T-14 (RED→GREEN via T-19): user without rma.ver receives HTTP 403 on drill-down."""
        resp = _drilldown(client_no_ver, dimension="estado_recepcion", valor="1")
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# T-15: Drill-down happy path — equipos and timeline
# ---------------------------------------------------------------------------


class TestDrilldownHappyPath:
    def test_drilldown_happy_path_equipos_and_timeline(
        self,
        client_rma_ver,
        db,
        rma_caso_factory,
        rma_item_factory,
        rma_opcion_factory,
        rma_historial_factory,
        rma_superadmin_user,
    ):
        """T-15 (RED→GREEN via T-18/T-19): drill-down returns correct equipos and timeline.

        5 items with estado_recepcion_id == opc.id, each with a historial transition.
        """
        fecha = date(2026, 1, 15)
        opc = rma_opcion_factory("estado_recepcion", "Dañado", orden=1, color="red")

        items_created = []
        for i in range(5):
            caso = rma_caso_factory(activo=True, fecha_caso=fecha)
            item = rma_item_factory(
                caso_id=caso.id,
                estado_recepcion_id=opc.id,
                serial_number=f"SN-{i:04d}",
                ean=f"EAN{i:07d}",
                producto_desc=f"Producto {i}",
            )
            # Add a historial transition for this item
            rma_historial_factory(
                caso_id=caso.id,
                caso_item_id=item.id,
                campo="estado_recepcion_id",
                valor_anterior=None,
                valor_nuevo=str(opc.id),
                usuario_id=rma_superadmin_user.id,
            )
            items_created.append((caso, item))

        resp = _drilldown(
            client_rma_ver,
            dimension="estado_recepcion",
            valor=str(opc.id),
        )
        assert resp.status_code == 200
        data = resp.json()

        assert "equipos" in data
        assert len(data["equipos"]) == 5

        # Every equipo must carry the expected fields
        for eq in data["equipos"]:
            assert "serial_number" in eq
            assert "ean" in eq
            assert "producto_desc" in eq
            assert "numero_caso" in eq
            assert "caso_id" in eq
            assert "timeline" in eq
            # Each item has 1 historial row
            assert len(eq["timeline"]) >= 1
            for evt in eq["timeline"]:
                assert "campo" in evt
                assert "valor_nuevo" in evt
                assert "usuario_nombre" in evt
                assert "created_at" in evt


# ---------------------------------------------------------------------------
# T-16: Drill-down NULL bucket (sin_clasificar)
# ---------------------------------------------------------------------------


class TestDrilldownSinClasificar:
    """Fixture-based test for NULL bucket drill-down."""

    def test_drilldown_sin_clasificar_null_fk(
        self,
        client_rma_ver,
        db,
        rma_caso_factory,
        rma_item_factory,
        rma_opcion_factory,
    ):
        """T-16 variant: valor=sin_clasificar returns ONLY items with NULL FK."""
        fecha = date(2026, 1, 15)

        opc = rma_opcion_factory("causa_devolucion", "Defecto Fabricante", orden=1)

        # 3 items with NULL causa_devolucion_id
        for _ in range(3):
            caso = rma_caso_factory(activo=True, fecha_caso=fecha)
            rma_item_factory(caso_id=caso.id, causa_devolucion_id=None)

        # 2 items with NON-NULL causa_devolucion_id (must NOT appear in sin_clasificar)
        for _ in range(2):
            caso = rma_caso_factory(activo=True, fecha_caso=fecha)
            rma_item_factory(caso_id=caso.id, causa_devolucion_id=opc.id)

        resp = _drilldown(client_rma_ver, dimension="causa_devolucion", valor="sin_clasificar")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["equipos"]) == 3


# ---------------------------------------------------------------------------
# T-17: No N+1 — bulk historial query
# ---------------------------------------------------------------------------


class TestDrilldownNoNPlusOne:
    def test_drilldown_no_n_plus_one(
        self,
        client_rma_ver,
        db,
        rma_caso_factory,
        rma_item_factory,
        rma_opcion_factory,
        rma_historial_factory,
        rma_superadmin_user,
    ):
        """T-17 (RED→GREEN via T-18/T-19): historial is fetched in ONE bulk query, not per-item.

        Strategy: count DB queries during the drilldown call.
        With N=5 items, an N+1 implementation would issue 1+5=6 historial queries.
        The bulk implementation issues exactly 1 historial query regardless of N.
        Total query budget: generous upper bound of 12 (auth+perms+items+1historial+overhead).
        """
        from sqlalchemy import event as sa_event

        fecha = date(2026, 1, 15)
        opc = rma_opcion_factory("estado_recepcion", "Pendiente", orden=1, color="yellow")

        n_items = 5
        for i in range(n_items):
            caso = rma_caso_factory(activo=True, fecha_caso=fecha)
            item = rma_item_factory(caso_id=caso.id, estado_recepcion_id=opc.id)
            rma_historial_factory(
                caso_id=caso.id,
                caso_item_id=item.id,
                campo="estado_recepcion_id",
                valor_nuevo=str(opc.id),
                usuario_id=rma_superadmin_user.id,
            )

        query_count: list[int] = [0]

        # Listen on the connection bound to the test session
        conn = db.connection()

        @sa_event.listens_for(conn, "after_cursor_execute")
        def _count(*args, **kwargs) -> None:
            query_count[0] += 1

        try:
            resp = _drilldown(
                client_rma_ver,
                dimension="estado_recepcion",
                valor=str(opc.id),
            )
            assert resp.status_code == 200
            assert len(resp.json()["equipos"]) == n_items
        finally:
            sa_event.remove(conn, "after_cursor_execute", _count)

        # N+1 bound: with 5 items, N+1 = 6 historial queries.
        # Bulk implementation must stay well below 6.
        # Budget: 12 covers auth, permission check, item query, 1 historial bulk query + overhead.
        assert query_count[0] <= 12, (
            f"Too many DB queries ({query_count[0]}): suspected N+1. "
            f"With {n_items} items, N+1 would be >{n_items + 4} queries."
        )
