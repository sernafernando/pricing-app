#!/usr/bin/env python3
"""Read-only measurement of the Agrupado tree (`GET /ml-publications/view/groups`), P7a / R6.

It answers one question: is opening ONE level of the tree fast enough (budget p95 < 400 ms, a proposal)? It sends GET
requests only: 1 warm-up plus 20 measured requests per scenario, then prints p50 / p95 / max against the budget. It
writes nothing anywhere. The scenarios are every level of the tree (brands, then the categories of the biggest brand,
the subcategories of its biggest category, the products of its biggest subcategory, the families of the first
product that has any), the roots with a store filter, with a search, and with families on, the "Sin producto" branch
and a second page. The nodes are found by walking the API itself, so the keys are exactly the ones the screen sends.

It also checks, for the node it opened at each level, that its `count` is the `/items` total with the node's `params`
(the consistency rule of the tree) and prints MISMATCH when they differ; that check is not timed.

Zero configuration. Run it from the backend directory of the server with the app's own interpreter:

    cd /var/www/html/pricing-app/backend && venv/bin/python /tmp/measure_pubml_p7a.py

With no token it mints a short-lived (15 min) one, locally, with the app's `create_access_token`, for the first
active user that holds `ml_ops.ver` (the token is never printed), and it picks the store and the search word from the
database through a read-only transaction. It talks to the local API (http://localhost:8002/api by default).
`--token` / `$PUBML_TOKEN`, `--store`, `--term` and `--base-url` override any of it; with a token given the app is
not imported.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Callable, Iterable, Optional, Sequence

DEFAULT_BASE_URL = "http://localhost:8002/api"
BUDGET_MS = 400.0
RUNS = 20
GROUPS = "/ml-publications/view/groups"
ITEMS = "/ml-publications/view/items"
TIMEOUT_SECONDS = 60
REQUIRED_PERMISSIONS = frozenset({"ml_ops.ver"})
TOKEN_MINUTES = 15
DEFAULT_TERM = "cable"
NO_GROUP = "__none__"
PAGE = 100


@dataclass(frozen=True)
class Scenario:
    name: str
    params: dict[str, Any]
    node: Optional[dict[str, Any]] = None  # the node whose children this opens (checked against /items)


class RequestFailed(Exception):
    pass


def percentile(samples: Sequence[float], q: float) -> float:
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


def fetch(base_url: str, token: str, endpoint: str, params: dict[str, Any]) -> tuple[float, dict[str, float], Any]:
    """One GET: (elapsed ms, server-side stages, JSON body)."""
    url = base_url.rstrip("/") + endpoint + "?" + urllib.parse.urlencode(params)
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
    return (time.perf_counter() - started) * 1000, stages, json.loads(raw)


def path_param(keys: Iterable[str]) -> dict[str, str]:
    keys = list(keys)
    return {"path": ",".join(keys)} if keys else {}


def biggest(nodes: Sequence[dict[str, Any]], *, real: bool = True) -> Optional[dict[str, Any]]:
    """The node with the most publications (a real one: not the `__none__` bucket unless that is all there is)."""
    pool = [n for n in nodes if n["key"] != NO_GROUP] if real else list(nodes)
    pool = pool or list(nodes)
    return max(pool, key=lambda n: n["count"]) if pool else None


def walk(get: Callable[[dict[str, Any]], dict[str, Any]], store: Optional[str], term: str) -> list[Scenario]:
    """The scenarios, discovered by opening the tree through `get` (params -> `/groups` body): each level's node is
    the biggest one of the level above. A branch that does not exist in this data (no families, no unlinked
    publications) simply yields no scenario."""
    scenarios = [Scenario("roots (brands)", {})]
    if store:
        scenarios.append(Scenario(f"roots, store {store}", {"tiendas": store}))
    scenarios.append(Scenario(f"roots, search '{term}'", {"q": term}))
    scenarios.append(Scenario("roots, families on", {"familias": "true"}))

    keys: list[str] = []
    level_names = (
        "categories of the biggest brand",
        "subcategories of its biggest category",
        "products of its biggest subcategory",
    )
    body = get({})
    for name in level_names:
        node = biggest(body["nodes"])
        if node is None:
            return scenarios
        keys.append(node["key"])
        scenarios.append(Scenario(name, path_param(keys), node))
        body = get(path_param(keys))
    if body["total"] > PAGE:
        scenarios.append(Scenario("products, second page", {**path_param(keys), "offset": PAGE}))
    scenarios.append(Scenario("products, families on", {**path_param(keys), "familias": "true"}))
    with_families = get({**path_param(keys), "familias": "true"})
    family_parent = next((n for n in with_families["nodes"] if not n["leaf"]), None)
    if family_parent is not None:
        scenarios.append(
            Scenario(
                "families of the first product that has some",
                {**path_param([*keys, family_parent["key"]]), "familias": "true"},
                family_parent,
            )
        )
    unlinked = {"path": ",".join([NO_GROUP] * 3)}
    if get(unlinked)["nodes"]:
        scenarios.append(Scenario("products of 'Sin producto' (unlinked)", unlinked))
    return scenarios


@dataclass
class Result:
    scenario: Scenario
    samples: list[float] = field(default_factory=list)
    stages: dict[str, list[float]] = field(default_factory=dict)
    error: Optional[str] = None
    nodes: Optional[int] = None
    total: Optional[int] = None
    level: Optional[str] = None
    warmup_ms: Optional[float] = None


def measure(base_url: str, token: str, scenario: Scenario, runs: int = RUNS) -> Result:
    result = Result(scenario)
    try:
        result.warmup_ms, _stages, _body = fetch(base_url, token, GROUPS, scenario.params)  # not counted
        for _ in range(runs):
            elapsed, stages, body = fetch(base_url, token, GROUPS, scenario.params)
            result.samples.append(elapsed)
            for name, ms in stages.items():
                result.stages.setdefault(name, []).append(ms)
            result.nodes, result.total, result.level = len(body["nodes"]), body["total"], body["level"]
    except RequestFailed as exc:
        result.error = str(exc)
    return result


def report(result: Result, budget_ms: float) -> bool:
    """Print one scenario; True when it is within budget."""
    scenario = result.scenario
    if result.error:
        print(f"[{scenario.name}] FAIL {result.error}")
        return False
    p50, p95, worst = percentile(result.samples, 50), percentile(result.samples, 95), max(result.samples)
    ok = p95 < budget_ms
    print(
        f"[{scenario.name}] level={result.level} nodes={result.nodes} of {result.total} n={len(result.samples)} "
        f"p50={p50:.1f} ms p95={p95:.1f} ms max={worst:.1f} ms (budget p95 < {budget_ms:g} ms) "
        f"{'PASS' if ok else 'FAIL'}"
    )
    stages = " ".join(f"{stage}_ms={percentile(values, 50):.1f}" for stage, values in result.stages.items())
    print(f"pubml.view endpoint=groups scenario={scenario.name!r} {stages}".rstrip())
    return ok


def check_consistency(base_url: str, token: str, scenario: Scenario, parent: Optional[dict[str, Any]]) -> bool:
    """The node this scenario opens has `count` == the `/items` total with its `params` (not timed)."""
    if parent is None or "count" not in parent:
        return True
    _ms, _stages, body = fetch(base_url, token, ITEMS, {**parent["params"], "limit": 1})
    ok = body["total"] == parent["count"]
    print(
        f"consistency [{scenario.name}] node {parent['key']!r}: count={parent['count']} items_total={body['total']} "
        f"{'OK' if ok else 'MISMATCH'}"
    )
    return ok


# --- zero configuration: a token, a store and a search word from the app itself ----------------------------


@dataclass(frozen=True)
class AutoConfig:
    token: str
    username: str
    store: Optional[str]
    term: str


def frequent_word(titles: Iterable[str], fallback: str) -> str:
    """The most frequent word (5+ letters) of the titles, or `fallback`."""
    words = Counter(w for title in titles for w in re.findall(r"[a-záéíóúñ]{5,}", (title or "").lower()))
    return words.most_common(1)[0][0] if words else fallback


def pick_user(names: Iterable[str], permissions_of: Callable[[str], Iterable[str]]) -> Optional[str]:
    """The first user that holds every required permission; one whose permissions cannot be read is skipped."""
    for name in names:
        try:
            if REQUIRED_PERMISSIONS <= set(permissions_of(name)):
                return name
        except Exception:
            continue
    return None


def auto_config() -> Optional[AutoConfig]:
    """Mint a token for an active user with `ml_ops.ver`; pick the busiest store and a frequent title word."""
    sys.path.insert(0, os.getcwd())  # run from the backend directory with its own interpreter
    try:
        from sqlalchemy import text

        from app.core.database import SessionLocal
        from app.core.security import create_access_token
        from app.models.usuario import Usuario
        from app.services.permisos_service import PermisosService
    except Exception as exc:  # not run from the backend directory, or without its environment
        print(f"cannot load the app ({exc}); run from the backend directory with venv/bin/python, or pass --token")
        return None
    db = SessionLocal()
    try:
        try:
            db.execute(text("SET TRANSACTION READ ONLY"))  # nothing here writes; the database also refuses it
        except Exception:  # not PostgreSQL: the queries below are SELECTs anyway
            db.rollback()
        service = PermisosService(db)
        users = {
            (u.username or u.email): u
            for u in db.query(Usuario).filter(Usuario.activo.is_(True)).order_by(Usuario.id).all()
            if (u.username or u.email)
        }
        username = pick_user(users, lambda name: service.obtener_permisos_usuario(users[name]))
        if username is None:
            return None
        titles = [r[0] for r in db.execute(text("SELECT title FROM ml_items WHERE title IS NOT NULL LIMIT 5000"))]
        store = db.execute(
            text(
                "SELECT official_store_id FROM ml_items WHERE official_store_id IS NOT NULL AND gone_at IS NULL "
                "GROUP BY official_store_id ORDER BY count(*) DESC LIMIT 1"
            )
        ).scalar()
    finally:
        db.rollback()
        db.close()
    token = create_access_token({"sub": username}, expires_delta=timedelta(minutes=TOKEN_MINUTES))
    return AutoConfig(token, username, None if store is None else str(store), frequent_word(titles, DEFAULT_TERM))


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only measurement of GET /ml-publications/view/groups")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--token", default=None, help="access token (default: $PUBML_TOKEN, else minted locally)")
    parser.add_argument(
        "--store", default=None, help="official_store_id for the store-filter scenario (default: picked)"
    )
    parser.add_argument("--term", default=None, help="word present in publication titles (default: picked)")
    parser.add_argument("--budget-ms", type=float, default=BUDGET_MS)
    args = parser.parse_args(argv)

    token = args.token or os.environ.get("PUBML_TOKEN")
    store, term = args.store, args.term
    if token:
        print("using the token given")
    else:
        config = auto_config()
        if config is None:
            print(
                "No token and no active user holding ml_ops.ver could be found; "
                "pass --token or run from the backend directory."
            )
            return 2
        token, store, term = config.token, store or config.store, term or config.term
        print(f"minted a {TOKEN_MINUTES}-minute token for {config.username} (ml_ops.ver)")
    term = term or DEFAULT_TERM

    def get(params: dict[str, Any]) -> dict[str, Any]:
        return fetch(args.base_url, token, GROUPS, params)[2]

    try:
        scenarios = walk(get, store, term)
    except (RequestFailed, KeyError, ValueError) as exc:
        print(f"cannot open the tree: {exc}")
        return 1
    print(f"store={store} term={term!r}")
    print(f"measuring {args.base_url}{GROUPS}: {RUNS} requests per scenario after 1 warm-up, GET only")
    passed = True
    for index, scenario in enumerate(scenarios):
        result = measure(args.base_url, token, scenario)
        if index == 0 and result.warmup_ms is not None:
            print(f"cold first request: {result.warmup_ms:.1f} ms")
        passed = report(result, args.budget_ms) and passed
        if not result.error:
            try:
                passed = check_consistency(args.base_url, token, scenario, scenario.node) and passed
            except RequestFailed as exc:
                print(f"consistency [{scenario.name}]: FAIL {exc}")
                passed = False
    print(f"RESULT: {'PASS' if passed else 'FAIL'} (every level p95 < {args.budget_ms:g} ms, counts equal /items)")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
