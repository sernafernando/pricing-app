"""S12f1: the Publicaciones ML screen takes `productos.ver` OR `ml_ops.ver`, and nothing wider.

Regression probes from the change's independent verification: with Productos' permission alone the screen's
reads answer, but what each read asks on top (pausing, Métricas, the margin) and the `ml_ops.ver` reads outside the
screen stay closed; with neither permission every screen read is 403; SUPERADMIN reads it.
"""

# ruff: noqa: F811  (the imported `pg` fixture is a test parameter)
from __future__ import annotations

import pytest

from app.routers import ml_publications_view
from tests.conftest import make_access_token
from tests.routers import test_ml_publications_view as view_tests
from tests.routers.test_ml_publications_links import grant
from tests.routers.test_ml_publications_view import pg  # noqa: F401
from tests.services.ml_publications.conftest import mlpub_pg  # noqa: F401

pytestmark = pytest.mark.postgres

VIEW_PATHS = sorted(route.path.replace("{item_id}", "MLA1") for route in ml_publications_view.router.routes)


@pytest.fixture()
def productos_only(db, rol_ventas, auth_headers):
    grant(db, rol_ventas, "productos.ver")
    return auth_headers


class TestNotWider:
    def test_status_item_ids_still_needs_pausar(self, client, pg, productos_only):
        response = client.get("/api/ml-publications/view/status-item-ids?target=paused", headers=productos_only)
        assert response.status_code == 403
        assert "pausar" in response.text

    def test_kpis_still_need_ml_metricas_ver(self, client, pg, productos_only):
        response = client.get("/api/ml-publications/view/kpis", headers=productos_only)
        assert response.status_code == 403
        assert "ml_metricas.ver" in response.text

    def test_items_carry_no_markup_nor_metrics_with_productos_ver_alone(self, client, pg, productos_only):
        with pg.begin() as conn:
            view_tests.TestContract.fill(None, conn)
        response = client.get("/api/ml-publications/view/items", headers=productos_only)
        assert response.status_code == 200, response.text
        rows = response.json()["items"]
        assert rows
        for row in rows:
            assert "markup" not in row and "metrics" not in row and "sales_30d" not in row

    def test_a_markup_filter_is_403_with_productos_ver_alone(self, client, pg, productos_only):
        assert client.get("/api/ml-publications/view/items?markup_neg=true", headers=productos_only).status_code == 403

    @pytest.mark.parametrize(
        "path",
        [
            "/api/ml-publications/status",
            "/api/ml-publications/settings",
            "/api/ml-publications/product-links",
            "/api/ml-publications/product-links/coverage",
            "/api/ml-ventas-ops/sales",
            "/api/ml-ops/order-metrics/health",
        ],
    )
    def test_ml_ops_reads_outside_the_screen_stay_closed(self, client, pg, productos_only, path):
        assert client.get(path, headers=productos_only).status_code == 403


class TestNeither:
    @pytest.mark.parametrize("path", VIEW_PATHS)
    def test_neither_permission_is_403_on_every_view_read(self, client, pg, auth_headers, path):
        assert client.get(f"/api{path}", headers=auth_headers).status_code == 403

    @pytest.mark.parametrize(
        "path",
        ["/api/ml-publications/items/MLA1/product-links", "/api/ml-item-overrides/MLA1", "/api/productos-propios/70"],
    )
    def test_neither_permission_is_403_on_the_panel_reads(self, client, pg, auth_headers, path):
        assert client.get(path, headers=auth_headers).status_code == 403

    def test_superadmin_reads_the_screen(self, client, pg, rma_superadmin_user):
        headers = {"Authorization": f"Bearer {make_access_token(rma_superadmin_user)}"}
        assert client.get("/api/ml-publications/view/items", headers=headers).status_code == 200
