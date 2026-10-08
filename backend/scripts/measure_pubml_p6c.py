#!/usr/bin/env python3
"""Read-only measurement of the variation sub-rows (`GET /ml-publications/view/items/{item_id}/variations`), P6c / R6.

It answers one question: is the expanded row fast enough (budget p95 < 150 ms, a proposal)? It sends GET requests
only: 1 warm-up plus 20 measured requests per scenario, then prints p50 / p95 / max against the budget and, for each
answer, how many sub-rows came back and whether they carry cost and markup. It writes nothing anywhere. The
scenarios are the publication with the MOST variations (the worst case of the endpoint), one with just a few, and
the first again with the Ads cost subtracted over the last 30 days (ignored and reported while there is no Ads
data).

Zero configuration. Run it from the backend directory of the server with the app's own interpreter:

    cd /var/www/html/pricing-app/backend && venv/bin/python /tmp/measure_pubml_p6c.py

With no token it mints a short-lived (15 min) one, locally, with the app's `create_access_token`, for the first
active user that holds `ml_ops.ver` AND `ml_metricas.ver_ganancia` (the token is never printed), and it picks the
publications from the database through a read-only transaction. It talks to the local API
(http://localhost:8002/api by default). `--token` / `$PUBML_TOKEN`, `--mla`, `--small-mla` and `--base-url`
override any of it; with a token given the app is not imported.
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
from datetime import date, timedelta
from typing import Any, Callable, Iterable, Optional, Sequence

DEFAULT_BASE_URL = "http://localhost:8002/api"
BUDGET_MS = 150.0
RUNS = 20
PATH = "/ml-publications/view/items/{item_id}/variations"
TIMEOUT_SECONDS = 60
REQUIRED_PERMISSIONS = frozenset({"ml_ops.ver", "ml_metricas.ver_ganancia"})
TOKEN_MINUTES = 15
ADS_DAYS = 30


@dataclass(frozen=True)
class Scenario:
    name: str
    item_id: str
    params: dict[str, Any] = field(default_factory=dict)


def ads_period(today: date) -> dict[str, str]:
    """The last `ADS_DAYS` full days before `today`."""
    return {
        "ads_desde": (today - timedelta(days=ADS_DAYS)).isoformat(),
        "ads_hasta": (today - timedelta(days=1)).isoformat(),
    }


def build_scenarios(big: str, small: Optional[str], today: date) -> list[Scenario]:
    scenarios = [Scenario(f"most variations ({big})", big)]
    if small and small != big:
        scenarios.append(Scenario(f"few variations ({small})", small))
    scenarios.append(
        Scenario(
            f"most variations ({big}) + restar_publicidad", big, {"restar_publicidad": "true", **ads_period(today)}
        )
    )
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
    rows: Optional[int] = None
    has_margin: bool = True  # every sub-row of the answer carried `costo` and `markup` (the token sees margins)
    ads: Optional[dict[str, Any]] = None
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
            sub_rows = body.get("variations", [])
            result.rows = len(sub_rows)
            result.has_margin = body.get("can_see_margin") is True and all(
                "costo" in row and "markup" in row for row in sub_rows
            )
            result.ads = body.get("ads")
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
    line = [f"pubml.view endpoint=variations scenario={scenario.name!r}"]
    line += [f"{stage}_ms={percentile(values, 50):.1f}" for stage, values in result.stages.items()]
    line.append(f"sub_rows={result.rows}")
    print(" ".join(line))
    if result.ads:
        publication = result.ads.get("publication")
        print(
            f"  ads: available={result.ads.get('available')} reason={result.ads.get('reason')} "
            f"applied={result.ads.get('applied')} publication={publication}"
        )
    return ok


# --- zero configuration: a token and publications from the app itself -------------------------------------------


@dataclass(frozen=True)
class AutoConfig:
    token: str
    username: str
    big_mla: Optional[str]
    small_mla: Optional[str]


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
        username = pick_user(users, lambda name: service.obtener_permisos_usuario(users[name]))
        if username is None:
            return None
        counted = (
            "SELECT v.item_id FROM ml_item_variations v JOIN ml_items i ON i.item_id = v.item_id "
            "WHERE v.gone_at IS NULL AND i.gone_at IS NULL GROUP BY v.item_id HAVING count(*) >= 2 "
        )
        big = db.execute(text(counted + "ORDER BY count(*) DESC, v.item_id LIMIT 1")).scalar()
        small = db.execute(text(counted + "ORDER BY count(*), v.item_id LIMIT 1")).scalar()
    finally:
        db.rollback()
        db.close()
    token = create_access_token({"sub": username}, expires_delta=timedelta(minutes=TOKEN_MINUTES))
    return AutoConfig(token, username, big, small)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only measurement of GET /ml-publications/view/items/{id}/variations"
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--token", default=None, help="access token (default: $PUBML_TOKEN, else minted locally)")
    parser.add_argument("--mla", default=None, help="the publication with many variations (default: the one with most)")
    parser.add_argument("--small-mla", default=None, help="a publication with a few variations (default: picked)")
    parser.add_argument("--budget-ms", type=float, default=BUDGET_MS)
    args = parser.parse_args(argv)

    token = args.token or os.environ.get("PUBML_TOKEN")
    big, small = args.mla, args.small_mla
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
        big, small = big or config.big_mla, small or config.small_mla
        print(f"minted a {TOKEN_MINUTES}-minute token for {config.username} (ml_ops.ver + ml_metricas.ver_ganancia)")
    if not big:
        print("No publication with variations could be found; pass --mla (an MLA id that has variations).")
        return 2

    scenarios = build_scenarios(big, small, date.today())
    print(f"measuring {args.base_url}{PATH}: {RUNS} requests per scenario after 1 warm-up, GET only")
    passed = True
    for scenario in scenarios:
        result = measure(args.base_url, token, scenario)
        passed = report(result, args.budget_ms) and passed
        if result.error:
            continue
        if not result.rows:
            print(f"[{scenario.name}] the answer has no sub-rows: the publication has no live variations")
            passed = False
        if not result.has_margin:
            print(
                f"[{scenario.name}] the answer has no cost/markup: the token's user needs ml_metricas.ver_ganancia "
                "(without it the sub-rows carry neither)"
            )
            passed = False
    print(f"RESULT: {'PASS' if passed else 'FAIL'} (p95 < {args.budget_ms:g} ms per scenario)")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
