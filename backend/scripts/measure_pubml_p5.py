#!/usr/bin/env python3
"""Read-only measurement of the Publicaciones list (`GET /ml-publications/view/items`), P5 / R6.

Sends GET requests only: 1 warm-up plus 20 measured requests per scenario, then prints p50 / p95 / max against
the owner's budget (list page p95 < 500 ms) and, per scenario, a `pubml.view` line with the server-side stages
(`Server-Timing` header of the endpoint, p50 of each stage). It writes nothing anywhere.

Standard library only, so it runs with a bare `python3` on the server.

    PUBML_TOKEN=<access token of a user with ml_ops.ver> \\
        python3 measure_pubml_p5.py --base-url http://localhost:8000/api

Options: `--term` / `--product-term` (words that exist in your titles / linked product names), `--mla` (an MLA id,
adds an exact-search scenario), `--budget-ms`, and `--database-url` (optional: one read-only query that reports
whether the `pg_trgm` and `unaccent` extensions are installed, which decides if a title trigram index and
accent-insensitive search are possible; the script never installs anything).

Exit code: 0 all scenarios under budget, 1 over budget or an HTTP error, 2 usage error (no token).
"""

from __future__ import annotations

import argparse
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Optional

BUDGET_MS = 500.0
RUNS = 20
PATH = "/ml-publications/view/items"
TIMEOUT_SECONDS = 30
DEFAULT_TERM = "cable"
DEFAULT_PRODUCT_TERM = "camara"

# Read-only: the extensions that decide whether a trigram index / accent-insensitive search is possible.
PROBE_SQL = "SELECT extname FROM pg_extension WHERE extname IN ('pg_trgm', 'unaccent') ORDER BY extname"


@dataclass(frozen=True)
class Scenario:
    name: str
    params: dict[str, Any]


def build_scenarios(term: str, product_term: str, mla: Optional[str] = None) -> list[Scenario]:
    scenarios = [
        Scenario("default", {"limit": 50}),
        Scenario("default + facets", {"limit": 50, "facets": "true"}),
        Scenario("page 5", {"limit": 50, "offset": 200}),
        Scenario(f"search '{term}' (title, SKU, product)", {"limit": 50, "q": term}),
        Scenario(f"search '{product_term}' (linked product)", {"limit": 50, "q": product_term}),
        Scenario("filter active, sort price", {"limit": 50, "estado": "active", "orden": "precio"}),
    ]
    if mla:
        scenarios.append(Scenario(f"search {mla} (exact)", {"limit": 50, "q": mla}))
    return scenarios


SCENARIOS = build_scenarios(DEFAULT_TERM, DEFAULT_PRODUCT_TERM)


def percentile(samples: list[float], q: float) -> float:
    """Nearest-rank percentile (q in 0..100) of unsorted samples."""
    ordered = sorted(samples)
    rank = max(1, math.ceil(q / 100 * len(ordered)))
    return ordered[rank - 1]


def parse_server_timing(header: Optional[str]) -> dict[str, float]:
    """`name;dur=12.3, other;dur=4` -> {name: 12.3, other: 4.0}; entries without a duration are ignored."""
    stages: dict[str, float] = {}
    for entry in (header or "").split(","):
        name, *attributes = [part.strip() for part in entry.split(";")]
        for attribute in attributes:
            if attribute.startswith("dur="):
                try:
                    stages[name] = float(attribute[4:])
                except ValueError:
                    pass
    return stages


class RequestFailed(Exception):
    pass


def fetch(base_url: str, token: str, params: dict[str, Any]) -> tuple[float, dict[str, float], dict[str, Any]]:
    """One GET of the list: (elapsed ms, server-side stages, JSON body)."""
    import json

    url = base_url.rstrip("/") + PATH + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, method="GET", headers={"Authorization": f"Bearer {token}"})
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            raw = response.read()
            stages = parse_server_timing(response.headers.get("Server-Timing"))
    except urllib.error.HTTPError as exc:
        raise RequestFailed(f"HTTP {exc.code}") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise RequestFailed(f"connection error: {exc}") from exc
    elapsed = (time.perf_counter() - started) * 1000
    return elapsed, stages, json.loads(raw)


@dataclass
class Result:
    scenario: Scenario
    samples: list[float] = field(default_factory=list)
    stages: dict[str, list[float]] = field(default_factory=dict)
    error: Optional[str] = None
    total: Optional[int] = None
    rows: Optional[int] = None
    data_state: Optional[dict[str, Any]] = None
    warmup_ms: Optional[float] = None  # the uncounted first request
    warmup_stages: dict[str, float] = field(default_factory=dict)


