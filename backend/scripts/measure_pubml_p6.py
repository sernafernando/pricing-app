#!/usr/bin/env python3
"""Read-only measurement of the markup in the Publicaciones list (`GET /ml-publications/view/items`), P6 / R6.

It answers one question: is sorting or filtering by markup fast enough to compute at query time (P6b is built only
if `orden=markup` with no other filter has p95 > 1 s). It sends GET requests only: 1 warm-up plus 20 measured
requests per scenario, then prints p50 / p95 / max against the budgets and the P6b verdict. It writes nothing
anywhere. The scenarios are the page path (markup of the 50 rows of a page, budget p95 < 500 ms) and the set-wide
path (sort / filter by markup prices every publication of the filtered set, budget p95 < 1 s).

Zero configuration. Run it from the backend directory of the server with the app's own interpreter:

    cd /var/www/html/pricing-app/backend && venv/bin/python /tmp/measure_pubml_p6.py

With no token it mints a short-lived (15 min) one, locally, with the app's `create_access_token`, for the first
active user that holds `ml_ops.ver` AND `ml_metricas.ver_ganancia` (the token is never printed), and it picks the
search words from the database (a frequent title word, a linked product's name word, a recent MLA) through a
read-only transaction. It talks to the local API (http://localhost:8002/api by default). `--token` / `$PUBML_TOKEN`,
`--term`, `--product-term`, `--mla` and `--base-url` override any of it; with a token given the app is not imported.
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
PAGE_BUDGET_MS = 500.0
SET_WIDE_BUDGET_MS = 1000.0
RUNS = 20
PATH = "/ml-publications/view/items"
TIMEOUT_SECONDS = 60
DEFAULT_TERM = "cable"
DEFAULT_PRODUCT_TERM = "camara"
REQUIRED_PERMISSIONS = frozenset({"ml_ops.ver", "ml_metricas.ver_ganancia"})
TOKEN_MINUTES = 15
MARKUP_FILTERS = ("markup_neg", "markup_min", "markup_max")


@dataclass(frozen=True)
class Scenario:
    name: str
    params: dict[str, Any]
    gate: bool = False  # the one scenario the P6b decision is read from

    @property
    def set_wide(self) -> bool:
        """Sorting or filtering by markup prices the whole filtered set; otherwise only the page is priced."""
        return self.params.get("orden") == "markup" or any(key in self.params for key in MARKUP_FILTERS)


def build_scenarios(term: str, product_term: str, mla: Optional[str] = None) -> list[Scenario]:
    scenarios = [
        Scenario("default page + markup", {"limit": 50}),
        Scenario("page 5 + markup", {"limit": 50, "offset": 200}),
        Scenario(f"search '{term}' + markup", {"limit": 50, "q": term}),
        Scenario("orden=markup (no other filter)  [P6b gate]", {"limit": 50, "orden": "markup"}, gate=True),
        Scenario("orden=markup desc", {"limit": 50, "orden": "markup", "dir": "desc"}),
        Scenario("orden=markup, page 5", {"limit": 50, "orden": "markup", "offset": 200}),
        Scenario("markup_neg=true, sort title", {"limit": 50, "markup_neg": "true", "orden": "titulo"}),
        Scenario("markup_min=0 markup_max=30", {"limit": 50, "markup_min": "0", "markup_max": "30"}),
        Scenario(f"orden=markup + search '{term}'", {"limit": 50, "orden": "markup", "q": term}),
        Scenario(
            f"orden=markup + search '{product_term}' (linked product)",
            {"limit": 50, "orden": "markup", "q": product_term},
        ),
        Scenario("orden=markup + estado=active", {"limit": 50, "orden": "markup", "estado": "active"}),
    ]
    if mla:
        scenarios.append(Scenario(f"search {mla} (exact) + markup", {"limit": 50, "q": mla}))
    return scenarios


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


class RequestFailed(Exception):
    pass


def fetch(base_url: str, token: str, params: dict[str, Any]) -> tuple[float, dict[str, float], dict[str, Any]]:
    """One GET of the list: (elapsed ms, server-side stages, JSON body)."""
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
    markup_stats: Optional[dict[str, Any]] = None
    ads: Optional[dict[str, Any]] = None
    has_markup: bool = True  # every row of the answer carried a `markup` block (the token sees margins)
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
            items = body.get("items", [])
            result.total, result.rows = body.get("total"), len(items)
            result.markup_stats, result.ads = body.get("markup_stats"), body.get("ads")
            result.has_markup = "markup_stats" in body and all("markup" in item for item in items)
    except RequestFailed as exc:
        result.error = str(exc)
    return result


def budget_of(scenario: Scenario, page_budget: float, set_wide_budget: float) -> float:
    return set_wide_budget if scenario.set_wide else page_budget


def report(result: Result, budget_ms: float) -> bool:
    """Print one scenario; True when it is within budget."""
    scenario = result.scenario
    kind = "set-wide" if scenario.set_wide else "page"
    if result.error:
        print(f"[{scenario.name}] FAIL {result.error}")
        return False
    p50, p95, worst = (percentile(result.samples, 50), percentile(result.samples, 95), max(result.samples))
    ok = p95 < budget_ms
    print(
        f"[{scenario.name}] {kind} n={len(result.samples)} p50={p50:.1f} ms p95={p95:.1f} ms max={worst:.1f} ms "
        f"(budget p95 < {budget_ms:g} ms) {'PASS' if ok else 'FAIL'}"
    )
    line = [f"pubml.view endpoint=items scenario={scenario.name!r}"]
    line += [f"{stage}_ms={percentile(values, 50):.1f}" for stage, values in result.stages.items()]
    line += [f"rows={result.rows}", f"total={result.total}"]
    print(" ".join(line))
    return ok


def describe_stats(stats: Optional[dict[str, Any]]) -> str:
    if not stats:
        return "markup_stats: missing"
    return (
        f"markup_stats: computed={stats.get('computed')} null_by_reason={stats.get('null_by_reason')} "
        f"ms={stats.get('ms')} (server-side, last request of the scenario)"
    )


def describe_ads(ads: Optional[dict[str, Any]]) -> str:
    if not ads:
        return "ads: missing"
    return f"ads: available={ads.get('available')} reason={ads.get('reason')} applied={ads.get('applied')}"


# --- zero configuration: a token and search words from the app itself ------------------------------------------


@dataclass(frozen=True)
class AutoConfig:
    token: str
    username: str
    term: str
    product_term: str
    mla: Optional[str]


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
    """Mint a token for an active user with `ml_ops.ver` + `ml_metricas.ver_ganancia` and pick search words."""
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
        term = frequent_word(titles, DEFAULT_TERM)
        description = db.execute(
            text("SELECT descripcion FROM productos_erp WHERE descripcion IS NOT NULL ORDER BY codigo LIMIT 1")
        ).scalar()
        product_term = frequent_word([description or ""], term)
        mla = db.execute(
            text(
                "SELECT item_id FROM ml_items WHERE gone_at IS NULL "
                "ORDER BY last_trigger_received_at DESC NULLS LAST LIMIT 1"
            )
        ).scalar()
    finally:
        db.rollback()
        db.close()
    token = create_access_token({"sub": username}, expires_delta=timedelta(minutes=TOKEN_MINUTES))
    return AutoConfig(token, username, term, product_term, mla)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only measurement of the markup in GET /ml-publications/view/items"
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--token", default=None, help="access token (default: $PUBML_TOKEN, else minted locally)")
    parser.add_argument("--term", default=None, help="word present in publication titles (default: picked)")
    parser.add_argument("--product-term", default=None, help="word present in linked product names (default: picked)")
    parser.add_argument("--mla", default=None, help="an MLA id: adds an exact-search scenario (default: a recent one)")
    parser.add_argument("--page-budget-ms", type=float, default=PAGE_BUDGET_MS)
    parser.add_argument("--set-wide-budget-ms", type=float, default=SET_WIDE_BUDGET_MS)
    args = parser.parse_args(argv)

    token = args.token or os.environ.get("PUBML_TOKEN")
    term, product_term, mla = args.term, args.product_term, args.mla
    if token:
        print("using the token given")
    else:
        config = auto_config()
        if config is None:
            print(
                "No token and no active user holding ml_ops.ver and ml_metricas.ver_ganancia could be found; "
                "pass --token (a user with both permissions) or run from the backend directory."
            )
            return 2
        token = config.token
        term, product_term, mla = term or config.term, product_term or config.product_term, mla or config.mla
        print(f"minted a {TOKEN_MINUTES}-minute token for {config.username} (ml_ops.ver + ml_metricas.ver_ganancia)")
    term, product_term = term or DEFAULT_TERM, product_term or DEFAULT_PRODUCT_TERM

    scenarios = build_scenarios(term, product_term, mla)
    print(f"words: term={term!r} product term={product_term!r} mla={mla}")
    print(f"measuring {args.base_url}{PATH}: {RUNS} requests per scenario after 1 warm-up, GET only")
    passed = True
    gate: Optional[Result] = None
    stats_line = ads_line = None
    for index, scenario in enumerate(scenarios):
        result = measure(args.base_url, token, scenario)
        if index == 0 and result.warmup_ms is not None:
            status_ms = result.warmup_stages.get("status")
            print(
                f"cold first request: {result.warmup_ms:.1f} ms (status {'n/a' if status_ms is None else f'{status_ms} ms'})"
            )
        passed = report(result, budget_of(scenario, args.page_budget_ms, args.set_wide_budget_ms)) and passed
        if result.error:
            continue
        if not result.has_markup:
            print(
                f"[{scenario.name}] the answer has no markup: the token's user needs ml_metricas.ver_ganancia "
                "(without it the response carries no markup keys)"
            )
            passed = False
        if scenario.gate:
            gate = result
        if scenario.set_wide and stats_line is None:
            stats_line, ads_line = describe_stats(result.markup_stats), describe_ads(result.ads)
    for line in (stats_line, ads_line):
        if line:
            print(line)
    if gate is not None and gate.samples:
        p95 = percentile(gate.samples, 95)
        needed = p95 > args.set_wide_budget_ms
        print(
            f"P6b gate (orden=markup, no other filter, 20 warm requests): p95={p95:.1f} ms -> "
            f"{'P6b NEEDED' if needed else 'P6b NOT needed'} (threshold {args.set_wide_budget_ms:g} ms)"
        )
    else:
        print("P6b gate: not measured (the gate scenario failed)")
    print(
        f"RESULT: {'PASS' if passed else 'FAIL'} (page path p95 < {args.page_budget_ms:g} ms, "
        f"set-wide p95 < {args.set_wide_budget_ms:g} ms)"
    )
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
