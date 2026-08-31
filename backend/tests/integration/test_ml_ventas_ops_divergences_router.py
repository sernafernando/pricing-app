"""Integration tests for the divergence dashboard API (slice 6). Covers
permission BEFORE flag on every endpoint, `ml_ops.ver` for reads vs
`ml_ops.gestionar` for state changes, pagination, and the mandatory
`window_not_enumerable` sentinel never rendering `order_id=0` as an
order."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.core.config import settings
from app.models.ml_orders_ops import MlOpsDivergence
from app.models.permiso import Permiso, RolPermisoBase


@pytest.fixture(autouse=True)
def _flag_on(monkeypatch):
    monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", True)


def _grant(db, rol_admin, codigo: str, es_critico: bool = False) -> None:
    permiso = db.query(Permiso).filter(Permiso.codigo == codigo).first()
    if not permiso:
        permiso = Permiso(
            codigo=codigo, nombre=codigo, descripcion="", categoria="ml_ops", orden=200, es_critico=es_critico
        )
        db.add(permiso)
        db.flush()
    db.add(RolPermisoBase(rol_id=rol_admin.id, permiso_id=permiso.id))
    db.flush()


def _seed_divergence(db, order_id: int = 400, kind: str = "field_mismatch", **kwargs) -> MlOpsDivergence:
    row = MlOpsDivergence(
        order_id=order_id,
        kind=kind,
        field=kwargs.get("field", "status"),
        ml_value=kwargs.get("ml_value", "paid"),
        gbp_value=kwargs.get("gbp_value", "cancelled"),
        state=kwargs.get("state", "open"),
        detected_at=datetime(2026, 8, 30, tzinfo=timezone.utc),
    )
    db.add(row)
    db.commit()
    return row


class TestFlagAndPermissionGateList:
    def test_flag_off_returns_503_for_a_user_with_permission(
        self, db, client, admin_auth_headers, rol_admin, monkeypatch
    ):
        _grant(db, rol_admin, "ml_ops.ver")
        monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", False)
        resp = client.get("/api/ml-ventas-ops/divergences", headers=admin_auth_headers)
        assert resp.status_code == 503

    def test_flag_off_still_returns_403_for_a_user_without_permission(self, client, admin_auth_headers, monkeypatch):
        monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", False)
        resp = client.get("/api/ml-ventas-ops/divergences", headers=admin_auth_headers)
        assert resp.status_code == 403

    def test_user_without_permission_gets_403(self, client, auth_headers):
        resp = client.get("/api/ml-ventas-ops/divergences", headers=auth_headers)
        assert resp.status_code == 403


class TestListDivergences:
    def test_user_with_ver_can_list(self, db, client, admin_auth_headers, rol_admin) -> None:
        _grant(db, rol_admin, "ml_ops.ver")
        _seed_divergence(db, order_id=401)

        resp = client.get("/api/ml-ventas-ops/divergences", headers=admin_auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["divergences"][0]["order_id"] == 401

    def test_pagination_fields_are_present_and_respected(self, db, client, admin_auth_headers, rol_admin) -> None:
        _grant(db, rol_admin, "ml_ops.ver")
        for i in range(3):
            _seed_divergence(db, order_id=500 + i)

        resp = client.get("/api/ml-ventas-ops/divergences?limit=2&offset=0", headers=admin_auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 3
        assert body["limit"] == 2
        assert body["offset"] == 0
        assert len(body["divergences"]) == 2

    def test_pagination_with_tied_detected_at_does_not_skip_or_repeat_rows(
        self, db, client, admin_auth_headers, rol_admin
    ) -> None:
        """The detector inserts in batches sharing the same `detected_at`
        (often the same transactional `func.now()`) -- `ORDER BY
        detected_at DESC` alone has no stable order among ties on
        Postgres, so `offset=0` then `offset=1` can return overlapping
        sets and silently miss rows. This is exactly the page boundary
        (`offset > 0`) where that bug can appear."""
        _grant(db, rol_admin, "ml_ops.ver")
        same_instant = datetime(2026, 8, 30, tzinfo=timezone.utc)
        order_ids = [700, 701, 702]
        for order_id in order_ids:
            db.add(
                MlOpsDivergence(
                    order_id=order_id,
                    kind="field_mismatch",
                    field="status",
                    ml_value="paid",
                    gbp_value="cancelled",
                    state="open",
                    detected_at=same_instant,
                )
            )
        db.commit()

        seen_order_ids: list[int] = []
        for offset in (0, 1, 2):
            resp = client.get(f"/api/ml-ventas-ops/divergences?limit=1&offset={offset}", headers=admin_auth_headers)
            assert resp.status_code == 200
            page = resp.json()["divergences"]
            assert len(page) == 1
            seen_order_ids.append(page[0]["order_id"])

        assert sorted(seen_order_ids) == order_ids

    def test_list_query_orders_by_id_as_a_tiebreaker(self, db, client, admin_auth_headers, rol_admin) -> None:
        """SQLite happens to preserve a stable row order among ties on
        `detected_at` even without an explicit tiebreaker, so the
        behavioral test above cannot, by itself, prove the tiebreaker
        clause exists -- Postgres gives no such guarantee. This asserts
        the actual SQL sent to the database orders by `id` as well."""
        _grant(db, rol_admin, "ml_ops.ver")
        _seed_divergence(db, order_id=710)

        statements: list[str] = []
        engine = db.get_bind()

        def _capture(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        from sqlalchemy import event

        event.listen(engine, "before_cursor_execute", _capture)
        try:
            resp = client.get("/api/ml-ventas-ops/divergences", headers=admin_auth_headers)
        finally:
            event.remove(engine, "before_cursor_execute", _capture)

        assert resp.status_code == 200
        list_statements = [s for s in statements if "ml_ops_divergence" in s and "ORDER BY" in s.upper()]
        assert list_statements, f"expected an ORDER BY query, got: {statements}"
        order_by_clause = list_statements[0].upper()
        assert "DETECTED_AT" in order_by_clause
        assert "ID" in order_by_clause.split("ORDER BY")[-1]

    def test_filters_by_kind_and_state(self, db, client, admin_auth_headers, rol_admin) -> None:
        _grant(db, rol_admin, "ml_ops.ver")
        _seed_divergence(db, order_id=600, kind="missing_in_gbp", state="open")
        _seed_divergence(db, order_id=601, kind="field_mismatch", state="resolved")

        resp = client.get("/api/ml-ventas-ops/divergences?kind=missing_in_gbp&state=open", headers=admin_auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["divergences"][0]["order_id"] == 600

    def test_invalid_kind_is_422(self, db, client, admin_auth_headers, rol_admin) -> None:
        _grant(db, rol_admin, "ml_ops.ver")
        resp = client.get("/api/ml-ventas-ops/divergences?kind=bogus", headers=admin_auth_headers)
        assert resp.status_code == 422

    def test_window_not_enumerable_sentinel_is_never_rendered_as_an_order(
        self, db, client, admin_auth_headers, rol_admin
    ) -> None:
        db.add(
            MlOpsDivergence(
                order_id=0,
                kind="window_not_enumerable",
                field="123|456",
                ml_value="2026-08-01T00:00:00+00:00",
                gbp_value="2026-08-01T00:01:00+00:00",
                detected_at=datetime(2026, 8, 30, tzinfo=timezone.utc),
            )
        )
        db.commit()
        _grant(db, rol_admin, "ml_ops.ver")

        resp = client.get("/api/ml-ventas-ops/divergences?kind=window_not_enumerable", headers=admin_auth_headers)
        assert resp.status_code == 200
        row = resp.json()["divergences"][0]
        assert row["order_id"] is None
        assert row["window_from"] == "2026-08-01T00:00:00+00:00"
        assert row["window_to"] == "2026-08-01T00:01:00+00:00"


class TestGetDivergence:
    def test_unknown_id_is_404(self, db, client, admin_auth_headers, rol_admin) -> None:
        _grant(db, rol_admin, "ml_ops.ver")
        resp = client.get("/api/ml-ventas-ops/divergences/999999", headers=admin_auth_headers)
        assert resp.status_code == 404

    def test_window_not_enumerable_sentinel_is_never_rendered_as_an_order(
        self, db, client, admin_auth_headers, rol_admin
    ) -> None:
        """The list endpoint's own version of this test only proves the
        sentinel is hidden in a LIST response -- GET-by-id is a separate
        code path (`DivergenceSummary.from_row` is shared, but nothing
        forces the endpoint to actually call it correctly)."""
        row = MlOpsDivergence(
            order_id=0,
            kind="window_not_enumerable",
            field="123|456",
            ml_value="2026-08-01T00:00:00+00:00",
            gbp_value="2026-08-01T00:01:00+00:00",
            detected_at=datetime(2026, 8, 30, tzinfo=timezone.utc),
        )
        db.add(row)
        db.commit()
        _grant(db, rol_admin, "ml_ops.ver")

        resp = client.get(f"/api/ml-ventas-ops/divergences/{row.id}", headers=admin_auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["order_id"] is None
        assert body["window_from"] == "2026-08-01T00:00:00+00:00"
        assert body["window_to"] == "2026-08-01T00:01:00+00:00"


class TestUpdateDivergence:
    def test_ver_only_permission_cannot_update_state(self, db, client, admin_auth_headers, rol_admin) -> None:
        _grant(db, rol_admin, "ml_ops.ver")
        row = _seed_divergence(db, order_id=800)

        resp = client.patch(
            f"/api/ml-ventas-ops/divergences/{row.id}", json={"state": "acknowledged"}, headers=admin_auth_headers
        )
        assert resp.status_code == 403

    def test_gestionar_permission_can_update_state_note_and_assignee(
        self, db, client, admin_auth_headers, rol_admin, admin_user
    ) -> None:
        _grant(db, rol_admin, "ml_ops.gestionar", es_critico=True)
        row = _seed_divergence(db, order_id=801)

        resp = client.patch(
            f"/api/ml-ventas-ops/divergences/{row.id}",
            json={"state": "acknowledged", "note": "investigando", "assigned_to_id": admin_user.id},
            headers=admin_auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["state"] == "acknowledged"
        assert body["note"] == "investigando"
        assert body["assigned_to_id"] == admin_user.id

    def test_invalid_state_is_422(self, db, client, admin_auth_headers, rol_admin) -> None:
        _grant(db, rol_admin, "ml_ops.gestionar", es_critico=True)
        row = _seed_divergence(db, order_id=802)

        resp = client.patch(
            f"/api/ml-ventas-ops/divergences/{row.id}", json={"state": "bogus"}, headers=admin_auth_headers
        )
        assert resp.status_code == 422

    def test_flag_off_returns_503_for_a_user_with_gestionar(
        self, db, client, admin_auth_headers, rol_admin, monkeypatch
    ) -> None:
        _grant(db, rol_admin, "ml_ops.gestionar", es_critico=True)
        row = _seed_divergence(db, order_id=803)
        monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", False)

        resp = client.patch(
            f"/api/ml-ventas-ops/divergences/{row.id}", json={"state": "resolved"}, headers=admin_auth_headers
        )
        assert resp.status_code == 503

    def test_unknown_divergence_id_is_404(self, db, client, admin_auth_headers, rol_admin) -> None:
        _grant(db, rol_admin, "ml_ops.gestionar", es_critico=True)
        resp = client.patch(
            "/api/ml-ventas-ops/divergences/999999", json={"state": "resolved"}, headers=admin_auth_headers
        )
        assert resp.status_code == 404

    def test_nonexistent_assigned_to_id_is_422_not_500(self, db, client, admin_auth_headers, rol_admin) -> None:
        """The column is an FK to `usuarios.id`; an unvalidated bad id
        used to reach `db.commit()` and raise `IntegrityError` -- a 500
        that also left the session broken."""
        _grant(db, rol_admin, "ml_ops.gestionar", es_critico=True)
        row = _seed_divergence(db, order_id=804)

        resp = client.patch(
            f"/api/ml-ventas-ops/divergences/{row.id}",
            json={"assigned_to_id": 999999},
            headers=admin_auth_headers,
        )
        assert resp.status_code == 422

        # the session must still be usable afterward -- a broken session
        # from an uncaught IntegrityError would fail this query too.
        assert db.query(MlOpsDivergence).filter(MlOpsDivergence.id == row.id).one().assigned_to_id is None

    def test_explicit_null_assigned_to_id_unassigns(
        self, db, client, admin_auth_headers, rol_admin, admin_user
    ) -> None:
        """`None` used to mean "leave alone" -- `{"assigned_to_id": null}`
        was a silent no-op that still returned 200 with the OLD assignee.
        The operator believes they released it; they had not."""
        _grant(db, rol_admin, "ml_ops.gestionar", es_critico=True)
        row = _seed_divergence(db, order_id=805)
        row.assigned_to_id = admin_user.id
        db.commit()

        resp = client.patch(
            f"/api/ml-ventas-ops/divergences/{row.id}",
            json={"assigned_to_id": None},
            headers=admin_auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["assigned_to_id"] is None
        assert db.query(MlOpsDivergence).filter(MlOpsDivergence.id == row.id).one().assigned_to_id is None

    def test_explicit_null_note_clears_it(self, db, client, admin_auth_headers, rol_admin) -> None:
        _grant(db, rol_admin, "ml_ops.gestionar", es_critico=True)
        row = _seed_divergence(db, order_id=806)
        row.note = "algo"
        db.commit()

        resp = client.patch(f"/api/ml-ventas-ops/divergences/{row.id}", json={"note": None}, headers=admin_auth_headers)
        assert resp.status_code == 200
        assert resp.json()["note"] is None

    def test_absent_field_is_left_alone(self, db, client, admin_auth_headers, rol_admin, admin_user) -> None:
        """The contract this whole fix exists for: an ABSENT field in the
        PATCH body must not touch the column at all, distinct from an
        explicit `null`."""
        _grant(db, rol_admin, "ml_ops.gestionar", es_critico=True)
        row = _seed_divergence(db, order_id=807)
        row.assigned_to_id = admin_user.id
        row.note = "ya asignado"
        db.commit()

        resp = client.patch(
            f"/api/ml-ventas-ops/divergences/{row.id}", json={"state": "acknowledged"}, headers=admin_auth_headers
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["state"] == "acknowledged"
        assert body["assigned_to_id"] == admin_user.id
        assert body["note"] == "ya asignado"
