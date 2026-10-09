"""P8b.T3: `scripts/measure_pubml_p8b.py`, the read-only measurement of the events and history endpoints (R6).

Standalone like the P8a script (stdlib only for the measurement; the app is imported lazily, and only to mint its own
token and pick publications), so it is loaded by path. A throwaway HTTP server stands in for the API.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "measure_pubml_p8b.py"


@pytest.fixture(scope="module")
def script():
    spec = importlib.util.spec_from_file_location("measure_pubml_p8b", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolves its annotations through sys.modules
    spec.loader.exec_module(module)
    return module


class Api:
    """A fake events/history endpoint: a first page with a cursor, a second one without, and a `Server-Timing`."""

    def __init__(self, status: int = 200, enabled: bool = True) -> None:
        self.requests: list[tuple[str, str, str | None]] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 -- http.server API
                outer.requests.append(("GET", self.path, self.headers.get("Authorization")))
                query = parse_qs(urlparse(self.path).query)
                second = "cursor" in query
                if urlparse(self.path).path.endswith("/events"):
                    rows = [{"id": 1}, {"id": 2}] if enabled else []
                    body = {"enabled": enabled, "events": rows}
                else:
                    body = {"entries": [{"id": 1, "business": [], "technical": []}]}
                body["next_cursor"] = None if second else "2026-10-08T12:00:00.000000Z|9"
                raw = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Server-Timing", "events;dur=7.5")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_POST(self) -> None:  # noqa: N802
                outer.requests.append(("POST", self.path, None))
                self.send_response(405)
                self.end_headers()

            def log_message(self, *args) -> None:
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}/api"

    def __enter__(self) -> "Api":
        self.thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self.server.shutdown()
        self.server.server_close()


def paths(api: Api) -> set[str]:
    return {urlparse(p).path for _m, p, _a in api.requests}


class TestDefaults:
    def test_the_default_base_url_is_the_production_port(self, script) -> None:
        assert script.DEFAULT_BASE_URL == "http://localhost:8002/api"

    def test_the_budget_and_runs(self, script) -> None:
        assert script.BUDGET_MS == 100.0 and script.RUNS == 20

    def test_the_scenarios_per_endpoint_are_the_busiest_twice_and_the_most_recent(self, script) -> None:
        scenarios = script.build_scenarios(
            {"events": "MLA9", "history": "MLA8"}, {"events": "MLA2", "history": "MLA3"}, None, None
        )
        assert [(s.endpoint, s.item_id, s.deep) for s in scenarios] == [
            ("events", "MLA9", False),
            ("events", "MLA9", True),
            ("events", "MLA2", False),
            ("history", "MLA8", False),
            ("history", "MLA8", True),
            ("history", "MLA3", False),
        ]

    def test_the_busiest_is_not_measured_again_as_the_most_recent(self, script) -> None:
        scenarios = script.build_scenarios({"events": "MLA9"}, {"events": "MLA9"}, None, None)
        assert [(s.item_id, s.deep) for s in scenarios] == [("MLA9", False), ("MLA9", True)]
        assert script.build_scenarios({}, {}, None, None) == []

    def test_an_explicit_mla_replaces_the_busiest_of_both_endpoints(self, script) -> None:
        scenarios = script.build_scenarios({"events": "MLA9", "history": "MLA8"}, {}, "MLA5", None)
        assert {s.item_id for s in scenarios} == {"MLA5"} and {s.endpoint for s in scenarios} == {"events", "history"}


class TestPureHelpers:
    def test_percentile_is_nearest_rank(self, script) -> None:
        samples = [float(n) for n in range(1, 21)]
        assert script.percentile(samples, 50) == 10.0 and script.percentile(samples, 95) == 19.0

    def test_server_timing_is_parsed_into_stages(self, script) -> None:
        assert script.parse_server_timing("events;dur=1.5, other;dur=4") == {"events": 1.5, "other": 4.0}
        assert script.parse_server_timing(None) == {}

    def test_the_user_must_hold_the_permission(self, script) -> None:
        users = {"nobody": {"x"}, "viewer": {"ml_ops.ver", "x"}}
        assert script.pick_user(list(users), lambda name: users[name]) == "viewer"
        assert script.pick_user(["nobody"], lambda name: users[name]) is None

    def test_a_user_whose_permissions_cannot_be_read_is_skipped(self, script) -> None:
        def perms(name: str):
            if name == "broken":
                raise RuntimeError("boom")
            return {"ml_ops.ver"}

        failures: list[str] = []
        assert script.pick_user(["broken", "ok"], perms, failures) == "ok"
        assert failures == ["broken: boom"]


class TestRun:
    def test_every_scenario_is_one_warmup_plus_twenty_get_requests_with_the_token(self, script, capsys) -> None:
        with Api() as api:
            code = script.main(["--base-url", api.url, "--token", "secret", "--mla", "MLA9", "--recent-mla", "MLA3"])
        out = capsys.readouterr().out
        assert code == 0
        measured = 6  # events and history: busiest, busiest page 2, most recent
        deep_setup = 2  # the first page of each busiest publication, fetched once to get its cursor
        assert len(api.requests) == measured * (script.RUNS + 1) + deep_setup
        assert {method for method, _p, _a in api.requests} == {"GET"}
        assert {auth for _m, _p, auth in api.requests} == {"Bearer secret"}
        assert paths(api) == {
            f"/api/ml-publications/view/items/{mla}/{endpoint}"
            for mla in ("MLA9", "MLA3")
            for endpoint in ("events", "history")
        }
        assert "events_ms=7.5" in out and "RESULT: PASS" in out
        assert "rows=2 more=True" in out and "rows=2 more=False" in out

    def test_the_second_page_is_asked_with_the_cursor_the_first_one_returned(self, script) -> None:
        with Api() as api:
            script.main(["--base-url", api.url, "--token", "t", "--mla", "MLA9"])
        with_cursor = [p for _m, p, _a in api.requests if "cursor" in p]
        assert with_cursor and all("cursor=2026-10-08T12%3A00%3A00.000000Z%7C9" in p for p in with_cursor)
        assert all("limit=50" in p for p in with_cursor if "/events" in p)
        assert all("limit=20" in p for p in with_cursor if "/history" in p)

    def test_over_the_budget_fails_the_run(self, script, capsys) -> None:
        with Api() as api:
            code = script.main(["--base-url", api.url, "--token", "t", "--mla", "MLA9", "--budget-ms", "0.0001"])
        assert code == 1 and "FAIL" in capsys.readouterr().out

    def test_the_flag_being_off_is_said_because_only_the_lookup_was_timed(self, script, capsys) -> None:
        with Api(enabled=False) as api:
            script.main(["--base-url", api.url, "--token", "t", "--mla", "MLA9"])
        assert "events.enabled is off" in capsys.readouterr().out

    def test_an_http_error_is_reported_and_fails_the_run(self, script, capsys) -> None:
        with Api(status=404) as api:
            code = script.main(["--base-url", api.url, "--token", "t", "--mla", "MLA9"])
        assert code == 1 and "HTTP 404" in capsys.readouterr().out

    def test_the_token_may_come_from_the_environment(self, script, monkeypatch) -> None:
        monkeypatch.setenv("PUBML_TOKEN", "from-env")
        with Api() as api:
            script.main(["--base-url", api.url, "--mla", "MLA9"])
        assert {auth for _m, _p, auth in api.requests} == {"Bearer from-env"}


class TestZeroConfig:
    def test_without_a_token_it_mints_its_own_and_picks_the_publications(self, script, monkeypatch, capsys) -> None:
        monkeypatch.delenv("PUBML_TOKEN", raising=False)
        monkeypatch.setattr(
            script,
            "auto_config",
            lambda: script.AutoConfig("tok-secret-123", "ana", {"events": "MLA77", "history": "MLA78"}, {}),
        )
        with Api() as api:
            code = script.main(["--base-url", api.url])
        out = capsys.readouterr().out
        assert code == 0
        assert {auth for _m, _p, auth in api.requests} == {"Bearer tok-secret-123"}
        assert {p.split("/")[-2] for p in paths(api)} == {"MLA77", "MLA78"}
        assert "ana" in out and "tok-secret-123" not in out  # the token is never printed

    def test_it_stops_with_a_clear_message_when_no_user_can_be_found(self, script, monkeypatch, capsys) -> None:
        monkeypatch.delenv("PUBML_TOKEN", raising=False)
        monkeypatch.setattr(script, "auto_config", lambda: None)
        assert script.main(["--base-url", "http://127.0.0.1:1/api"]) == 2
        assert "ml_ops.ver" in capsys.readouterr().out

    def test_it_stops_with_a_clear_message_when_no_publication_can_be_found(self, script, monkeypatch, capsys) -> None:
        monkeypatch.delenv("PUBML_TOKEN", raising=False)
        monkeypatch.setattr(script, "auto_config", lambda: script.AutoConfig("tok", "ana", {}, {}))
        assert script.main(["--base-url", "http://127.0.0.1:1/api"]) == 2
        assert "--mla" in capsys.readouterr().out

    def test_the_app_is_imported_from_the_working_directory_and_only_when_needed(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        assert "sys.path.insert(0, os.getcwd())" in source
        top = source.split("def auto_config")[0]
        assert not re.search(r"^(from|import) app\b", top, re.MULTILINE)  # lazy: the measurement needs no app


class TestReadOnly:
    def test_the_script_can_only_issue_get_requests(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        assert not re.search(r"method\s*=\s*[\"'](POST|PUT|PATCH|DELETE)", source, re.IGNORECASE)
        assert not re.search(r"\.(post|put|patch|delete)\(", source)

    def test_the_database_session_is_read_only_and_never_commits(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        assert "SET TRANSACTION READ ONLY" in source
        assert ".commit(" not in source and ".add(" not in source
        assert not re.search(
            r"\b(INSERT|UPDATE|DELETE|CREATE|DROP|ALTER|TRUNCATE)\b\s", source.split("def auto_config")[1]
        )
