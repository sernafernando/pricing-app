"""P5.T9: `scripts/measure_pubml_p5.py`, the read-only measurement of the Publicaciones list (R6).

The script is standalone (stdlib only: it runs on the server with a bare python3), so it is loaded by path.
A throwaway HTTP server stands in for the API and records every request it receives.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "measure_pubml_p5.py"


@pytest.fixture(scope="module")
def script():
    spec = importlib.util.spec_from_file_location("measure_pubml_p5", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolves its annotations through sys.modules
    spec.loader.exec_module(module)
    return module


class Api:
    """A fake list endpoint: answers a page and a `Server-Timing` header, records what it was asked."""

    def __init__(self, status: int = 200) -> None:
        self.requests: list[tuple[str, str, str | None]] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 -- http.server API
                outer.requests.append(("GET", self.path, self.headers.get("Authorization")))
                body = json.dumps(
                    {
                        "items": [{"item_id": "MLA1"}],
                        "total": 24600,
                        "data_state": {"degraded": True, "degradations": [{"code": "flag_disabled", "flag": "events"}]},
                    }
                ).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Server-Timing", "flags;dur=1.5, list;dur=20.0, status;dur=0.5")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

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


class TestPureHelpers:
    def test_percentile_is_nearest_rank(self, script) -> None:
        samples = [float(n) for n in range(1, 21)]  # 1..20
        assert script.percentile(samples, 50) == 10.0
        assert script.percentile(samples, 95) == 19.0
        assert script.percentile([7.0], 95) == 7.0

    def test_percentile_does_not_need_sorted_input(self, script) -> None:
        assert script.percentile([5.0, 1.0, 3.0], 50) == 3.0

    def test_server_timing_is_parsed_into_stages(self, script) -> None:
        assert script.parse_server_timing("flags;dur=1.5, list;dur=20.0, status;dur=0.5") == {
            "flags": 1.5,
            "list": 20.0,
            "status": 0.5,
        }
        assert script.parse_server_timing(None) == {}
        assert script.parse_server_timing("cache;desc=hit") == {}

    def test_the_budget_is_the_owner_one(self, script) -> None:
        assert script.BUDGET_MS == 500.0 and script.RUNS == 20


class TestRun:
    def test_every_scenario_is_one_warmup_plus_twenty_get_requests_with_the_token(self, script, capsys) -> None:
        with Api() as api:
            code = script.main(["--base-url", api.url, "--token", "secret"])
        out = capsys.readouterr().out
        assert code == 0
        scenarios = len(script.SCENARIOS)
        assert scenarios >= 5
        assert len(api.requests) == scenarios * (script.RUNS + 1)
        assert {method for method, _path, _auth in api.requests} == {"GET"}
        assert {auth for _m, _p, auth in api.requests} == {"Bearer secret"}
        paths = [path for _m, path, _a in api.requests]
        assert all(path.startswith("/api/ml-publications/view/items?") for path in paths)
        assert any("facets=true" in path for path in paths)
        assert any("q=" in path for path in paths)
        for scenario in script.SCENARIOS:
            assert scenario.name in out
        assert "p50" in out and "p95" in out

    def test_it_prints_the_server_side_stages_as_pubml_view_lines(self, script, capsys) -> None:
        with Api() as api:
            script.main(["--base-url", api.url, "--token", "t"])
        out = capsys.readouterr().out
        lines = [line for line in out.splitlines() if line.startswith("pubml.view ")]
        assert len(lines) == len(script.SCENARIOS)
        assert "list_ms=20.0" in lines[0] and "status_ms=0.5" in lines[0] and "endpoint=items" in lines[0]

    def test_the_gate_passes_under_the_budget_and_fails_over_it(self, script, capsys) -> None:
        with Api() as api:
            assert script.main(["--base-url", api.url, "--token", "t"]) == 0
            assert script.main(["--base-url", api.url, "--token", "t", "--budget-ms", "0.0001"]) == 1
        assert "FAIL" in capsys.readouterr().out

    def test_the_token_may_come_from_the_environment(self, script, monkeypatch) -> None:
        monkeypatch.setenv("PUBML_TOKEN", "from-env")
        with Api() as api:
            script.main(["--base-url", api.url])
        assert {auth for _m, _p, auth in api.requests} == {"Bearer from-env"}

    def test_it_refuses_to_run_without_a_token(self, script, monkeypatch, capsys) -> None:
        monkeypatch.delenv("PUBML_TOKEN", raising=False)
        assert script.main(["--base-url", "http://127.0.0.1:1/api"]) == 2
        assert "token" in capsys.readouterr().out.lower()

    def test_an_http_error_is_reported_and_fails_the_run(self, script, capsys) -> None:
        with Api(status=500) as api:
            code = script.main(["--base-url", api.url, "--token", "t"])
        assert code == 1
        assert "HTTP 500" in capsys.readouterr().out

    def test_the_data_state_and_total_are_reported_once(self, script, capsys) -> None:
        with Api() as api:
            script.main(["--base-url", api.url, "--token", "t"])
        out = capsys.readouterr().out
        assert "total=24600" in out and "flag_disabled:events" in out


class TestColdRequest:
    def test_the_first_warm_up_is_reported_because_it_pays_the_status_report(self, script, capsys) -> None:
        with Api() as api:
            script.main(["--base-url", api.url, "--token", "t"])
        out = capsys.readouterr().out
        (line,) = [line for line in out.splitlines() if line.startswith("cold first request")]
        assert "(status 0.5 ms)" in line  # the Server-Timing status stage of that first response


class TestReadOnly:
    def test_the_script_can_only_issue_get_requests(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        assert not re.search(r"method\s*=\s*[\"'](POST|PUT|PATCH|DELETE)", source, re.IGNORECASE)
        assert not re.search(r"\.(post|put|patch|delete)\(", source)

    def test_the_database_probe_opens_a_read_only_transaction(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        assert "SET TRANSACTION READ ONLY" in source
        assert not re.search(
            r"\b(INSERT|UPDATE|DELETE|CREATE|DROP|ALTER|TRUNCATE)\b", source.split("PROBE_SQL")[1][:600]
        )
