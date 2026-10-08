"""P6.T6: `scripts/measure_pubml_p6.py`, the read-only measurement of the markup in the list (R6, the P6b gate).

The script is standalone (stdlib only for the measurement; the app is imported lazily, and only to mint its own
token and pick search terms), so it is loaded by path. A throwaway HTTP server stands in for the API.
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

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "measure_pubml_p6.py"


@pytest.fixture(scope="module")
def script():
    spec = importlib.util.spec_from_file_location("measure_pubml_p6", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolves its annotations through sys.modules
    spec.loader.exec_module(module)
    return module


class Api:
    """A fake list endpoint: answers a page with the markup blocks and a `Server-Timing` header, records requests."""

    def __init__(self, status: int = 200, markup: bool = True, delay: float = 0.0) -> None:
        self.requests: list[tuple[str, str, str | None]] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 -- http.server API
                outer.requests.append(("GET", self.path, self.headers.get("Authorization")))
                body = {
                    "items": [{"item_id": "MLA1"}],
                    "total": 24600,
                    "data_state": {"degraded": False, "degradations": []},
                }
                if markup:
                    body["items"] = [{"item_id": "MLA1", "markup": {"worst": 12.5}}]
                    body["markup_stats"] = {"computed": 17000, "null_by_reason": {"sin_vinculo": 7600}, "ms": 812.5}
                    body["ads"] = {
                        "available": False,
                        "reason": "provider_missing",
                        "requested": False,
                        "applied": False,
                    }
                raw = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Server-Timing", "flags;dur=1.5, list;dur=20.0, status;dur=0.5")
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

    def test_the_budgets_are_the_owner_ones(self, script) -> None:
        assert script.PAGE_BUDGET_MS == 500.0 and script.SET_WIDE_BUDGET_MS == 1000.0 and script.RUNS == 20

    def test_the_scenarios_cover_the_page_path_and_the_set_wide_path(self, script) -> None:
        scenarios = script.build_scenarios("cable", "camara", "MLA1")
        by_kind = {s.set_wide for s in scenarios}
        assert by_kind == {True, False}
        sorts = [s for s in scenarios if s.params.get("orden") == "markup"]
        assert any(
            not {k for k in s.params if k not in ("orden", "dir", "limit", "offset")} for s in sorts
        )  # unfiltered
        assert any(s.params.get("markup_neg") == "true" for s in scenarios)
        assert any("markup_min" in s.params or "markup_max" in s.params for s in scenarios)
        assert any(s.params.get("q") for s in sorts)  # a search combined with the markup sort
        assert all(
            s.set_wide
            == bool(
                s.params.get("orden") == "markup"
                or "markup_neg" in s.params
                or "markup_min" in s.params
                or "markup_max" in s.params
            )
            for s in scenarios
        )

    def test_exactly_one_scenario_is_the_p6b_gate(self, script) -> None:
        gate = [s for s in script.build_scenarios("a", "b", None) if s.gate]
        assert len(gate) == 1
        assert gate[0].params == {"limit": 50, "orden": "markup"}


class TestPureHelpers:
    def test_percentile_is_nearest_rank(self, script) -> None:
        samples = [float(n) for n in range(1, 21)]
        assert script.percentile(samples, 50) == 10.0 and script.percentile(samples, 95) == 19.0

    def test_server_timing_is_parsed_into_stages(self, script) -> None:
        assert script.parse_server_timing("flags;dur=1.5, list;dur=20.0") == {"flags": 1.5, "list": 20.0}
        assert script.parse_server_timing(None) == {}

    def test_the_most_frequent_word_of_the_titles_is_the_search_term(self, script) -> None:
        titles = ["Cable HDMI 2 metros", "Cable USB", "cable de red", "Camara domo", "Router"]
        assert script.frequent_word(titles, fallback="x") == "cable"
        assert script.frequent_word([], fallback="x") == "x"
        assert script.frequent_word(["a b"], fallback="x") == "x"  # words under 5 letters do not count

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


class TestRun:
    def test_every_scenario_is_one_warmup_plus_twenty_get_requests_with_the_token(self, script, capsys) -> None:
        with Api() as api:
            code = script.main(["--base-url", api.url, "--token", "secret"])
        out = capsys.readouterr().out
        scenarios = script.build_scenarios(script.DEFAULT_TERM, script.DEFAULT_PRODUCT_TERM)
        assert code == 0
        assert len(api.requests) == len(scenarios) * (script.RUNS + 1)
        assert {method for method, _p, _a in api.requests} == {"GET"}
        assert {auth for _m, _p, auth in api.requests} == {"Bearer secret"}
        assert all(path.startswith("/api/ml-publications/view/items?") for _m, path, _a in api.requests)
        for scenario in scenarios:
            assert scenario.name in out

    def test_the_markup_parameters_reach_the_endpoint(self, script) -> None:
        with Api() as api:
            script.main(["--base-url", api.url, "--token", "t"])
        queries = [parse_qs(urlparse(path).query) for _m, path, _a in api.requests]
        assert any(q.get("orden") == ["markup"] for q in queries)
        assert any(q.get("markup_neg") == ["true"] for q in queries)

    def test_the_p6b_verdict_is_printed_from_the_unfiltered_markup_sort(self, script, capsys) -> None:
        with Api() as api:
            script.main(["--base-url", api.url, "--token", "t"])
        out = capsys.readouterr().out
        assert "P6b gate" in out and "p95" in out
        assert "P6b NOT needed" in out  # the fake answers instantly

    def test_the_verdict_says_p6b_is_needed_over_the_threshold(self, script, capsys) -> None:
        with Api() as api:
            code = script.main(["--base-url", api.url, "--token", "t", "--set-wide-budget-ms", "0.0001"])
        out = capsys.readouterr().out
        assert code == 1 and "P6b NEEDED" in out

    def test_the_markup_stats_and_ads_block_are_reported(self, script, capsys) -> None:
        with Api() as api:
            script.main(["--base-url", api.url, "--token", "t"])
        out = capsys.readouterr().out
        assert "computed=17000" in out and "sin_vinculo" in out
        assert "ads: available=False reason=provider_missing" in out

    def test_a_response_without_markup_means_the_token_cannot_see_margins(self, script, capsys) -> None:
        with Api(markup=False) as api:
            code = script.main(["--base-url", api.url, "--token", "t"])
        assert code == 1
        assert "ml_metricas.ver_ganancia" in capsys.readouterr().out

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
    def test_without_a_token_it_mints_its_own_and_picks_the_terms(self, script, monkeypatch, capsys) -> None:
        monkeypatch.delenv("PUBML_TOKEN", raising=False)
        monkeypatch.setattr(
            script,
            "auto_config",
            lambda: script.AutoConfig(
                token="tok-secret-123", username="ana", term="router", product_term="domo", mla="MLA77"
            ),
        )
        with Api() as api:
            code = script.main(["--base-url", api.url])
        out = capsys.readouterr().out
        assert code == 0
        assert {auth for _m, _p, auth in api.requests} == {"Bearer tok-secret-123"}
        queries = [parse_qs(urlparse(path).query) for _m, path, _a in api.requests]
        assert any(q.get("q") == ["router"] for q in queries) and any(q.get("q") == ["MLA77"] for q in queries)
        assert "ana" in out and "tok-secret-123" not in out  # the token is never printed

    def test_it_stops_with_a_clear_message_when_no_user_can_be_found(self, script, monkeypatch, capsys) -> None:
        monkeypatch.delenv("PUBML_TOKEN", raising=False)
        monkeypatch.setattr(script, "auto_config", lambda: None)
        assert script.main(["--base-url", "http://127.0.0.1:1/api"]) == 2
        assert "ml_metricas.ver_ganancia" in capsys.readouterr().out

    def test_an_explicit_term_wins_over_the_picked_one(self, script, monkeypatch) -> None:
        monkeypatch.delenv("PUBML_TOKEN", raising=False)
        monkeypatch.setattr(
            script, "auto_config", lambda: script.AutoConfig("tok-secret-123", "ana", "router", "domo", None)
        )
        with Api() as api:
            script.main(["--base-url", api.url, "--term", "antena"])
        queries = [parse_qs(urlparse(path).query) for _m, path, _a in api.requests]
        assert any(q.get("q") == ["antena"] for q in queries) and not any(q.get("q") == ["router"] for q in queries)

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
