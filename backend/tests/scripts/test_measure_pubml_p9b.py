"""P9b.T3: `scripts/measure_pubml_p9b.py`, the read-only measurement of the KPI strip (R6).

Standalone like the other measurement scripts (stdlib only for the measurement; the app is imported lazily, and only
to mint its own token and pick a brand), so it is loaded by path. A throwaway HTTP server stands in for the API.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "measure_pubml_p9b.py"


@pytest.fixture(scope="module")
def script():
    spec = importlib.util.spec_from_file_location("measure_pubml_p9b", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolves its annotations through sys.modules
    spec.loader.exec_module(module)
    return module


class Api:
    """A fake strip endpoint with a `Server-Timing` header; records every request it receives."""

    def __init__(self, status: int = 200) -> None:
        self.requests: list[tuple[str, str, str | None]] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 -- http.server API
                outer.requests.append(("GET", self.path, self.headers.get("Authorization")))
                raw = json.dumps({"mla_count": 12, "kpis": {"units": {"value": 34}}}).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Server-Timing", "kpis;dur=7.5")
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
    def test_the_defaults(self, script) -> None:
        assert script.DEFAULT_BASE_URL == "http://localhost:8002/api"
        assert script.BUDGET_MS == 1000.0 and script.RUNS == 20  # the owner's budget: KPI strip p95 < 1 s

    def test_the_scenarios_are_the_store_twice_then_the_filters(self, script) -> None:
        names = [(s.name, s.params) for s in script.build_scenarios("TP-LINK")]
        assert names == [
            ("all, 30 days", {}),
            ("all, 90 days", {"periodo": "90"}),
            ("brand 'TP-LINK', 30 days", {"marcas": "TP-LINK"}),
            ("active, 30 days", {"estado": "active"}),
        ]
        assert [s.name for s in script.build_scenarios(None)] == ["all, 30 days", "all, 90 days", "active, 30 days"]


class TestPureHelpers:
    def test_percentile_is_nearest_rank(self, script) -> None:
        samples = [float(n) for n in range(1, 21)]
        assert script.percentile(samples, 50) == 10.0 and script.percentile(samples, 95) == 19.0

    def test_server_timing_is_parsed_into_stages(self, script) -> None:
        assert script.parse_server_timing("kpis;dur=1.5, other;dur=4") == {"kpis": 1.5, "other": 4.0}
        assert script.parse_server_timing(None) == {}

    def test_the_user_must_hold_both_permissions(self, script) -> None:
        users = {"ops": {"ml_ops.ver"}, "metricas": {"ml_metricas.ver"}, "both": {"ml_ops.ver", "ml_metricas.ver"}}
        assert script.pick_user(list(users), lambda name: users[name]) == "both"
        assert script.pick_user(["ops", "metricas"], lambda name: users[name]) is None

    def test_a_user_whose_permissions_cannot_be_read_is_skipped(self, script) -> None:
        def perms(name: str):
            if name == "broken":
                raise RuntimeError("boom")
            return {"ml_ops.ver", "ml_metricas.ver"}

        failures: list[str] = []
        assert script.pick_user(["broken", "ok"], perms, failures) == "ok"
        assert failures == ["broken: boom"]


class TestRun:
    def test_every_scenario_is_one_warmup_plus_twenty_get_requests_with_the_token(self, script, capsys) -> None:
        with Api() as api:
            code = script.main(["--base-url", api.url, "--token", "secret", "--marca", "TP-LINK"])
        out = capsys.readouterr().out
        assert code == 0
        assert len(api.requests) == 4 * (script.RUNS + 1)
        assert {method for method, _p, _a in api.requests} == {"GET"}
        assert {auth for _m, _p, auth in api.requests} == {"Bearer secret"}
        assert {urlparse(p).path for _m, p, _a in api.requests} == {"/api/ml-publications/view/kpis"}
        queries = [parse_qs(urlparse(p).query) for _m, p, _a in api.requests]
        assert {"periodo": ["90"]} in queries and {"marcas": ["TP-LINK"]} in queries
        assert "kpis_ms=7.5" in out and "mla_count=12 units=34" in out and "RESULT: PASS" in out

    def test_over_the_budget_fails_the_run(self, script, capsys) -> None:
        with Api() as api:
            code = script.main(["--base-url", api.url, "--token", "t", "--budget-ms", "0.0001"])
        assert code == 1 and "FAIL" in capsys.readouterr().out

    def test_an_http_error_is_reported_and_fails_the_run(self, script, capsys) -> None:
        with Api(status=403) as api:
            code = script.main(["--base-url", api.url, "--token", "t"])
        assert code == 1 and "HTTP 403" in capsys.readouterr().out

    def test_the_token_may_come_from_the_environment(self, script, monkeypatch) -> None:
        monkeypatch.setenv("PUBML_TOKEN", "from-env")
        with Api() as api:
            script.main(["--base-url", api.url])
        assert {auth for _m, _p, auth in api.requests} == {"Bearer from-env"}


class TestZeroConfig:
    def test_without_a_token_it_mints_its_own_and_picks_the_brand(self, script, monkeypatch, capsys) -> None:
        monkeypatch.delenv("PUBML_TOKEN", raising=False)
        monkeypatch.setattr(script, "auto_config", lambda: script.AutoConfig("tok-secret-123", "ana", "EPSON"))
        with Api() as api:
            code = script.main(["--base-url", api.url])
        out = capsys.readouterr().out
        assert code == 0 and "ana" in out and "tok-secret-123" not in out  # the token is never printed
        assert any("marcas=EPSON" in p for _m, p, _a in api.requests)

    def test_no_eligible_user_is_a_clear_exit(self, script, monkeypatch, capsys) -> None:
        monkeypatch.delenv("PUBML_TOKEN", raising=False)
        monkeypatch.setattr(script, "auto_config", lambda: None)
        assert script.main(["--base-url", "http://127.0.0.1:1/api"]) == 2
        assert "ml_metricas.ver" in capsys.readouterr().out
