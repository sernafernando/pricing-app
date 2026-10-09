"""P12.T1-T4: the admin endpoints of the ML publications store (`/api/ml-publications/...`).

Authentication, permission and the user table live in the SQLite test database; the store tables live in a
throwaway Postgres schema, reached through the router's own `get_admin_db` seam (and `settings_store`, which
`mlpub_pg` points at the same schema). The endpoints turn nothing on by existing: the settings one is the only
way in and it needs `ml_ops.gestionar`.
"""

from __future__ import annotations

import pytest
from sqlalchemy import event, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.main import app
from app.routers import ml_publications_admin
from app.services.ml_publications import admin, settings_store
from app.services.ml_publications.ml_http import MlHttpClient
from tests.routers.test_ml_publications_links import grant
from tests.services.ml_publications.conftest import mlpub_pg  # noqa: F401
from tests.services.ml_publications.test_status import WORKER_STATE_DDL

pytestmark = pytest.mark.postgres

BASE = "/api/ml-publications"
VER = "ml_ops.ver"
GESTIONAR = "ml_ops.gestionar"
ROUTES = [
    ("get", "/status", None),
    ("get", "/settings", None),
    ("put", "/settings/refresh.enabled", {"value": True}),
    ("post", "/enqueue", {"item_ids": ["MLA935110613"]}),
    ("post", "/jobs/refresh/request", None),
]


@pytest.fixture()
def pg(client, request, monkeypatch):
    """The store tables behind the router. `client` goes first so the shared column types are restored to
    Postgres' after the SQLite engine patched them."""
    from app.models.producto import ProductoERP

    engine = request.getfixturevalue("mlpub_pg")
    ProductoERP.__table__.create(bind=engine)
    with engine.begin() as conn:
        conn.execute(text(WORKER_STATE_DDL))
    monkeypatch.setattr(settings, "ML_PUB_KILL_SWITCH", False)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    sessions: list[Session] = []

    def _admin_db():
        session = factory()
        sessions.append(session)
        try:
            yield session
        finally:
            session.close()

    def no_ml(*args, **kwargs):
        pytest.fail("the admin endpoints must not call ML")

    monkeypatch.setattr(MlHttpClient, "get", no_ml)
    app.dependency_overrides[ml_publications_admin.get_admin_db] = _admin_db
    yield engine
    app.dependency_overrides.pop(ml_publications_admin.get_admin_db, None)


@pytest.fixture()
def reader(db, rol_admin, admin_auth_headers):
    grant(db, rol_admin, VER)
    return admin_auth_headers


@pytest.fixture()
def operator(db, rol_admin, admin_auth_headers):
    grant(db, rol_admin, VER, GESTIONAR)
    return admin_auth_headers


def rows(engine, sql: str, **params):
    with engine.connect() as conn:
        return conn.execute(text(sql), params).mappings().all()


def worker_state(engine, handler: str):
    found = rows(engine, "SELECT state FROM worker_job_state WHERE name = :n", n=handler)
    return found[0]["state"] if found else None


class TestContract:
    def test_the_permission_codes_are_the_catalog_ones(self) -> None:
        assert ml_publications_admin.PERMISO_VER == VER
        assert ml_publications_admin.PERMISO_GESTIONAR == GESTIONAR

    @pytest.mark.parametrize("method, path, body", ROUTES)
    def test_every_route_requires_authentication(self, client, pg, method, path, body) -> None:
        response = getattr(client, method)(BASE + path, **({"json": body} if body is not None else {}))
        assert response.status_code in (401, 403)

    @pytest.mark.parametrize("method, path, body", ROUTES)
    def test_a_user_without_any_ml_ops_permission_gets_403_on_every_route(
        self, client, pg, auth_headers, method, path, body
    ) -> None:
        response = getattr(client, method)(
            BASE + path, headers=auth_headers, **({"json": body} if body is not None else {})
        )
        assert response.status_code == 403

    @pytest.mark.parametrize("method, path, body", [r for r in ROUTES if r[0] != "get"])
    def test_the_reader_cannot_write(self, client, pg, reader, method, path, body) -> None:
        response = getattr(client, method)(BASE + path, headers=reader, **({"json": body} if body is not None else {}))
        assert response.status_code == 403
        assert rows(pg, "SELECT 1 FROM ml_pub_settings") == []
        assert rows(pg, "SELECT 1 FROM ml_pub_refresh_queue") == []
        assert rows(pg, "SELECT 1 FROM worker_job_state") == []

    def test_the_three_mutating_routes_are_post_or_put_and_nothing_deletes(self) -> None:
        verbs = {method for route in ml_publications_admin.router.routes for method in getattr(route, "methods", set())}
        assert verbs == {"GET", "PUT", "POST"}

    def test_the_router_is_mounted_and_openapi_lists_every_path(self, client) -> None:
        paths = client.get("/api/openapi.json").json()["paths"]

        assert set(paths[BASE + "/settings"]) == {"get"}
        assert set(paths[BASE + "/settings/{key}"]) == {"put"}
        assert set(paths[BASE + "/status"]) == {"get"}
        assert set(paths[BASE + "/enqueue"]) == {"post"}
        assert set(paths[BASE + "/jobs/{job}/request"]) == {"post"}

    def test_the_job_names_are_the_registered_handlers(self) -> None:
        from app.workers.registry import ML_PUBLICATIONS_REGISTRY

        # `ml_ads.ingest` and `ml_billing.sweep` are gated by env flags (ML_ADS_ENABLED, ML_BILLING_ENABLED), not by an
        # admin setting: they have no admin job.
        env_gated = {"ml_ads.ingest", "ml_billing.sweep"}
        registered = {h.name for h in ML_PUBLICATIONS_REGISTRY if h.name not in env_gated}
        assert {handler for handler, _ in admin.JOBS.values()} == registered