def measure(base_url: str, token: str, scenario: Scenario, runs: int = RUNS) -> Result:
    result = Result(scenario)
    try:
        result.warmup_ms, result.warmup_stages, _ = fetch(base_url, token, scenario.params)  # not counted
        for _ in range(runs):
            elapsed, stages, body = fetch(base_url, token, scenario.params)
            result.samples.append(elapsed)
            for name, ms in stages.items():
                result.stages.setdefault(name, []).append(ms)
            result.total, result.rows, result.data_state = (
                body.get("total"),
                len(body.get("items", [])),
                body.get("data_state"),
            )
    except RequestFailed as exc:
        result.error = str(exc)
    return result


def describe_data_state(state: Optional[dict[str, Any]]) -> str:
    if not state:
        return "data_state: missing"
    marks = [
        f"{d.get('code')}:{d.get('flag') or d.get('resource') or ''}".rstrip(":") for d in state.get("degradations", [])
    ]
    return f"data_state: degraded={state.get('degraded')} store_empty={state.get('store_empty')} [{', '.join(marks)}]"


def report(result: Result, budget_ms: float) -> bool:
    """Print one scenario; True when it is within budget."""
    name = result.scenario.name
    if result.error:
        print(f"[{name}] FAIL {result.error}")
        return False
    p50, p95, worst = (percentile(result.samples, 50), percentile(result.samples, 95), max(result.samples))
    ok = p95 < budget_ms
    print(
        f"[{name}] n={len(result.samples)} p50={p50:.1f} ms p95={p95:.1f} ms max={worst:.1f} ms "
        f"(budget p95 < {budget_ms:g} ms) {'PASS' if ok else 'FAIL'}"
    )
    line = [f"pubml.view endpoint=items scenario={name!r}"]
    line += [f"{stage}_ms={percentile(values, 50):.1f}" for stage, values in result.stages.items()]
    line += [f"rows={result.rows}", f"total={result.total}"]
    print(" ".join(line))
    return ok


def probe_extensions(database_url: str) -> None:
    """One read-only query: which of pg_trgm / unaccent are installed."""
    try:
        import psycopg2
    except ImportError:
        print("database probe skipped: psycopg2 is not installed")
        return
    connection = psycopg2.connect(database_url)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION READ ONLY")
            cursor.execute(PROBE_SQL)
            installed = [row[0] for row in cursor.fetchall()]
    finally:
        connection.rollback()
        connection.close()
    for name in ("pg_trgm", "unaccent"):
        print(f"extension {name}: {'installed' if name in installed else 'NOT installed'}")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only measurement of GET /ml-publications/view/items")
    parser.add_argument("--base-url", default="http://localhost:8000/api")
    parser.add_argument("--token", default=None, help="access token (default: $PUBML_TOKEN)")
    parser.add_argument("--term", default=DEFAULT_TERM, help="word present in publication titles")
    parser.add_argument("--product-term", default=DEFAULT_PRODUCT_TERM, help="word present in linked product names")
    parser.add_argument("--mla", default=None, help="an MLA id: adds an exact-search scenario")
    parser.add_argument("--budget-ms", type=float, default=BUDGET_MS)
    parser.add_argument("--database-url", default=None, help="optional: report installed pg_trgm / unaccent")
    args = parser.parse_args(argv)
    token = args.token or os.environ.get("PUBML_TOKEN")
    if not token:
        print("No token: pass --token or set PUBML_TOKEN (an access token of a user with ml_ops.ver).")
        return 2
    scenarios = build_scenarios(args.term, args.product_term, args.mla)
    print(f"measuring {args.base_url}{PATH}: {RUNS} requests per scenario after 1 warm-up, GET only")
    passed = True
    state_line: Optional[str] = None
    for index, scenario in enumerate(scenarios):
        result = measure(args.base_url, token, scenario)
        if index == 0 and result.warmup_ms is not None:
            # the very first request also builds the (cached) status report behind `data_state`
            status_ms = result.warmup_stages.get("status")
            status = "n/a" if status_ms is None else f"{status_ms} ms"
            print(f"cold first request: {result.warmup_ms:.1f} ms (status {status})")
        passed = report(result, args.budget_ms) and passed
        if state_line is None and not result.error:
            state_line = describe_data_state(result.data_state)
    if state_line:
        print(state_line)
    if args.database_url:
        probe_extensions(args.database_url)
    print(f"RESULT: {'PASS' if passed else 'FAIL'} (list page p95 < {args.budget_ms:g} ms in every scenario)")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
