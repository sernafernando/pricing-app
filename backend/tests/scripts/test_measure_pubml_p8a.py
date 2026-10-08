"""P8a.T4: `scripts/measure_pubml_p8a.py`, the read-only measurement of the publication detail (R6).

Standalone like the P6c script (stdlib only for the measurement; the app is imported lazily, and only to mint its own
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
from urllib.parse import urlparse

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "measure_pubml_p8a.py"


@pytest.fixture(scope="module")
def script():
    spec = importlib.util.spec_from_file_location("measure_pubml_p8a", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolves its annotations through sys.modules
    spec.loader.exec_module(module)
    return module


class Api:
    """A fake detail endpoint: answers the Resumen (with the breakdown when `margin`) and a `Server-Timing` header."""

    def __init__(self, status: int = 200, margin: bool = True, priced: bool = True) -> None:
        self.requests: list[tuple[str, str, str | None]] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 -- http.server API
                outer.requests.append(("GET", self.path, self.headers.get("Authorization")))
                body = {
                    "row": {"item_id": "MLA1"},
                    "links": [{"variation_id": 0}, {"variation_id": 11}],
                    "freshness": [{"resource": "items"}, {"resource": "stock"}, {"resource": "family"}],
                    "replenishment": {"status": "ok"},
                    "can_resync": False,
                }
                if margin:
                    body["markup_breakdown"] = {"markup": 5.0} if priced else None
                raw = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Server-Timing", "detail;dur=12.5")
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
        assert script.BUDGET_MS == 150.0 and script.RUNS == 20

    def test_the_scenarios_are_the_widest_publication_a_full_one_and_a_plain_one(self, script) -> None:
        scenarios = script.build_scenarios("MLA9", "MLA2", "MLA3")
        assert [s.item_id for s in scenarios] == ["MLA9", "MLA2", "MLA3"]
        assert all(s.params == {} for s in scenarios)

    def test_a_publication_found_twice_is_measured_once(self, script) -> None:
        assert [s.item_id for s in script.build_scenarios("MLA9", "MLA9", "MLA9")] == ["MLA9"]
        assert [s.item_id for s in script.build_scenarios("MLA9", None, "MLA3")] == ["MLA9", "MLA3"]
        assert script.build_scenarios(None, None, None) == []


class TestPureHelpers:
    def test_percentile_is_nearest_rank(self, script) -> None:
        samples = [float(n) for n in range(1, 21)]
        assert script.percentile(samples, 50) == 10.0 and script.percentile(samples, 95) == 19.0

    def test_server_timing_is_parsed_into_stages(self, script) -> None:
        assert script.parse_server_timing("detail;dur=1.5, other;dur=4") == {"detail": 1.5, "other": 4.0}
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

        failures: list[str] = []
        assert script.pick_user(["broken", "ok"], perms, failures) == "ok"
        assert failures == ["broken: boom"]


class TestRun:
    def test_every_scenario_is_one_warmup_plus_twenty_get_requests_with_the_token(self, script, capsys) -> None:
        with Api() as api:
            code = script.main(
                [
                    "--base-url",
                    api.url,
                    "--token",
                    "secret",
                    "--mla",
                    "MLA9",
                    "--full-mla",
                    "MLA2",
                    "--plain-mla",
                    "MLA3",
                ]
            )
        out = capsys.readouterr().out
        assert code == 0
        assert len(api.requests) == 3 * (script.RUNS + 1)
        assert {method for method, _p, _a in api.requests} == {"GET"}
        assert {auth for _m, _p, auth in api.requests} == {"Bearer secret"}
        assert paths(api) == {f"/api/ml-publications/view/items/{mla}" for mla in ("MLA9", "MLA2", "MLA3")}
        assert "links=2 freshness=3 replenishment=ok" in out and "breakdown=priced" in out
        assert "detail_ms=12.5" in out and "RESULT: PASS" in out

    def test_over_the_budget_fails_the_run(self, script, capsys) -> None:
        with Api() as api:
            code = script.main(["--base-url", api.url, "--token", "t", "--mla", "MLA9", "--budget-ms", "0.0001"])
        assert code == 1 and "FAIL" in capsys.readouterr().out

    def test_a_response_without_the_breakdown_key_means_the_token_cannot_see_margins(self, script, capsys) -> None:
        with Api(margin=False) as api:
            code = script.main(["--base-url", api.url, "--token", "t", "--mla", "MLA9"])
        assert code == 1 and "ml_metricas.ver_ganancia" in capsys.readouterr().out

    def test_a_null_breakdown_is_reported_but_is_not_a_failure(self, script, capsys) -> None:
        with Api(priced=False) as api:
            code = script.main(["--base-url", api.url, "--token", "t", "--mla", "MLA9"])
        assert code == 0 and "breakdown=null" in capsys.readouterr().out

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
            script, "auto_config", lambda: script.AutoConfig("tok-secret-123", "ana", "MLA77", "MLA78", "MLA79")
        )
        with Api() as api:
            code = script.main(["--base-url", api.url])
        out = capsys.readouterr().out
        assert code == 0
        assert {auth for _m, _p, auth in api.requests} == {"Bearer tok-secret-123"}
        assert {p.rsplit("/", 1)[-1] for p in paths(api)} == {"MLA77", "MLA78", "MLA79"}
        assert "ana" in out and "tok-secret-123" not in out  # the token is never printed

    def test_it_stops_with_a_clear_message_when_no_user_can_be_found(self, script, monkeypatch, capsys) -> None:
        monkeypatch.delenv("PUBML_TOKEN", raising=False)
        monkeypatch.setattr(script, "auto_config", lambda: None)
        assert script.main(["--base-url", "http://127.0.0.1:1/api"]) == 2
        assert "ml_metricas.ver_ganancia" in capsys.readouterr().out

    def test_it_stops_with_a_clear_message_when_no_publication_can_be_found(self, script, monkeypatch, capsys) -> None:
        monkeypatch.delenv("PUBML_TOKEN", raising=False)
        monkeypatch.setattr(script, "auto_config", lambda: script.AutoConfig("tok", "ana", None, None, None))
        assert script.main(["--base-url", "http://127.0.0.1:1/api"]) == 2
        assert "--mla" in capsys.readouterr().out

    def test_an_explicit_mla_wins_over_the_picked_one(self, script, monkeypatch) -> None:
        monkeypatch.delenv("PUBML_TOKEN", raising=False)
        monkeypatch.setattr(script, "auto_config", lambda: script.AutoConfig("tok", "ana", "MLA77", None, None))
        with Api() as api:
            script.main(["--base-url", api.url, "--mla", "MLA5"])
        assert "/api/ml-publications/view/items/MLA5" in paths(api)
        assert "/api/ml-publications/view/items/MLA77" not in paths(api)

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