class TestStatus:
    def test_an_empty_store_answers_200_with_zeros_and_nulls(self, client, pg, reader) -> None:
        response = client.get(f"{BASE}/status", headers=reader)

        assert response.status_code == 200
        body = response.json()
        assert body["sections_failed"] == []
        assert body["items"]["total"] == 0 and body["queue"]["parked_total"] == 0
        assert body["lag_p95_seconds_24h"] is None and body["freshness"]["items"]["p50_age_seconds"] is None
        assert {job["job"] for job in body["jobs"]} == set(admin.JOBS)
        assert all(job["disabled"] for job in body["jobs"])

    def test_it_writes_nothing_and_calls_no_ml(self, client, pg, reader) -> None:
        statements: list[str] = []

        @event.listens_for(pg, "before_cursor_execute")
        def capture(conn, cursor, statement, parameters, context, executemany):
            statements.append(" ".join(statement.split()).upper())

        tables = ("ml_items", "ml_pub_refresh_queue", "ml_pub_settings", "ml_change_log", "worker_job_state")
        before = {t: len(rows(pg, f"SELECT 1 FROM {t}")) for t in tables}
        statements.clear()

        assert client.get(f"{BASE}/status", headers=reader).status_code == 200

        assert {t: len(rows(pg, f"SELECT 1 FROM {t}")) for t in tables} == before
        assert "SET LOCAL STATEMENT_TIMEOUT = '5S'" in statements
        assert not [s for s in statements if s.startswith(("INSERT", "UPDATE", "DELETE", "TRUNCATE"))]

    def test_a_job_error_that_is_not_text_does_not_break_the_report(self, client, pg, reader) -> None:
        with pg.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO worker_job_state (name, detail) VALUES "
                    "('ml_publications.refresh', CAST('{\"error\": {\"code\": 7}}' AS jsonb))"
                )
            )

        response = client.get(f"{BASE}/status", headers=reader)

        assert response.status_code == 200
        refresh = next(job for job in response.json()["jobs"] if job["job"] == "refresh")
        assert "7" in refresh["last_error"]

    def test_it_reports_a_parked_entry_with_its_error(self, client, pg, reader) -> None:
        with pg.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO ml_pub_refresh_queue (kind, entity_id, lane, attempts, last_error, parked_at) "
                    "VALUES ('item', 'MLA9', 3, 8, 'http_500: boom', now())"
                )
            )

        parked = client.get(f"{BASE}/status", headers=reader).json()["queue"]["parked"]

        assert [(p["entity_id"], p["last_error"]) for p in parked] == [("MLA9", "http_500: boom")]


