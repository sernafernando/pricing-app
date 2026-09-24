"""RED/GREEN -- `app/routers/ml_order_metrics.py` (ventas-ml-rediseno
PR6.T6-T9, design D9/D10): `GET /order-metrics/health` (perm `ml_ops.ver`)
and `POST /order-metrics/divergence/run` (perm `ml_ops.gestionar`, the
closest admin-level write permission this router family already uses).

Health's underlying aggregates (`app.services.order_metrics.health`) are
Postgres-only and already tested against real Postgres in
`tests/services/order_metrics/test_health.py`; these tests run on the
SQLite `db`/`client` fixtures and monkeypatch that module's functions to
verify permission gating and response assembly only.
"""

from __future__ import annotations

import pytest

from app.models.permiso import Permiso, RolPermisoBase
from app.services.order_metrics import health as order_metrics_health


def _grant(db, rol_admin, codigo: str) -> None:
    permiso = db.query(Permiso).filter(Permiso.codigo == codigo).first()
    if not permiso:
        permiso = Permiso(codigo=codigo, nombre=codigo, descripcion="", categoria="ml_ops", orden=200)
        db.add(permiso)
        db.flush()
    db.add(RolPermisoBase(rol_id=rol_admin.id, permiso_id=permiso.id))
    db.flush()


@pytest.fixture(autouse=True)
def _patch_health_aggregates(monkeypatch):
    monkeypatch.setattr(order_metrics_health, "queue_depth", lambda db: 3)
    monkeypatch.setattr(order_metrics_health, "claimed_count", lambda db: 1)
    monkeypatch.setattr(order_metrics_health, "oldest_dirty_age_seconds", lambda db: 12.5)
    monkeypatch.setattr(order_metrics_health, "missing_metrics_count", lambda db: 7)
    monkeypatch.setattr(
        order_metrics_health,
        "poisoned_orders",
        lambda db, limit=50: [order_metrics_health.PoisonedOrder(order_id=99, last_error="boom")],
    )
    monkeypatch.setattr(order_metrics_health, "poisoned_count", lambda db: 1)


class TestHealthPermission:
    def test_user_without_permission_gets_403(self, client, auth_headers) -> None:
        resp = client.get("/api/ml-ops/order-metrics/health", headers=auth_headers)
        assert resp.status_code == 403

    def test_user_with_ver_gets_200(self, db, client, admin_auth_headers, rol_admin) -> None:
        _grant(db, rol_admin, "ml_ops.ver")
        resp = client.get("/api/ml-ops/order-metrics/health", headers=admin_auth_headers)
        assert resp.status_code == 200


class TestHealthResponseShape:
    def test_response_carries_every_documented_field(self, db, client, admin_auth_headers, rol_admin) -> None:
        _grant(db, rol_admin, "ml_ops.ver")

        resp = client.get("/api/ml-ops/order-metrics/health", headers=admin_auth_headers)
        assert resp.status_code == 200
        body = resp.json()

        for field in (
            "queue_depth",
            "oldest_dirty_age_s",
            "claimed_count",
            "poisoned_count",
            "worker_heartbeat_at",
            "worker_alive",
            "worker_draining",
            "listener_mode",
            "last_divergence",
            "formula_version",
        ):
            assert field in body, f"missing field: {field}"

        assert body["queue_depth"] == 3
        assert body["claimed_count"] == 1
        assert body["oldest_dirty_age_s"] == 12.5
        assert body["poisoned_count"] == 1
        assert body["poisoned_orders"] == [{"order_id": 99, "last_error": "boom"}]

    def test_worker_alive_false_when_heartbeat_stale_or_absent(self, db, client, admin_auth_headers, rol_admin) -> None:
        _grant(db, rol_admin, "ml_ops.ver")
        resp = client.get("/api/ml-ops/order-metrics/health", headers=admin_auth_headers)
        body = resp.json()
        # No `worker` row ever written in this SQLite fixture -- no
        # heartbeat means NOT alive, never a fabricated True.
        assert body["worker_alive"] is False
        assert body["worker_heartbeat_at"] is None


