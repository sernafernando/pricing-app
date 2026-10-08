"""P6c.T3: `scripts/measure_pubml_p6c.py`, the read-only measurement of the variation sub-rows (R6).

Standalone like the P6 script (stdlib only for the measurement; the app is imported lazily, and only to mint its own
token and pick publications), so it is loaded by path. A throwaway HTTP server stands in for the API.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "measure_pubml_p6c.py"


@pytest.fixture(scope="module")
def script():
    spec = importlib.util.spec_from_file_location("measure_pubml_p6c", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolves its annotations through sys.modules
    spec.loader.exec_module(module)
    return module


class Api:
    """A fake sub-rows endpoint: answers variations with cost and markup and a `Server-Timing` header."""

    def __init__(self, status: int = 200, margin: bool = True, rows: int = 3) -> None:
        self.requests: list[tuple[str, str, str | None]] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 -- http.server API
                outer.requests.append(("GET", self.path, self.headers.get("Authorization")))
                sub_rows = [{"variation_id": n} for n in range(rows)]
                body = {"item_id": "MLA1", "can_see_margin": margin, "variations": sub_rows}
                if margin:
                    body["variations"] = [{**r, "costo": {"amount": 1.0}, "markup": {"value": 5.0}} for r in sub_rows]
                    body["ads"] = {
                        "available": False,
                        "reason": "provider_missing",
                        "requested": False,
                        "applied": False,
                    }
                raw = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Server-Timing", "variations;dur=12.5")
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


class TestDefaults:
    def test_the_default_base_url_is_the_production_port(self, script) -> None:
        assert script.DEFAULT_BASE_URL == "http://localhost:8002/api"

    def test_the_budget_and_runs(self, script) -> None:
        assert script.BUDGET_MS == 150.0 and script.RUNS == 20

    def test_the_scenarios_are_the_biggest_publication_a_small_one_and_the_ads_variant(self, script) -> None:
        scenarios = script.build_scenarios("MLA9", "MLA2", date(2026, 10, 8))
        assert [s.item_id for s in scenarios] == ["MLA9", "MLA2", "MLA9"]
        ads = scenarios[-1].params
        assert ads == {"restar_publicidad": "true", "ads_desde": "2026-09-08", "ads_hasta": "2026-10-07"}
        assert scenarios[0].params == {} == scenarios[1].params

    def test_a_small_publication_equal_to_the_big_one_is_not_measured_twice(self, script) -> None:
        assert [s.item_id for s in script.build_scenarios("MLA9", "MLA9", date(2026, 10, 8))] == ["MLA9", "MLA9"]
        assert [s.item_id for s in script.build_scenarios("MLA9", None, date(2026, 10, 8))] == ["MLA9", "MLA9"]


class TestPureHelpers:
    def test_percentile_is_nearest_rank(self, script) -> None:
        samples = [float(n) for n in range(1, 21)]
        assert script.percentile(samples, 50) == 10.0 and script.percentile(samples, 95) == 19.0

    def test_server_timing_is_parsed_into_stages(self, script) -> None:
        assert script.parse_server_timing("variations;dur=1.5, other;dur=4") == {"variations": 1.5, "other": 4.0}
        assert script.parse_server_timing(None) == {}

    def test_the_user_must_hold_both_permissions(self, script) -> None:
        users = {
            "viewer": {"ml_ops.ver"},
            "margin": {"ml_metricas.ver_ganancia"},
            "both": {"ml_ops.ver", "ml_metricas.ver_ganancia", "x"},
        }
        assert script.pick_user(list(users), lambda name: users[name]) == "both"
        assert script.pick_user(["viewer", "margin"], lambda name: users[name]) is None

    def test_a_user_whose_permissions_cannot_be_read_is_skipped(self, script) -> None:
        def perms(name: str):
            if name == "broken":
                raise RuntimeError("boom")
            return {"ml_ops.ver", "ml_metricas.ver_ganancia"}

        assert script.pick_user(["broken", "ok"], perms) == "ok"

    def test_the_errors_of_the_skipped_users_are_reported_to_the_caller(self, script) -> None:
        def perms(name: str):
            raise RuntimeError("boom")

        failures: list[str] = []
        assert script.pick_user(["broken"], perms, failures) is None
        assert failures == ["broken: boom"]


class TestRun:
    def test_every_scenario_is_one_warmup_plus_twenty_get_requests_with_the_token(self, script, capsys) -> None:
        with Api() as api:
            code = script.main(["--base-url", api.url, "--token", "secret", "--mla", "MLA9", "--small-mla", "MLA2"])
        out = capsys.readouterr().out
        assert code == 0
        assert len(api.requests) == 3 * (script.RUNS + 1)
        assert {method for method, _p, _a in api.requests} == {"GET"}
        assert {auth for _m, _p, auth in api.requests} == {"Bearer secret"}
        assert {urlparse(p).path for _m, p, _a in api.requests} == {
            "/api/ml-publications/view/items/MLA9/variations",
            "/api/ml-publications/view/items/MLA2/variations",
        }
        assert "sub_rows=3" in out and "RESULT: PASS" in out

    def test_the_ads_scenario_sends_the_period(self, script) -> None:
        with Api() as api:
            script.main(["--base-url", api.url, "--token", "t", "--mla", "MLA9"])
        queries = [parse_qs(urlparse(path).query) for _m, path, _a in api.requests]
        assert any(q.get("restar_publicidad") == ["true"] and "ads_desde" in q and "ads_hasta" in q for q in queries)

    def test_the_server_side_stage_and_the_ads_block_are_reported(self, script, capsys) -> None:
        with Api() as api:
            script.main(["--base-url", api.url, "--token", "t", "--mla", "MLA9"])
        out = capsys.readouterr().out
        assert "variations_ms=12.5" in out and "ads: available=False reason=provider_missing" in out

    def test_over_the_budget_fails_the_run(self, script, capsys) -> None:
        with Api() as api:
            code = script.main(["--base-url", api.url, "--token", "t", "--mla", "MLA9", "--budget-ms", "0.0001"])
        assert code == 1 and "FAIL" in capsys.readouterr().out

    def test_a_response_without_cost_and_markup_means_the_token_cannot_see_margins(self, script, capsys) -> None:
        with Api(margin=False) as api:
            code = script.main(["--base-url", api.url, "--token", "t", "--mla", "MLA9"])
        assert code == 1 and "ml_metricas.ver_ganancia" in capsys.readouterr().out

    def test_a_publication_without_sub_rows_fails_the_run(self, script, capsys) -> None:
        with Api(rows=0) as api:
            code = script.main(["--base-url", api.url, "--token", "t", "--mla", "MLA9"])
        assert code == 1 and "no sub-rows" in capsys.readouterr().out

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
        monkeypatch.setattr(script, "auto_config", lambda: script.AutoConfig("tok-secret-123", "ana", "MLA77", "MLA78"))
        with Api() as api:
            code = script.main(["--base-url", api.url])
        out = capsys.readouterr().out
        assert code == 0
        assert {auth for _m, _p, auth in api.requests} == {"Bearer tok-secret-123"}
        assert {urlparse(p).path.split("/")[-2] for _m, p, _a in api.requests} == {"MLA77", "MLA78"}
        assert "ana" in out and "tok-secret-123" not in out  # the token is never printed

    def test_it_stops_with_a_clear_message_when_no_user_can_be_found(self, script, monkeypatch, capsys) -> None:
        monkeypatch.delenv("PUBML_TOKEN", raising=False)
        monkeypatch.setattr(script, "auto_config", lambda: None)
        assert script.main(["--base-url", "http://127.0.0.1:1/api"]) == 2
        assert "ml_metricas.ver_ganancia" in capsys.readouterr().out

    def test_it_stops_with_a_clear_message_when_no_publication_has_variations(
        self, script, monkeypatch, capsys
    ) -> None:
        monkeypatch.delenv("PUBML_TOKEN", raising=False)
        monkeypatch.setattr(script, "auto_config", lambda: script.AutoConfig("tok", "ana", None, None))
        assert script.main(["--base-url", "http://127.0.0.1:1/api"]) == 2
        assert "--mla" in capsys.readouterr().out

    def test_an_explicit_mla_wins_over_the_picked_one(self, script, monkeypatch) -> None:
        monkeypatch.delenv("PUBML_TOKEN", raising=False)
        monkeypatch.setattr(script, "auto_config", lambda: script.AutoConfig("tok", "ana", "MLA77", "MLA78"))
        with Api() as api:
            script.main(["--base-url", api.url, "--mla", "MLA5"])
        paths = {urlparse(p).path for _m, p, _a in api.requests}
        assert "/api/ml-publications/view/items/MLA5/variations" in paths
        assert "/api/ml-publications/view/items/MLA77/variations" not in paths

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