class TestSettings:
    def test_it_lists_every_allow_listed_key_with_its_effective_value_and_source(self, client, pg, reader) -> None:
        settings_store.set_setting("refresh.enabled", True, "test")

        body = client.get(f"{BASE}/settings", headers=reader).json()
        by_key = {row["key"]: row for row in body["settings"]}

        assert set(by_key) == set(settings_store.SETTING_DEFS)
        assert (by_key["refresh.enabled"]["value"], by_key["refresh.enabled"]["source"]) == (True, "db")
        assert (by_key["sweep.enabled"]["value"], by_key["sweep.enabled"]["source"]) == (False, "env")
        assert body["kill_switch"] is False

    def test_the_kill_switch_shows_as_the_source_of_every_flag(self, client, pg, reader, monkeypatch) -> None:
        monkeypatch.setattr(settings, "ML_PUB_KILL_SWITCH", True)

        body = client.get(f"{BASE}/settings", headers=reader).json()
        flag = next(row for row in body["settings"] if row["key"] == "refresh.enabled")

        assert body["kill_switch"] is True and (flag["value"], flag["source"]) == (False, "kill_switch")

    def test_put_stores_the_value_with_the_author_and_answers_the_effective_one(self, client, pg, operator) -> None:
        response = client.put(f"{BASE}/settings/bundle_resources", json={"value": ["core", "prices"]}, headers=operator)

        assert response.status_code == 200
        assert response.json()["key"] == "bundle_resources" and response.json()["value"] == ["core", "prices"]
        assert response.json()["source"] == "db"
        stored = rows(pg, "SELECT value, updated_by FROM ml_pub_settings WHERE key = 'bundle_resources'")[0]
        assert stored["value"] == ["core", "prices"] and stored["updated_by"] == "user:adminuser"

    def test_an_unknown_key_is_404_and_writes_nothing(self, client, pg, operator) -> None:
        response = client.put(f"{BASE}/settings/not_a_setting", json={"value": True}, headers=operator)

        assert response.status_code == 404
        assert rows(pg, "SELECT 1 FROM ml_pub_settings") == []

    @pytest.mark.parametrize(
        "key, value",
        [
            ("refresh.enabled", "yes"),
            ("rate_per_sec", 500),
            ("sweep.statuses", ["closed"]),
            ("scan.next_mode", "everything"),
            ("bundle_resources", "core"),
        ],
    )
    def test_an_invalid_value_is_422_and_writes_nothing_and_requests_nothing(
        self, client, pg, operator, key, value
    ) -> None:
        response = client.put(f"{BASE}/settings/{key}", json={"value": value}, headers=operator)

        assert response.status_code == 422
        assert rows(pg, "SELECT 1 FROM ml_pub_settings") == []
        assert rows(pg, "SELECT 1 FROM worker_job_state") == []

    def test_a_body_without_value_is_422(self, client, pg, operator) -> None:
        assert client.put(f"{BASE}/settings/refresh.enabled", json={}, headers=operator).status_code == 422

    @pytest.mark.parametrize(
        "key, handler",
        [
            ("refresh.enabled", "ml_publications.refresh"),
            ("intake.enabled", "ml_publications.intake"),
            ("scan.enabled", "ml_publications.scan"),
            ("missed_feeds.enabled", "ml_publications.missed_feeds"),
            ("sweep.enabled", "ml_publications.sweep"),
            ("links.enabled", "ml_publications.relink"),
        ],
    )
    def test_turning_a_flag_on_marks_its_handler_requested_so_it_runs_on_the_next_pass(
        self, client, pg, operator, key, handler
    ) -> None:
        response = client.put(f"{BASE}/settings/{key}", json={"value": True}, headers=operator)

        assert response.status_code == 200 and response.json()["requested"] == handler
        assert worker_state(pg, handler) == "requested"
        assert settings_store.get_setting(key).value is True

    def test_turning_a_flag_off_requests_nothing(self, client, pg, operator) -> None:
        response = client.put(f"{BASE}/settings/refresh.enabled", json={"value": False}, headers=operator)

        assert response.status_code == 200 and response.json()["requested"] is None
        assert rows(pg, "SELECT 1 FROM worker_job_state") == []

    @pytest.mark.parametrize(
        "key, value", [("events.enabled", True), ("rate_per_sec", 3.5), ("bundle_resources", ["core"])]
    )
    def test_a_setting_without_a_handler_requests_nothing(self, client, pg, operator, key, value) -> None:
        response = client.put(f"{BASE}/settings/{key}", json={"value": value}, headers=operator)

        assert response.status_code == 200 and response.json()["requested"] is None
        assert rows(pg, "SELECT 1 FROM worker_job_state") == []

    def test_under_the_kill_switch_the_stored_flag_reads_off_and_says_why(
        self, client, pg, operator, monkeypatch
    ) -> None:
        monkeypatch.setattr(settings, "ML_PUB_KILL_SWITCH", True)

        body = client.put(f"{BASE}/settings/refresh.enabled", json={"value": True}, headers=operator).json()

        assert (body["value"], body["source"]) == (False, "kill_switch")
        assert body["requested"] is None  # the handler would only report disabled: no mark that waits for later
        assert rows(pg, "SELECT 1 FROM worker_job_state") == []
        assert rows(pg, "SELECT value FROM ml_pub_settings WHERE key = 'refresh.enabled'")[0]["value"] is True


