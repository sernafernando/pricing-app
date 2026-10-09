#!/usr/bin/env python3
"""Read-only measurement of the publication events and history (`GET /ml-publications/view/items/{id}/events` and
`/history`), P8b / R6.

It answers one question: are the Eventos and Historial tabs fast enough (budget p95 < 100 ms, a proposal)? It sends GET
requests only: 1 warm-up plus 20 measured requests per scenario, then prints p50 / p95 / max against the budget and,
for each answer, how many rows came back and whether another page exists. It writes nothing anywhere. The scenarios
are, per endpoint, the publication with the MOST rows in the last 30 days (the worst case for the first page), the
second page of that publication (the keyset path, with the cursor the first page returned) and the most recently
active publication (the plain case).

Zero configuration. Run it from the backend directory of the server with the app's own interpreter:

    cd /var/www/html/pricing-app/backend && venv/bin/python /tmp/measure_pubml_p8b.py

With no token it mints a short-lived (15 min) one, locally, with the app's `create_access_token`, for the first
active user that holds `ml_ops.ver` (the token is never printed), and it picks the publications from the database
through a read-only transaction. It talks to the local API (http://localhost:8002/api by default). `--token` /
`$PUBML_TOKEN`, `--mla`, `--recent-mla` and `--base-url` override any of it; with a token given the app is not
imported. The events endpoint answers an empty list while `events.enabled` is off: the report says so, because then
only the existence check of the publication is being timed.
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
BUDGET_MS = 100.0
RUNS = 20
ENDPOINTS = {
    "events": "/ml-publications/view/items/{item_id}/events",
    "history": "/ml-publications/view/items/{item_id}/history",
}
PAGE_SIZE = {"events": 50, "history": 20}  # the largest page the endpoint answers is measured, not the default
TIMEOUT_SECONDS = 60
REQUIRED_PERMISSIONS = frozenset({"ml_ops.ver"})
TOKEN_MINUTES = 15
PICK_TIMEOUT = "20s"

# The publications measured, picked from the database (the statements are read-only; the window keeps them cheap).
BUSIEST_SQL = {
    "events": (
        "SELECT e.item_id FROM ml_item_events e WHERE e.observed_at >= now() - interval '30 days' "
        'GROUP BY e.item_id ORDER BY count(*) DESC, e.item_id COLLATE "C" LIMIT 1'
    ),
    "history": (
        "SELECT c.item_id FROM ml_change_log c "
        "WHERE c.item_id IS NOT NULL AND c.observed_at >= now() - interval '30 days' "
        'GROUP BY c.item_id ORDER BY count(*) DESC, c.item_id COLLATE "C" LIMIT 1'
    ),
}
RECENT_SQL = {
    "events": "SELECT item_id FROM ml_item_events ORDER BY observed_at DESC, id DESC LIMIT 1",
    "history": "SELECT item_id FROM ml_change_log WHERE item_id IS NOT NULL ORDER BY observed_at DESC, id DESC LIMIT 1",
}


@dataclass(frozen=True)
class Scenario:
    name: str
    endpoint: str  # "events" or "history"
    item_id: str
    cursor: Optional[str] = None
    deep: bool = False  # the cursor is taken from the first page of the same publication at run time


def build_scenarios(
    busiest: dict[str, Optional[str]],
    recent: dict[str, Optional[str]],
    override: Optional[str],
    recent_override: Optional[str],
) -> list[Scenario]:
    """Per endpoint: the busiest publication (first page, then second page) and the most recent one. An explicit MLA
    replaces the busiest; one publication is never measured twice for the same endpoint and page."""
    scenarios: list[Scenario] = []
    for endpoint in ENDPOINTS:
        top = override or busiest.get(endpoint)
        if top:
            scenarios.append(Scenario(f"{endpoint}: busiest ({top})", endpoint, top))
            scenarios.append(Scenario(f"{endpoint}: busiest, page 2 ({top})", endpoint, top, deep=True))
        latest = recent_override or recent.get(endpoint)
        if latest and latest != top:
            scenarios.append(Scenario(f"{endpoint}: most recent ({latest})", endpoint, latest))
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
    """One GET of an events/history page: (elapsed ms, server-side stages, JSON body)."""
    path = ENDPOINTS[scenario.endpoint].format(item_id=urllib.parse.quote(scenario.item_id))
    params = {"limit": PAGE_SIZE[scenario.endpoint]}
    if scenario.cursor:
        params["cursor"] = scenario.cursor
    url = base_url.rstrip("/") + path + "?" + urllib.parse.urlencode(params)
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
    rows: Optional[int] = None
    more: Optional[bool] = None  # another page exists
    events_enabled: Optional[bool] = None  # events endpoint only
    warmup_ms: Optional[float] = None  # the uncounted first request


def summarize(result: Result, body: dict[str, Any]) -> None:
    rows = body.get("events" if result.scenario.endpoint == "events" else "entries", [])
    result.rows = len(rows)
    result.more = body.get("next_cursor") is not None
    if result.scenario.endpoint == "events":
        result.events_enabled = body.get("enabled")


def resolve_cursor(base_url: str, token: str, scenario: Scenario) -> Scenario:
    """The scenario of a second page: its cursor is the one the first page of the publication answers."""
    _, _, first = fetch(base_url, token, Scenario(scenario.name, scenario.endpoint, scenario.item_id))
    cursor = first.get("next_cursor")
    if not cursor:
        raise RequestFailed("the publication has no second page (fewer rows than one page)")
    return Scenario(scenario.name, scenario.endpoint, scenario.item_id, cursor)


def measure(base_url: str, token: str, scenario: Scenario, runs: int = RUNS) -> Result:
    result = Result(scenario)
    try:
        if scenario.deep:
            scenario = resolve_cursor(base_url, token, scenario)
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
    line = [f"pubml.view endpoint={scenario.endpoint} scenario={scenario.name!r}"]
    line += [f"{stage}_ms={percentile(values, 50):.1f}" for stage, values in result.stages.items()]
    line.append(f"rows={result.rows} more={result.more}")
    print(" ".join(line))
    if result.events_enabled is False:
        print(f"[{scenario.name}] events.enabled is off: the answer is empty, only the publication lookup was timed")
    return ok


# --- zero configuration: a token and publications from the app itself -------------------------------------------


@dataclass(frozen=True)
class AutoConfig:
    token: str
    username: str
    busiest: dict[str, Optional[str]]
    recent: dict[str, Optional[str]]


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
    """Mint a token for an active user with `ml_ops.ver` and pick the publications."""
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
        busiest = {endpoint: db.execute(text(sql)).scalar() for endpoint, sql in BUSIEST_SQL.items()}
        recent = {endpoint: db.execute(text(sql)).scalar() for endpoint, sql in RECENT_SQL.items()}
    finally:
        db.rollback()
        db.close()
    token = create_access_token({"sub": username}, expires_delta=timedelta(minutes=TOKEN_MINUTES))
    return AutoConfig(token, username, busiest, recent)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only measurement of GET /ml-publications/view/items/{id}/events|history"
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--token", default=None, help="access token (default: $PUBML_TOKEN, else minted locally)")
    parser.add_argument("--mla", default=None, help="the publication with many rows (default: the busiest of each)")
    parser.add_argument("--recent-mla", default=None, help="the plain-case publication (default: the most recent)")
    parser.add_argument("--budget-ms", type=float, default=BUDGET_MS)
    args = parser.parse_args(argv)

    token = args.token or os.environ.get("PUBML_TOKEN")
    busiest: dict[str, Optional[str]] = {}
    recent: dict[str, Optional[str]] = {}
    if token:
        print("using the token given")
    else:
        config = auto_config()
        if config is None:
            print(
                "No token and no active user holding ml_ops.ver could be found; "
                "pass --token (a user with ml_ops.ver) or run from the backend directory."
            )
            return 2
        token, busiest, recent = config.token, config.busiest, config.recent
        print(f"minted a {TOKEN_MINUTES}-minute token for {config.username} (ml_ops.ver)")

    scenarios = build_scenarios(busiest, recent, args.mla, args.recent_mla)
    if not scenarios:
        print("No publication could be found; pass --mla (any MLA id of the store).")
        return 2
    print(
        f"measuring {args.base_url}/ml-publications/view/items/{{id}}/events|history: "
        f"{RUNS} requests per scenario after 1 warm-up, GET only"
    )
    passed = True
    for scenario in scenarios:
        passed = report(measure(args.base_url, token, scenario), args.budget_ms) and passed
    print(f"RESULT: {'PASS' if passed else 'FAIL'} (p95 < {args.budget_ms:g} ms per scenario)")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