class TestHealthReportsOrdersWithNoMetricsRow:
    """PR6 review: the D10 production gate (PR6.T12) tells the owner to poll
    this endpoint and confirm nothing is missing before trusting the stored
    values. The only `missing_count` the response carried came from the
    DIVERGENCE summary, which scans orders that ALREADY have an
    `ml_order_metrics` row -- so orders with no row at all were counted by
    nobody. With the whole history un-backfilled (77k orders on this
    project's production the day this shipped) the gate figure would have
    read 0 while nothing was computed. The endpoint must surface
    `missing_metrics_count`, the helper that counts exactly those orders
    and deliberately excludes parked ones."""

    def test_missing_metrics_count_is_surfaced(self, db, client, admin_auth_headers, rol_admin) -> None:
        _grant(db, rol_admin, "ml_ops.ver")

        body = client.get("/api/ml-ops/order-metrics/health", headers=admin_auth_headers).json()

        assert body["missing_metrics_count"] == 7, (
            "orders with no metrics row must be reported, or the gate reads clean on an empty backfill"
        )


class TestHealthGateAccounting:
    """PR6.T11a: `missing_count` excludes parked orders (health.py's own
    contract); the endpoint must surface `poisoned_count` and the poisoned
    order list, never hide them behind a clean-looking `missing_count`."""

    def test_missing_count_and_poisoned_count_are_independent_figures(
        self, db, client, admin_auth_headers, rol_admin, monkeypatch
    ) -> None:
        _grant(db, rol_admin, "ml_ops.ver")
        monkeypatch.setattr(order_metrics_health, "missing_metrics_count", lambda db: 0)
        monkeypatch.setattr(
            order_metrics_health,
            "poisoned_orders",
            lambda db, limit=50: [
                order_metrics_health.PoisonedOrder(order_id=1, last_error="bad data"),
                order_metrics_health.PoisonedOrder(order_id=2, last_error="timeout"),
            ],
        )
        monkeypatch.setattr(order_metrics_health, "poisoned_count", lambda db: 2)
        resp = client.get("/api/ml-ops/order-metrics/health", headers=admin_auth_headers)
        body = resp.json()
        assert body["poisoned_count"] == 2
        assert {row["order_id"] for row in body["poisoned_orders"]} == {1, 2}

    def test_poisoned_count_is_never_capped_by_the_sample_list(
        self, db, client, admin_auth_headers, rol_admin, monkeypatch
    ) -> None:
        """PR6 review fix J1: `poisoned_orders`'s default `limit=50` must
        never leak into `poisoned_count` -- a 300-order backlog reads as
        300, not silently as 50."""
        _grant(db, rol_admin, "ml_ops.ver")
        monkeypatch.setattr(
            order_metrics_health,
            "poisoned_orders",
            lambda db, limit=50: [order_metrics_health.PoisonedOrder(order_id=i, last_error="boom") for i in range(50)],
        )
        monkeypatch.setattr(order_metrics_health, "poisoned_count", lambda db: 300)

        resp = client.get("/api/ml-ops/order-metrics/health", headers=admin_auth_headers)
        body = resp.json()
        assert body["poisoned_count"] == 300
        assert len(body["poisoned_orders"]) == 50


class TestDivergenceRunPermission:
    def test_ver_alone_is_not_enough(self, db, client, admin_auth_headers, rol_admin) -> None:
        _grant(db, rol_admin, "ml_ops.ver")
        resp = client.post("/api/ml-ops/order-metrics/divergence/run", headers=admin_auth_headers)
        assert resp.status_code == 403

    def test_gestionar_can_trigger(self, db, client, admin_auth_headers, rol_admin) -> None:
        _grant(db, rol_admin, "ml_ops.gestionar")
        resp = client.post("/api/ml-ops/order-metrics/divergence/run", headers=admin_auth_headers)
        assert resp.status_code == 202


class TestDivergenceRunSetsRequestedState:
    def test_sets_worker_job_state_requested_never_runs_inline(
        self, db, client, admin_auth_headers, rol_admin, monkeypatch
    ) -> None:
        _grant(db, rol_admin, "ml_ops.gestionar")

        # The endpoint must NEVER call the handler directly -- only flip
        # the requested flag for the worker's own next wake to pick up.
        from app.workers.handlers import order_metrics as handlers_module

        called = {"ran": False}

        def _forbidden_run(*args, **kwargs):
            called["ran"] = True
            raise AssertionError("divergence.run must not be called inline by the endpoint")

        monkeypatch.setattr(handlers_module.divergence, "run", _forbidden_run)

        resp = client.post("/api/ml-ops/order-metrics/divergence/run", headers=admin_auth_headers)
        assert resp.status_code == 202
        assert called["ran"] is False

        from app.models.worker_job_state import WorkerJobState

        row = db.query(WorkerJobState).filter(WorkerJobState.name == "order_metrics.divergence").first()
        assert row is not None
        assert row.state == "requested"