class TestEnqueue:
    ITEM = "MLA935110613"

    def post(self, client, headers, **body):
        return client.post(f"{BASE}/enqueue", json=body, headers=headers)

    def test_entries_go_in_at_lane_zero_and_the_operator_is_told_processing_is_off(self, client, pg, operator) -> None:
        response = self.post(client, operator, item_ids=[self.ITEM, "MLA934406852", self.ITEM])

        assert response.status_code == 200
        body = response.json()
        assert (body["enqueued"], body["lane"], body["refresh_enabled"]) == (2, 0, False)
        assert "refresh.enabled" in body["note"]
        queued = rows(pg, "SELECT kind, entity_id, lane, resources FROM ml_pub_refresh_queue ORDER BY entity_id")
        assert [(q["kind"], q["entity_id"], q["lane"], list(q["resources"])) for q in queued] == [
            ("item", "MLA934406852", 0, ["bundle"]),
            ("item", self.ITEM, 0, ["bundle"]),
        ]

    def test_with_refresh_on_the_response_says_processing_is_on(self, client, pg, operator) -> None:
        settings_store.set_setting("refresh.enabled", True, "test")

        body = self.post(client, operator, item_ids=[self.ITEM]).json()

        assert body["refresh_enabled"] is True and body["note"] is None

    def test_enqueueing_again_collapses_into_the_same_entry(self, client, pg, operator) -> None:
        self.post(client, operator, item_ids=[self.ITEM])
        self.post(client, operator, item_ids=[self.ITEM])

        assert len(rows(pg, "SELECT 1 FROM ml_pub_refresh_queue")) == 1

    def test_requested_resources_missing_from_bundle_resources_are_reported(self, client, pg, operator) -> None:
        body = self.post(client, operator, item_ids=[self.ITEM], resources=["prices", "description", "core"]).json()

        assert body["missing_from_bundle_resources"] == ["description", "prices"]

        settings_store.set_setting("bundle_resources", ["core", "prices", "description"], "test")
        body = self.post(client, operator, item_ids=[self.ITEM], resources=["prices", "description"]).json()

        assert body["missing_from_bundle_resources"] == []

    def test_the_default_bundle_request_reports_nothing_missing(self, client, pg, operator) -> None:
        assert self.post(client, operator, item_ids=[self.ITEM]).json()["missing_from_bundle_resources"] == []

    def test_a_hundred_ids_are_accepted_and_a_hundred_and_one_are_not(self, client, pg, operator) -> None:
        ids = [f"MLA{n}" for n in range(1, 102)]

        assert self.post(client, operator, item_ids=ids[:100]).status_code == 200
        assert len(rows(pg, "SELECT 1 FROM ml_pub_refresh_queue")) == 100
        assert self.post(client, operator, item_ids=ids).status_code == 422
        assert len(rows(pg, "SELECT 1 FROM ml_pub_refresh_queue")) == 100

    @pytest.mark.parametrize(
        "body",
        [
            {"item_ids": []},
            {"item_ids": ["not-an-item"]},
            {"item_ids": ["MLA1", "mla2"]},
            {"item_ids": ["MLA1"], "resources": ["not_a_resource"]},
            {"item_ids": ["MLA1"], "resources": []},
            {},
        ],
    )
    def test_a_malformed_request_is_422_and_enqueues_nothing(self, client, pg, operator, body) -> None:
        assert client.post(f"{BASE}/enqueue", json=body, headers=operator).status_code == 422
        assert rows(pg, "SELECT 1 FROM ml_pub_refresh_queue") == []


