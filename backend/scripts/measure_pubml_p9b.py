#!/usr/bin/env python3
"""Read-only measurement of the Publicaciones KPI strip (`GET /ml-publications/view/kpis`), P9b / R6.

It answers one question: is the strip fast enough (owner budget: p95 < 1 s)? It sends GET requests only: 1 warm-up
plus 20 measured requests per scenario, then prints p50 / p95 / max against the budget and, for each answer, how many
publications the filter selected and the units of the period. It writes nothing anywhere. The scenarios are the whole
store for the default 30 days, the whole store for 90 days (the widest preset), the busiest brand and the active
publications (the filters that shrink the set the Board is restricted to).

Zero configuration. Run it from the backend directory of the server with the app's own interpreter:

    cd /var/www/html/pricing-app/backend && venv/bin/python /tmp/measure_pubml_p9b.py

With no token it mints a short-lived (15 min) one, locally, with the app's `create_access_token`, for the first
active user that holds `ml_ops.ver` AND `ml_metricas.ver` (the token is never printed), and it picks the brand through
a read-only transaction. It talks to the local API (http://localhost:8002/api by default). `--token` / `$PUBML_TOKEN`,
`--marca` and `--base-url` override any of it; with a token given the app is not imported.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Callable, Iterable, Optional, Sequence

DEFAULT_BASE_URL = "http://localhost:8002/api"
PATH = "/ml-publications/view/kpis"
BUDGET_MS = 1000.0
RUNS = 20
TIMEOUT_SECONDS = 60
REQUIRED_PERMISSIONS = frozenset({"ml_ops.ver", "ml_metricas.ver"})
TOKEN_MINUTES = 15
PICK_TIMEOUT = "20s"

BUSIEST_BRAND_SQL = (
    "SELECT p.marca FROM ml_item_product_links l JOIN productos_erp p ON p.item_id = l.producto_item_id "
    "WHERE l.variation_id = 0 AND p.marca IS NOT NULL "
    'GROUP BY p.marca ORDER BY count(*) DESC, p.marca COLLATE "C" LIMIT 1'
)


@dataclass(frozen=True)
class Scenario:
    name: str
    params: dict[str, str]


def build_scenarios(marca: Optional[str]) -> list[Scenario]:
    """The whole store for the default and the widest period, then the filters that shrink the set."""
    scenarios = [Scenario("all, 30 days", {}), Scenario("all, 90 days", {"periodo": "90"})]
    if marca:
        scenarios.append(Scenario(f"brand {marca!r}, 30 days", {"marcas": marca}))
    scenarios.append(Scenario("active, 30 days", {"estado": "active"}))
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


def fetch(base_url: str, token: str, scenario: Scenario) -> tuple[float, dict[str, float], dict[str, Any]]:
    """One GET of the strip: (elapsed ms, server-side stages, JSON body)."""
    url = base_url.rstrip("/") + PATH + "?" + urllib.parse.urlencode(scenario.params)
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
    try:
        return elapsed, stages, json.loads(raw)
    except ValueError as exc:  # a 200 that is not JSON (a proxy's page): reported, not a stack trace
        raise RequestFailed("the answer is not JSON") from exc


@dataclass
class Result:
    scenario: Scenario
    samples: list[float] = field(default_factory=list)
    stages: dict[str, list[float]] = field(default_factory=dict)
    error: Optional[str] = None
    mla_count: Optional[int] = None
    units: Optional[int] = None
    warmup_ms: Optional[float] = None  # the uncounted first request


def measure(base_url: str, token: str, scenario: Scenario, runs: int = RUNS) -> Result:
    result = Result(scenario)
    try:
        result.warmup_ms, _, _ = fetch(base_url, token, scenario)  # not counted
        for _ in range(runs):
            elapsed, stages, body = fetch(base_url, token, scenario)
            result.samples.append(elapsed)
            for name, ms in stages.items():
                result.stages.setdefault(name, []).append(ms)
            result.mla_count = body.get("mla_count")
            result.units = body.get("kpis", {}).get("units", {}).get("value")
    except RequestFailed as exc:
        result.error = str(exc)
    return result


def report(result: Result, budget_ms: float) -> bool:
    """Print one scenario; True when it is within budget."""
    scenario = result.scenario
    if result.error:
        print(f"[{scenario.name}] FAIL {result.error}")
        return False
    p50, p95, worst = (percentile(result.samples, 50), percentile(result.samples, 95), max(result.samples))
    ok = p95 < budget_ms
    print(
        f"[{scenario.name}] n={len(result.samples)} p50={p50:.1f} ms p95={p95:.1f} ms max={worst:.1f} ms "
        f"(budget p95 < {budget_ms:g} ms) {'PASS' if ok else 'FAIL'}"
    )
    line = [f"pubml.view endpoint=kpis scenario={scenario.name!r}"]
    line += [f"{stage}_ms={percentile(values, 50):.1f}" for stage, values in result.stages.items()]
    line.append(f"mla_count={result.mla_count} units={result.units}")
    print(" ".join(line))
    return ok


# --- zero configuration: a token and a brand from the app itself ---------------------------------------------------


@dataclass(frozen=True)
class AutoConfig:
    token: str
    username: str
    marca: Optional[str]


def pick_user(
    names: Iterable[str], permissions_of: Callable[[str], Iterable[str]], failures: Optional[list[str]] = None
) -> Optional[str]:
    """The first user that holds every required permission; one whose permissions cannot be read is skipped (and
    its error appended to `failures`, so the caller can say why nobody was found)."""
    for name in names:
        try:
            if REQUIRED_PERMISSIONS <= set(permissions_of(name)):
                return name
        except Exception as exc:
            if failures is not None:
                failures.append(f"{name}: {exc}")
    return None


def auto_config() -> Optional[AutoConfig]:
    """Mint a token for an active user with both permissions and pick the busiest brand."""
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
            db.execute(text(f"SET LOCAL statement_timeout = '{PICK_TIMEOUT}'"))
        except Exception:  # not PostgreSQL: the queries below are SELECTs anyway
            db.rollback()
        service = PermisosService(db)
        users = {
            (u.username or u.email): u
            for u in db.query(Usuario).filter(Usuario.activo.is_(True)).order_by(Usuario.id).all()
            if (u.username or u.email)
        }
        failures: list[str] = []
        username = pick_user(users, lambda name: service.obtener_permisos_usuario(users[name]), failures)
        if username is None:
            for failure in failures[:3]:
                print(f"could not read the permissions of {failure}")
            return None
        marca = db.execute(text(BUSIEST_BRAND_SQL)).scalar()
    finally:
        db.rollback()
        db.close()
    token = create_access_token({"sub": username}, expires_delta=timedelta(minutes=TOKEN_MINUTES))
    return AutoConfig(token, username, marca)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only measurement of GET /ml-publications/view/kpis")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--token", default=None, help="access token (default: $PUBML_TOKEN, else minted locally)")
    parser.add_argument("--marca", default=None, help="the brand to filter by (default: the busiest one)")
    parser.add_argument("--budget-ms", type=float, default=BUDGET_MS)
    args = parser.parse_args(argv)

    token = args.token or os.environ.get("PUBML_TOKEN")
    marca = args.marca
    if token:
        print("using the token given")
    else:
        config = auto_config()
        if config is None:
            print(
                "No token and no active user holding ml_ops.ver and ml_metricas.ver could be found; "
                "pass --token or run from the backend directory."
            )
            return 2
        token, marca = config.token, marca or config.marca
        print(f"minted a {TOKEN_MINUTES}-minute token for {config.username} (ml_ops.ver, ml_metricas.ver)")

    print(f"measuring {args.base_url}{PATH}: {RUNS} requests per scenario after 1 warm-up, GET only")
    passed = True
    for scenario in build_scenarios(marca):
        passed = report(measure(args.base_url, token, scenario), args.budget_ms) and passed
    print(f"RESULT: {'PASS' if passed else 'FAIL'} (p95 < {args.budget_ms:g} ms per scenario)")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
