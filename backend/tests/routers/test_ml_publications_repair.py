"""Read-only repair control view endpoints (`/api/ml-publications/repair/...`)."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.main import app
from app.models.ml_write_log import MlWriteLog
from app.models.publicacion_repair import (
    PublicacionRepairEvent,
    PublicacionRepairRun,
)
from app.routers import ml_publications_repair
from tests.routers.test_ml_publications_links import grant
from tests.services.ml_publications.conftest import mlpub_pg  # noqa: F401

pytestmark = pytest.mark.postgres

BASE = "/api/ml-publications/repair"
VER = "ml_ops.ver"


@pytest.fixture()
def pg(client, request, monkeypatch):

    engine = request.getfixturevalue("mlpub_pg")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS usuarios (id serial PRIMARY KEY, nombre varchar(255) NOT NULL, username varchar(100) NOT NULL)"
            )
        )
    PublicacionRepairRun.__table__.create(bind=engine, checkfirst=True)
    PublicacionRepairEvent.__table__.create(bind=engine, checkfirst=True)
    MlWriteLog.__table__.create(bind=engine, checkfirst=True)
    # Live-label joins for the control view (title / ERP descripcion).
    with engine.begin() as conn:
        conn.execute(
            text("CREATE TABLE IF NOT EXISTS ml_items (item_id text PRIMARY KEY, title text)")
        )
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS productos_erp "
                "(item_id integer PRIMARY KEY, descripcion varchar(500))"
            )
        )

    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    sessions: list[Session] = []

    def _repair_db():
        session = factory()
        sessions.append(session)
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[ml_publications_repair.get_repair_db] = _repair_db
    yield engine
    app.dependency_overrides.pop(ml_publications_repair.get_repair_db, None)


@pytest.fixture()
def reader(db, rol_admin, admin_auth_headers):
    grant(db, rol_admin, VER)
    return admin_auth_headers


@pytest.fixture()
def no_perm(db, admin_auth_headers):
    return admin_auth_headers


def insert_run(engine, **kw):
    defaults = dict(job_type="envio", status="success", trigger="tick", scanned=10, changed=2, skipped=7, errors=1)
    defaults.update(kw)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO publicacion_repair_run (job_type, status, trigger, started_at, finished_at, scanned, changed, skipped, errors, error_message) "
                "VALUES (:job_type, :status, :trigger, COALESCE(:started_at, now()), :finished_at, :scanned, :changed, :skipped, :errors, :error_message)"
            ),
            {
                "job_type": defaults["job_type"],
                "status": defaults["status"],
                "trigger": defaults["trigger"],
                "started_at": defaults.get("started_at"),
                "finished_at": defaults.get("finished_at"),
                "scanned": defaults["scanned"],
                "changed": defaults["changed"],
                "skipped": defaults["skipped"],
                "errors": defaults["errors"],
                "error_message": defaults.get("error_message"),
            },
        )
        rid = conn.execute(text("SELECT currval(pg_get_serial_sequence('publicacion_repair_run','id'))")).scalar()
    return rid


def insert_event(
    engine, run_id, mla_id="MLA1", action="changed", detail="shipping_put", before=None, after=None, item_id=None
):
    import json

    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO publicacion_repair_event (run_id, mla_id, item_id, action, before, after, detail) "
                "VALUES (:run_id, :mla_id, :item_id, :action, CAST(:before AS jsonb), CAST(:after AS jsonb), :detail)"
            ),
            {
                "run_id": run_id,
                "mla_id": mla_id,
                "item_id": item_id,
                "action": action,
                "before": json.dumps(before) if before is not None else None,
                "after": json.dumps(after) if after is not None else None,
                "detail": detail,
            },
        )
        eid = conn.execute(text("SELECT currval(pg_get_serial_sequence('publicacion_repair_event','id'))")).scalar()
    return eid


def insert_write(engine, mla, action, payload=None, usuario_id=None, resource="item"):
    import json

    with engine.begin() as conn:
        if usuario_id is not None:
            conn.execute(
                text("INSERT INTO usuarios (id, nombre, username) VALUES (:id, 'u', 'u') ON CONFLICT (id) DO NOTHING"),
                {"id": usuario_id},
            )
        conn.execute(
            text(
                "INSERT INTO ml_write_log (mla, resource, action, payload, usuario_id) "
                "VALUES (:mla, :resource, :action, CAST(:payload AS jsonb), :uid)"
            ),
            {
                "mla": mla,
                "resource": resource,
                "action": action,
                "payload": json.dumps(payload) if payload is not None else None,
                "uid": usuario_id,
            },
        )


class TestAuth:
    def test_unauth(self, client, pg):
        assert client.get(f"{BASE}/runs").status_code in (401, 403)

    def test_no_perm_403(self, client, pg, no_perm):
        assert client.get(f"{BASE}/runs", headers=no_perm).status_code == 403
        assert client.get(f"{BASE}/runs/1", headers=no_perm).status_code == 403
        assert client.get(f"{BASE}/events?mla_id=MLA1", headers=no_perm).status_code == 403


class TestRuns:
    def test_list_empty(self, client, pg, reader):
        body = client.get(f"{BASE}/runs", headers=reader).json()
        assert body["total"] == 0 and body["items"] == []

    def test_list_filters_and_pagination(self, client, pg, reader):
        insert_run(pg, job_type="envio", status="success")
        r2 = insert_run(pg, job_type="sku", status="failed", errors=3, error_message="boom")
        body = client.get(f"{BASE}/runs?job_type=sku", headers=reader).json()
        assert body["total"] == 1
        assert body["items"][0]["id"] == r2
        # pagination bounds
        assert client.get(f"{BASE}/runs?page=0", headers=reader).status_code == 422
        assert client.get(f"{BASE}/runs?page_size=0", headers=reader).status_code == 422
        assert client.get(f"{BASE}/runs?page_size=201", headers=reader).status_code == 422

    def test_status_filter(self, client, pg, reader):
        insert_run(pg, status="success")
        insert_run(pg, status="failed", errors=1)
        body = client.get(f"{BASE}/runs?status=failed", headers=reader).json()
        assert body["total"] == 1

    def test_date_range_filters(self, client, pg, reader):
        from datetime import datetime, time, timedelta
        from zoneinfo import ZoneInfo

        ar = ZoneInfo("America/Argentina/Buenos_Aires")
        today = datetime.now(ar).date()
        yesterday = today - timedelta(days=1)
        insert_run(pg, started_at=datetime.combine(yesterday, datetime.min.time(), tzinfo=ar))
        # 22:00 Argentina is 01:00 UTC the next day: must still count for today.
        insert_run(pg, started_at=datetime.combine(today, time(22, 0), tzinfo=ar))
        body = client.get(f"{BASE}/runs?desde={today.isoformat()}&hasta={today.isoformat()}", headers=reader).json()
        assert body["total"] == 1

    def test_newest_first_ordering(self, client, pg, reader):
        from datetime import datetime, timedelta, timezone

        older = insert_run(pg, started_at=datetime.now(timezone.utc) - timedelta(days=1))
        newer = insert_run(pg, started_at=datetime.now(timezone.utc))
        body = client.get(f"{BASE}/runs", headers=reader).json()
        assert [r["id"] for r in body["items"]] == [newer, older]

    def test_invalid_date_returns_422(self, client, pg, reader):
        assert client.get(f"{BASE}/runs?desde=not-a-date", headers=reader).status_code == 422
        assert client.get(f"{BASE}/runs?hasta=2026-99-99", headers=reader).status_code == 422


class TestRunDetail:
    def test_404(self, client, pg, reader):
        assert client.get(f"{BASE}/runs/999999", headers=reader).status_code == 404

    def test_events_filters_and_breakdown(self, client, pg, reader):
        rid = insert_run(pg)
        insert_event(pg, rid, mla_id="MLA1", action="changed", detail="shipping_put", before={"a": 1}, after={"a": 2})
        insert_event(pg, rid, mla_id="MLA2", action="skipped", detail="flex_refused")
        # filtered by action
        body = client.get(f"{BASE}/runs/{rid}?action=changed", headers=reader).json()
        assert body["total"] == 1
        assert body["events"][0]["mla_id"] == "MLA1"
        # breakdown ignores the action/detail filters: the filtered response still
        # lists every (action, detail) group of the run.
        bd_filtered = {(b["action"], b["detail"]): b["count"] for b in body["breakdown"]}
        assert bd_filtered[("skipped", "flex_refused")] == 1
        body2 = client.get(f"{BASE}/runs/{rid}", headers=reader).json()
        bd = {(b["action"], b["detail"]): b["count"] for b in body2["breakdown"]}
        assert bd[("changed", "shipping_put")] == 1
        assert bd[("skipped", "flex_refused")] == 1
        # compact diff keys present
        changed_ev = next(e for e in body2["events"] if e["action"] == "changed")
        assert changed_ev["before"] == {"a": 1} and changed_ev["after"] == {"a": 2}

    def test_events_include_live_title_and_descripcion(self, client, pg, reader):
        with pg.begin() as conn:
            conn.execute(
                text("INSERT INTO ml_items (item_id, title) VALUES ('MLA1', 'Cable HDMI 2m')")
            )
            conn.execute(
                text(
                    "INSERT INTO productos_erp (item_id, descripcion) "
                    "VALUES (42, 'CABLE HDMI 2 METROS')"
                )
            )
        rid = insert_run(pg)
        insert_event(
            pg,
            rid,
            mla_id="MLA1",
            item_id=42,
            action="changed",
            detail="seller_sku",
        )
        body = client.get(f"{BASE}/runs/{rid}", headers=reader).json()
        ev = body["events"][0]
        assert ev["title"] == "Cable HDMI 2m"
        assert ev["descripcion"] == "CABLE HDMI 2 METROS"
        assert ev["detail"] == "seller_sku"

    def test_detail_filter(self, client, pg, reader):
        rid = insert_run(pg)
        insert_event(pg, rid, action="skipped", detail="flex_refused")
        insert_event(pg, rid, action="skipped", detail="rate_limited")
        body = client.get(f"{BASE}/runs/{rid}?detail=rate_limited", headers=reader).json()
        assert body["total"] == 1
        assert body["events"][0]["detail"] == "rate_limited"

    def test_events_newest_first(self, client, pg, reader):
        rid = insert_run(pg)
        first = insert_event(pg, rid, mla_id="MLA1", action="changed", detail="shipping_put")
        second = insert_event(pg, rid, mla_id="MLA2", action="skipped", detail="flex_refused")
        body = client.get(f"{BASE}/runs/{rid}", headers=reader).json()
        assert [e["id"] for e in body["events"]] == [second, first]

    def test_pagination_bounds(self, client, pg, reader):
        rid = insert_run(pg)
        assert client.get(f"{BASE}/runs/{rid}?page=0", headers=reader).status_code == 422
        assert client.get(f"{BASE}/runs/{rid}?page_size=0", headers=reader).status_code == 422
        assert client.get(f"{BASE}/runs/{rid}?page_size=201", headers=reader).status_code == 422


class TestMlaEvents:
    def test_events_across_runs_with_run_context(self, client, pg, reader):
        r1 = insert_run(pg, job_type="envio")
        r2 = insert_run(pg, job_type="sku")
        insert_event(pg, r1, mla_id="MLA9", action="changed", detail="shipping_put")
        insert_event(pg, r2, mla_id="MLA9", action="changed", detail="shipping_put")
        body = client.get(f"{BASE}/events?mla_id=MLA9", headers=reader).json()
        assert body["total"] == 2
        assert body["events"][0]["run_job_type"] in ("envio", "sku")
        assert body["events"][0]["run_started_at"] is not None

    def test_ml_writes_excludes_non_repair(self, client, pg, reader):
        insert_write(pg, "MLA9", "update_shipping", {"shipping": {"x": 1}}, usuario_id=None)
        insert_write(pg, "MLA9", "enable_flex", {"site": "MLA"}, usuario_id=None)
        insert_write(pg, "MLA9", "update_data", {"attributes": []}, usuario_id=None)
        # non-repair: user write
        insert_write(pg, "MLA9", "update_data", {"x": 1}, usuario_id=1)
        # non-repair action
        insert_write(pg, "MLA9", "pause", None, usuario_id=None)
        body = client.get(f"{BASE}/events?mla_id=MLA9", headers=reader).json()
        actions = [w["action"] for w in body["ml_writes"]]
        assert sorted(actions) == ["enable_flex", "update_data", "update_shipping"]
        assert len(body["ml_writes"]) == 3

    def test_events_newest_first(self, client, pg, reader):
        r1 = insert_run(pg, job_type="envio")
        r2 = insert_run(pg, job_type="sku")
        insert_event(pg, r1, mla_id="MLA7", action="changed", detail="shipping_put")
        insert_event(pg, r2, mla_id="MLA7", action="skipped", detail="flex_refused")
        body = client.get(f"{BASE}/events?mla_id=MLA7", headers=reader).json()
        assert body["events"][0]["run_job_type"] == "sku"

    def test_pagination_bounds(self, client, pg, reader):
        assert client.get(f"{BASE}/events?mla_id=MLA1&page=0", headers=reader).status_code == 422
        assert client.get(f"{BASE}/events?mla_id=MLA1&page_size=0", headers=reader).status_code == 422
        assert client.get(f"{BASE}/events?mla_id=MLA1&page_size=201", headers=reader).status_code == 422

    def test_ml_writes_excludes_non_item_resource(self, client, pg, reader):
        insert_write(pg, "MLA9", "update_shipping", {"shipping": {"x": 1}}, usuario_id=None, resource="promotion")
        body = client.get(f"{BASE}/events?mla_id=MLA9", headers=reader).json()
        assert body["ml_writes"] == []

    def test_mla_required(self, client, pg, reader):
        assert client.get(f"{BASE}/events", headers=reader).status_code == 422