class TestJobRequest:
    def post(self, client, headers, job: str, body=None):
        return client.post(
            f"{BASE}/jobs/{job}/request", **({"json": body} if body is not None else {}), headers=headers
        )

    @pytest.mark.parametrize("job", sorted(admin.JOBS))
    def test_it_sets_the_state_to_requested(self, client, pg, operator, job) -> None:
        response = self.post(client, operator, job)

        handler = admin.JOBS[job][0]
        assert response.status_code == 200
        assert (response.json()["job"], response.json()["handler"], response.json()["requested"]) == (
            job,
            handler,
            True,
        )
        assert worker_state(pg, handler) == "requested"

    def test_the_full_handler_name_is_accepted_too(self, client, pg, operator) -> None:
        assert self.post(client, operator, "ml_publications.sweep").status_code == 200
        assert worker_state(pg, "ml_publications.sweep") == "requested"

    def test_requesting_twice_keeps_one_row_and_keeps_the_last_run_columns(self, client, pg, operator) -> None:
        with pg.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO worker_job_state (name, last_run_at, state) VALUES ('ml_publications.refresh', now(), NULL)"
                )
            )

        self.post(client, operator, "refresh")
        self.post(client, operator, "refresh")

        found = rows(pg, "SELECT state, last_run_at FROM worker_job_state")
        assert len(found) == 1 and found[0]["state"] == "requested" and found[0]["last_run_at"] is not None

    def test_the_response_says_when_the_job_is_off_so_the_request_waits(self, client, pg, operator) -> None:
        body = self.post(client, operator, "scan").json()
        assert body["enabled"] is False and "scan.enabled" in body["note"]

        settings_store.set_setting("scan.enabled", True, "test")
        body = self.post(client, operator, "scan").json()
        assert body["enabled"] is True and body["note"] is None

    def test_the_shared_verify_handler_is_enabled_when_either_of_its_flags_is_on(self, client, pg, operator) -> None:
        # asked by its handler name (what the docs use), `verify` and `divergence` are the same request
        body = self.post(client, operator, "ml_publications.verify").json()
        assert body["enabled"] is False
        assert "verify.enabled" in body["note"] and "divergence.enabled" in body["note"]

        settings_store.set_setting("divergence.enabled", True, "test")
        body = self.post(client, operator, "ml_publications.verify").json()
        assert body["enabled"] is True and body["note"] is None

    def test_an_unknown_job_is_404_and_writes_nothing(self, client, pg, operator) -> None:
        assert self.post(client, operator, "nonexistent").status_code == 404
        assert rows(pg, "SELECT 1 FROM worker_job_state") == []

    @pytest.mark.parametrize("mode", ["full", "rescan"])
    def test_scan_mode_is_written_with_the_request_in_one_transaction(self, client, pg, operator, mode) -> None:
        response = self.post(client, operator, "scan", {"mode": mode})

        assert response.status_code == 200 and response.json()["mode"] == mode
        stored = rows(pg, "SELECT value, updated_by FROM ml_pub_settings WHERE key = 'scan.next_mode'")[0]
        assert (stored["value"], stored["updated_by"]) == (mode, "user:adminuser")
        assert worker_state(pg, "ml_publications.scan") == "requested"

    def test_a_refused_scan_mode_is_422_not_500(self, client, pg, operator, monkeypatch) -> None:
        def refuse(*args, **kwargs):
            raise admin.InvalidSetting("invalid value for ml_pub setting 'scan.next_mode'")

        monkeypatch.setattr(admin, "request_job", refuse)

        assert self.post(client, operator, "scan", {"mode": "full"}).status_code == 422

    def test_under_the_kill_switch_the_request_is_kept_and_the_note_says_it_waits(
        self, client, pg, operator, monkeypatch
    ) -> None:
        monkeypatch.setattr(settings, "ML_PUB_KILL_SWITCH", True)

        body = self.post(client, operator, "refresh").json()

        assert body["enabled"] is False and "ML_PUB_KILL_SWITCH" in body["note"]
        assert worker_state(pg, "ml_publications.refresh") == "requested"

    def test_without_a_mode_the_scan_setting_is_left_alone(self, client, pg, operator) -> None:
        self.post(client, operator, "scan")

        assert rows(pg, "SELECT 1 FROM ml_pub_settings") == []

    @pytest.mark.parametrize("job, body", [("refresh", {"mode": "full"}), ("scan", {"mode": "everything"})])
    def test_a_mode_that_does_not_apply_or_is_invalid_is_422_and_changes_nothing(
        self, client, pg, operator, job, body
    ) -> None:
        response = self.post(client, operator, job, body)

        assert response.status_code == 422
        assert rows(pg, "SELECT 1 FROM ml_pub_settings") == [] and rows(pg, "SELECT 1 FROM worker_job_state") == []

    def test_it_never_wakes_the_worker_through_notify(self, client, pg, operator) -> None:
        statements: list[str] = []

        @event.listens_for(pg, "before_cursor_execute")
        def capture(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement.lower())

        self.post(client, operator, "refresh")

        assert statements and not [s for s in statements if "notify" in s]
