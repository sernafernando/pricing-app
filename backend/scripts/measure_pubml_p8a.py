#!/usr/bin/env python3
"""Read-only measurement of the publication detail (`GET /ml-publications/view/items/{item_id}`), P8a / R6.

It answers one question: is opening the Resumen of a publication fast enough (budget p95 < 150 ms, a proposal)? It
sends GET requests only: 1 warm-up plus 20 measured requests per scenario, then prints p50 / p95 / max against the
budget and, for each answer, how many links came back, the replenishment state, how many resources report their
freshness and whether the markup breakdown is there. It writes nothing anywhere. The scenarios are the publication
with the MOST variations (the worst case: the most links and the widest markup), a Full publication with stored
replenishment, and a publication without variations (the plain case); the token's user holds the margin permission,
so the markup breakdown (the three statements of the markup inputs and one shipping batch) is part of what is timed.

Zero configuration. Run it from the backend directory of the server with the app's own interpreter:

    cd /var/www/html/pricing-app/backend && venv/bin/python /tmp/measure_pubml_p8a.py

With no token it mints a short-lived (15 min) one, locally, with the app's `create_access_token`, for the first
active user that holds `ml_ops.ver` AND `ml_metricas.ver_ganancia` (the token is never printed), and it picks the
publications from the database through a read-only transaction. It talks to the local API
(http://localhost:8002/api by default). `--token` / `$PUBML_TOKEN`, `--mla`, `--full-mla`, `--plain-mla` and
`--base-url` override any of it; with a token given the app is not imported.
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
BUDGET_MS = 150.0
RUNS = 20
PATH = "/ml-publications/view/items/{item_id}"
TIMEOUT_SECONDS = 60
REQUIRED_PERMISSIONS = frozenset({"ml_ops.ver", "ml_metricas.ver_ganancia"})
TOKEN_MINUTES = 15


# The three publications measured, picked from the database (the statements are exercised by the Postgres test).
BIG_SQL = (
    "SELECT v.item_id FROM ml_item_variations v JOIN ml_items i ON i.item_id = v.item_id "
    "WHERE v.gone_at IS NULL AND i.gone_at IS NULL AND i.never_existed IS NOT TRUE "
    "GROUP BY v.item_id ORDER BY count(*) DESC, v.item_id LIMIT 1"
)
FULL_SQL = (
    "SELECT i.item_id FROM ml_items i JOIN ml_user_product_replenishment r "
    "ON r.user_product_id = i.user_product_id WHERE i.gone_at IS NULL AND i.never_existed IS NOT TRUE "
    "AND i.logistic_type = 'fulfillment' AND r.http_status BETWEEN 200 AND 299 "
    "ORDER BY i.last_trigger_received_at DESC NULLS LAST, i.item_id LIMIT 1"
)
PLAIN_SQL = (
    "SELECT i.item_id FROM ml_items i WHERE i.gone_at IS NULL AND i.never_existed IS NOT TRUE "
    "AND NOT EXISTS (SELECT 1 FROM ml_item_variations v WHERE v.item_id = i.item_id AND v.gone_at IS NULL) "
    "AND EXISTS (SELECT 1 FROM ml_item_product_links l WHERE l.item_id = i.item_id AND l.variation_id = 0 "
    "AND l.match_status = 'linked') "
    "ORDER BY i.last_trigger_received_at DESC NULLS LAST, i.item_id LIMIT 1"
)


@dataclass(frozen=True)
class Scenario:
    name: str
    item_id: str
    params: dict[str, Any] = field(default_factory=dict)


def build_scenarios(big: Optional[str], full: Optional[str], plain: Optional[str]) -> list[Scenario]:
    """One scenario per distinct publication, in the order: most variations, Full with replenishment, plain."""
    scenarios: list[Scenario] = []
    seen: list[str] = []
    for label, item_id in (("most variations", big), ("Full with replenishment", full), ("plain", plain)):
        if item_id and item_id not in seen:
            seen.append(item_id)
            scenarios.append(Scenario(f"{label} ({item_id})", item_id))
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
    """One GET of the sub-rows: (elapsed ms, server-side stages, JSON body)."""
    path = PATH.format(item_id=urllib.parse.quote(scenario.item_id))
    url = base_url.rstrip("/") + path + ("?" + urllib.parse.urlencode(scenario.params) if scenario.params else "")
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
    links: Optional[int] = None
    freshness: Optional[int] = None
    replenishment: Optional[str] = None  # its state, "-" when null (not Full)
    has_margin: bool = True  # the answer has the `markup_breakdown` key (the token sees margins)
    breakdown_priced: Optional[bool] = None  # the breakdown has figures (the publication could be priced)
    warmup_ms: Optional[float] = None  # the uncounted first request


def summarize(result: Result, body: dict[str, Any]) -> None:
    result.links = len(body.get("links", []))
    result.freshness = len(body.get("freshness", []))
    replenishment = body.get("replenishment")
    result.replenishment = "-" if replenishment is None else replenishment.get("status")
    result.has_margin = "markup_breakdown" in body
    result.breakdown_priced = body.get("markup_breakdown") is not None


def measure(base_url: str, token: str, scenario: Scenario, runs: int = RUNS) -> Result:
    result = Result(scenario)
    try:
        result.warmup_ms, _, _ = fetch(base_url, token, scenario)  # not counted
        for _ in range(runs):
            elapsed, stages, body = fetch(base_url, token, scenario)
            result.samples.append(elapsed)
            for name, ms in stages.items():
                result.stages.setdefault(name, []).append(ms)
            summarize(result, body)
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
    line = [f"pubml.view endpoint=detail scenario={scenario.name!r}"]
    line += [f"{stage}_ms={percentile(values, 50):.1f}" for stage, values in result.stages.items()]
    line.append(f"links={result.links} freshness={result.freshness} replenishment={result.replenishment}")
    line.append(f"breakdown={'priced' if result.breakdown_priced else 'null'}")
    print(" ".join(line))
    return ok


# --- zero configuration: a token and publications from the app itself -------------------------------------------


@dataclass(frozen=True)
class AutoConfig:
    token: str
    username: str
    big_mla: Optional[str]
    full_mla: Optional[str]
    plain_mla: Optional[str]


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
    """Mint a token for an active user with `ml_ops.ver` + `ml_metricas.ver_ganancia` and pick publications."""
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
        failures: list[str] = []
        username = pick_user(users, lambda name: service.obtener_permisos_usuario(users[name]), failures)
        if username is None:
            for failure in failures[:3]:
                print(f"could not read the permissions of {failure}")
            return None
        big, full, plain = (db.execute(text(sql)).scalar() for sql in (BIG_SQL, FULL_SQL, PLAIN_SQL))
    finally:
        db.rollback()
        db.close()
    token = create_access_token({"sub": username}, expires_delta=timedelta(minutes=TOKEN_MINUTES))
    return AutoConfig(token, username, big, full, plain)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only measurement of GET /ml-publications/view/items/{id}")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--token", default=None, help="access token (default: $PUBML_TOKEN, else minted locally)")
    parser.add_argument("--mla", default=None, help="the publication with many variations (default: the one with most)")
    parser.add_argument("--full-mla", default=None, help="a Full publication with replenishment (default: picked)")
    parser.add_argument("--plain-mla", default=None, help="a linked publication without variations (default: picked)")
    parser.add_argument("--budget-ms", type=float, default=BUDGET_MS)
    args = parser.parse_args(argv)

    token = args.token or os.environ.get("PUBML_TOKEN")
    big, full, plain = args.mla, args.full_mla, args.plain_mla
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
        big, full, plain = big or config.big_mla, full or config.full_mla, plain or config.plain_mla
        print(f"minted a {TOKEN_MINUTES}-minute token for {config.username} (ml_ops.ver + ml_metricas.ver_ganancia)")

    scenarios = build_scenarios(big, full, plain)
    if not scenarios:
        print("No publication could be found; pass --mla (any MLA id of the store).")
        return 2
    print(f"measuring {args.base_url}{PATH}: {RUNS} requests per scenario after 1 warm-up, GET only")
    passed = True
    for scenario in scenarios:
        result = measure(args.base_url, token, scenario)
        passed = report(result, args.budget_ms) and passed
        if result.error:
            continue
        if not result.has_margin:
            print(
                f"[{scenario.name}] the answer has no markup_breakdown: the token's user needs "
                "ml_metricas.ver_ganancia (the margin path is what this script times)"
            )
            passed = False
    print(f"RESULT: {'PASS' if passed else 'FAIL'} (p95 < {args.budget_ms:g} ms per scenario)")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
