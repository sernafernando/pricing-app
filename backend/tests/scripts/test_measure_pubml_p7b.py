"""P7b.T3: `scripts/measure_pubml_p7b.py`, the read-only measurement of the node markup aggregates of the Agrupado tree (R6).

The script is standalone (stdlib only for the measurement; the app is imported lazily, and only to mint its own
token and pick a store and a search word), so it is loaded by path. A throwaway HTTP server stands in for the API:
it serves a small tree on `/groups` and the totals on `/items`.
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

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "measure_pubml_p7b.py"
NONE = "__none__"


@pytest.fixture(scope="module")
def script():
    spec = importlib.util.spec_from_file_location("measure_pubml_p7b", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolves its annotations through sys.modules
    spec.loader.exec_module(module)
    return module


def node(kind: str, key: str, count: int, leaf: bool = False, **params: str) -> dict:
    return {
        "kind": kind,
        "key": key,
        "label": key,
        "count": count,
        "leaf": leaf,
        "params": params,
        "negative_count": count // 3,
        "markup_min": -5.0,
        "markup_max": 40.0,
    }


def tree(families: bool = True, products: int = 3) -> dict:
    """path (tuple of keys, plus `+f` when families are on) -> the answer of `/groups`."""
    brand = {"marcas": "TPL"}
    category = {**brand, "categorias": "REDES"}
    sub = {**category, "subcategorias": "10"}
    answers = {
        (): (
            "marca",
            [node("marca", "TPL", 9, **brand), node("marca", "ACME", 4, marcas="ACME"), node("marca", NONE, 99)],
        ),
        ("TPL",): ("categoria", [node("categoria", "REDES", 9, **category)]),
        ("TPL", "REDES"): ("subcategoria", [node("subcategoria", "10", 9, **sub)]),
        ("TPL", "REDES", "10"): (
            "producto",
            [
                node("producto", "70", 6, True, **sub, producto="70"),
                node("producto", "71", 3, True, **sub, producto="71"),
            ],
        ),
        (NONE, NONE, NONE): ("producto", [node("producto", NONE, 2, True, sin_producto="true")]),
    }
    if families:
        answers[("TPL", "REDES", "10", "f")] = (
            "producto",
            [
                node("producto", "70", 6, False, **sub, producto="70"),
                node("producto", "71", 3, True, **sub, producto="71"),
            ],
        )
        answers[("TPL", "REDES", "10", "70", "f")] = (
            "familia",
            [node("familia", "900", 2, True, **sub, producto="70", familia="900")],
        )
    return answers


class Api:
    """A fake API: `/groups` answers from `tree`, `/items` answers a total, `Server-Timing` on both."""

    def __init__(
        self, status: int = 200, items_total=None, answers=None, big_total: int = 0, negative_total=None
    ) -> None:
        self.requests: list[tuple[str, str, str | None]] = []
        outer = self
        answers = tree() if answers is None else answers

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 -- http.server API
                outer.requests.append(("GET", self.path, self.headers.get("Authorization")))
                url = urlparse(self.path)
                query = parse_qs(url.query)
                if url.path.endswith("/groups"):
                    keys = tuple(k for k in query.get("path", [""])[0].split(",") if k)
                    if query.get("familias") == ["true"]:
                        keys = (*keys, "f")
                    found = answers.get(keys) or answers.get(tuple(k for k in keys if k != "f")) or ("marca", [])
                    level, nodes = found
                    body = {"level": level, "nodes": nodes, "total": big_total or len(nodes), "limit": 100, "offset": 0}
                elif "markup_neg" in query:
                    body = {
                        "items": [],
                        "total": negative_total(query) if negative_total else self.expected(query, "negative_count"),
                    }
                else:
                    body = {"items": [], "total": items_total(query) if items_total else self.expected(query)}
                raw = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Server-Timing", "groups;dur=12.5")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def expected(self, query, field: str = "count") -> int:
                """The `count` (or `negative_count`) of the node whose `params` are exactly the query (bar the
                `limit` and `markup_neg` the script adds)."""
                sent = {k: v[0] for k, v in query.items() if k not in ("limit", "markup_neg")}
                counts = [n[field] for _level, nodes in answers.values() for n in nodes if n["params"] == sent]
                return counts[0] if counts else 0

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

    def test_the_budget_is_the_proposed_one_and_there_are_twenty_runs(self, script) -> None:
        assert script.BUDGET_MS == 1000.0 and script.RUNS == 20

    def test_the_user_needs_ml_ops_ver_and_ver_ganancia(self, script) -> None:
        users = {
            "nobody": {"x"},
            "viewer": {"ml_ops.ver"},  # cannot see the figures
            "analyst": {"ml_ops.ver", "ml_metricas.ver_ganancia"},
        }
        assert script.pick_user(list(users), lambda name: users[name]) == "analyst"
        assert script.pick_user(["nobody", "viewer"], lambda name: users[name]) is None

    def test_a_user_whose_permissions_cannot_be_read_is_skipped(self, script) -> None:
        def perms(name: str):
            if name == "broken":
                raise RuntimeError("boom")
            return {"ml_ops.ver", "ml_metricas.ver_ganancia"}

        assert script.pick_user(["broken", "ok"], perms) == "ok"


class TestPureHelpers:
    def test_percentile_is_nearest_rank(self, script) -> None:
        samples = [float(n) for n in range(1, 21)]
        assert script.percentile(samples, 50) == 10.0 and script.percentile(samples, 95) == 19.0

    def test_server_timing_is_parsed_into_stages(self, script) -> None:
        assert script.parse_server_timing("groups;dur=1.5, other;dur=4") == {"groups": 1.5, "other": 4.0}
        assert script.parse_server_timing(None) == {}

    def test_the_biggest_real_node_wins_over_a_bigger_none_bucket(self, script) -> None:
        nodes = [node("marca", "A", 4), node("marca", "B", 9), node("marca", NONE, 99)]
        assert script.biggest(nodes)["key"] == "B"
        assert script.biggest([node("marca", NONE, 3)])["key"] == NONE  # all there is
        assert script.biggest([]) is None

    def test_the_most_frequent_word_of_the_titles_is_the_search_term(self, script) -> None:
        assert script.frequent_word(["Cable HDMI", "Cable USB", "cable de red", "Router"], fallback="x") == "cable"
        assert script.frequent_word([], fallback="x") == "x"


class TestWalk:
    def scenarios(self, script, **kwargs):
        with Api(**kwargs) as api:
            return script.walk(lambda params: script.fetch(api.url, "t", script.GROUPS, params)[2], "2645", "cable")

    def test_every_level_of_the_tree_has_a_scenario_following_the_biggest_node(self, script) -> None:
        by_name = {s.name: s for s in self.scenarios(script)}
        assert by_name["roots (brands)"].params == {}
        assert by_name["categories of the biggest brand"].params == {"path": "TPL"}
        assert by_name["subcategories of its biggest category"].params == {"path": "TPL,REDES"}
        assert by_name["products of its biggest subcategory"].params == {"path": "TPL,REDES,10"}
        assert by_name["families of the first product that has some"].params == {
            "path": "TPL,REDES,10,70",
            "familias": "true",
        }
        assert by_name["products of 'Sin producto' (unlinked)"].params == {"path": f"{NONE},{NONE},{NONE}"}

    def test_the_filter_scenarios_use_the_store_and_the_term(self, script) -> None:
        by_name = {s.name: s for s in self.scenarios(script)}
        assert by_name["roots, store 2645"].params == {"tiendas": "2645"}
        assert by_name["roots, search 'cable'"].params == {"q": "cable"}
        assert by_name["roots, families on"].params == {"familias": "true"}

    def test_a_second_page_is_measured_only_when_the_level_has_more_than_a_page(self, script) -> None:
        names = [s.name for s in self.scenarios(script)]
        assert "products, second page" not in names
        paged = {s.name: s for s in self.scenarios(script, big_total=230)}
        assert paged["products, second page"].params == {"path": "TPL,REDES,10", "offset": 100}

    def test_a_branch_that_does_not_exist_yields_no_scenario_and_no_crash(self, script) -> None:
        answers = tree(families=False)
        del answers[(NONE, NONE, NONE)]
        names = [s.name for s in self.scenarios(script, answers=answers)]
        assert "families of the first product that has some" not in names
        assert "products of 'Sin producto' (unlinked)" not in names
        assert "products of its biggest subcategory" in names

    def test_an_empty_tree_stops_at_the_roots(self, script) -> None:
        names = [s.name for s in self.scenarios(script, answers={})]
        assert names == ["roots (brands)", "roots, store 2645", "roots, search 'cable'", "roots, families on"]


class TestRun:
    def test_every_scenario_is_one_warmup_plus_twenty_get_requests_with_the_token(self, script, capsys) -> None:
        with Api() as api:
            code = script.main(["--base-url", api.url, "--token", "secret", "--store", "1", "--term", "cable"])
        out = capsys.readouterr().out
        assert code == 0, out
        measured = [p for _m, p, _a in api.requests if "/groups" in p]
        assert {method for method, _p, _a in api.requests} == {"GET"}
        assert {auth for _m, _p, auth in api.requests} == {"Bearer secret"}
        assert len(measured) >= 9 * 21  # nine scenarios x (warm-up + 20), plus the requests of the walk
        assert "RESULT: PASS" in out and "level=categoria" in out and "level=familia" in out

    def test_the_budget_decides_the_verdict(self, script, capsys) -> None:
        with Api() as api:
            code = script.main(["--base-url", api.url, "--token", "t", "--budget-ms", "0.0001"])
        out = capsys.readouterr().out
        assert code == 1 and "FAIL" in out and "RESULT: FAIL" in out

    def test_the_count_of_the_opened_node_is_checked_against_items(self, script, capsys) -> None:
        with Api() as api:
            script.main(["--base-url", api.url, "--token", "t"])
        out = capsys.readouterr().out
        assert "consistency [categories of the biggest brand] node 'TPL': count=9 items_total=9 OK" in out
        queries = [parse_qs(urlparse(p).query) for _m, p, _a in api.requests if "/items" in p]
        assert queries and all(q["limit"] == ["1"] for q in queries)

    def test_the_negative_count_of_the_opened_node_is_checked_against_items_markup_neg(self, script, capsys) -> None:
        with Api() as api:
            code = script.main(["--base-url", api.url, "--token", "t"])
        out = capsys.readouterr().out
        assert code == 0, out
        assert "node 'TPL': negative_count=3 items_markup_neg_total=3 OK" in out
        negatives = [parse_qs(urlparse(p).query) for _m, p, _a in api.requests if "markup_neg" in p]
        assert negatives and all(q["markup_neg"] == ["true"] and q["limit"] == ["1"] for q in negatives)

    def test_a_negative_count_that_differs_from_items_fails_the_run(self, script, capsys) -> None:
        with Api(negative_total=lambda query: 99) as api:
            code = script.main(["--base-url", api.url, "--token", "t"])
        out = capsys.readouterr().out
        assert code == 1 and "negative_count=3 items_markup_neg_total=99 MISMATCH" in out

    def test_a_node_without_the_figures_fails_the_run(self, script, capsys) -> None:
        answers = tree()
        for _level, nodes in answers.values():
            for item in nodes:
                del item["negative_count"]
        with Api(answers=answers) as api:
            code = script.main(["--base-url", api.url, "--token", "t"])
        out = capsys.readouterr().out
        assert code == 1 and "MISSING" in out

    def test_an_over_budget_scenario_says_it_belongs_in_the_p6b_decision(self, script, capsys) -> None:
        with Api() as api:
            script.main(["--base-url", api.url, "--token", "t", "--budget-ms", "0.0001"])
        out = capsys.readouterr().out
        assert "OVER BUDGET" in out and "P6b" in out

    def test_a_node_whose_count_differs_from_items_fails_the_run(self, script, capsys) -> None:
        with Api(items_total=lambda query: 1) as api:
            code = script.main(["--base-url", api.url, "--token", "t"])
        out = capsys.readouterr().out
        assert code == 1 and "MISMATCH" in out

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
    def test_without_a_token_it_mints_its_own_and_picks_the_store_and_term(self, script, monkeypatch, capsys) -> None:
        monkeypatch.delenv("PUBML_TOKEN", raising=False)
        monkeypatch.setattr(script, "auto_config", lambda: script.AutoConfig("tok-secret-123", "ana", "2645", "router"))
        with Api() as api:
            code = script.main(["--base-url", api.url])
        out = capsys.readouterr().out
        assert code == 0, out
        assert {auth for _m, _p, auth in api.requests} == {"Bearer tok-secret-123"}
        queries = [parse_qs(urlparse(p).query) for _m, p, _a in api.requests]
        assert any(q.get("tiendas") == ["2645"] for q in queries) and any(q.get("q") == ["router"] for q in queries)
        assert "ana" in out and "tok-secret-123" not in out  # the token is never printed

    def test_it_stops_with_a_clear_message_when_no_user_can_be_found(self, script, monkeypatch, capsys) -> None:
        monkeypatch.delenv("PUBML_TOKEN", raising=False)
        monkeypatch.setattr(script, "auto_config", lambda: None)
        assert script.main(["--base-url", "http://127.0.0.1:1/api"]) == 2
        out = capsys.readouterr().out
        assert "ml_ops.ver" in out and "ml_metricas.ver_ganancia" in out  # both permissions are named

    def test_an_unreachable_api_is_a_clear_failure_not_a_traceback(self, script, capsys) -> None:
        assert script.main(["--base-url", "http://127.0.0.1:1/api", "--token", "t"]) == 1
        assert "cannot open the tree" in capsys.readouterr().out

    def test_a_failed_permission_read_leaves_the_session_usable_and_still_read_only(self, script) -> None:
        """A database error while reading one user's permissions aborts the transaction: the next user (and the
        queries after them) must start from a clean, read-only one."""

        class Db:
            def __init__(self) -> None:
                self.calls: list[str] = []

            def rollback(self) -> None:
                self.calls.append("rollback")

            def execute(self, statement) -> None:
                self.calls.append(str(statement))

        class Service:
            def obtener_permisos_usuario(self, user):
                if user == "broken":
                    raise RuntimeError("current transaction is aborted")
                return {"ml_ops.ver"}

        db = Db()

        with pytest.raises(RuntimeError):
            script.read_permissions(db, Service(), "broken")
        assert db.calls == ["rollback", "SET TRANSACTION READ ONLY"]
        db.calls.clear()
        assert script.read_permissions(db, Service(), "ok") == {"ml_ops.ver"}
        assert db.calls == []  # nothing to repair when the read worked

    def test_the_app_is_imported_from_the_working_directory_and_only_when_needed(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        assert "sys.path.insert(0, os.getcwd())" in source
        top = source.split("def auto_config")[0]
        assert not re.search(r"^(from|import) app\b", top, re.MULTILINE)  # lazy: the measurement needs no app

    def test_the_script_loads_standalone_from_a_copy_in_another_directory(self, tmp_path) -> None:
        """It is uploaded alone to /tmp: nothing may be imported from the repository, `scripts/` or a sibling."""
        copy = tmp_path / "measure_pubml_p7b.py"
        copy.write_text(SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
        spec = importlib.util.spec_from_file_location("measure_copy", copy)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        try:
            spec.loader.exec_module(module)
        finally:
            sys.modules.pop(spec.name, None)
        assert module.DEFAULT_BASE_URL.endswith(":8002/api")


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
