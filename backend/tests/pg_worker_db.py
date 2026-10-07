"""One PostgreSQL database per pytest-xdist worker.

`@pytest.mark.postgres` tests create/drop real tables (and schemas) inside a
single database, so two workers sharing it would trample each other. Under
xdist every worker therefore gets its own database, `<base>_<worker>` (e.g.
`pricing_test_gw0`), and `POSTGRES_TEST_URL` is rewritten to point at it
before anything reads it. Without xdist nothing changes.

Databases are intentionally never dropped: CI containers are ephemeral and
local reruns reuse them (the fixtures clean up their own tables).
"""

import re
import time
from typing import Mapping

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, OperationalError

DEFAULT_POSTGRES_TEST_URL = "postgresql+psycopg2://postgres@localhost:5432/pricing_test"

_WORKER_ID = re.compile(r"^[A-Za-z0-9]+$")


def worker_database_url(base_url: str, worker_id: str) -> str:
    """Return `base_url` with the database name suffixed by `_<worker_id>`."""
    if not _WORKER_ID.match(worker_id):
        raise ValueError(f"Unsafe xdist worker id: {worker_id!r}")
    url = make_url(base_url)
    return url.set(database=f"{url.database}_{worker_id}").render_as_string(hide_password=False)


def resolve_postgres_test_url(env: Mapping[str, str]) -> str:
    """The URL every Postgres fixture must use for this process."""
    base = env.get("POSTGRES_TEST_URL", DEFAULT_POSTGRES_TEST_URL)
    worker = env.get("PYTEST_XDIST_WORKER")
    return worker_database_url(base, worker) if worker else base


def ensure_database(url: str, attempts: int = 5) -> None:
    """Create the database in `url` if missing, via the server's `postgres` DB.

    Safe to call concurrently and repeatedly: an already-existing database is
    success, and a transient "template1 is being accessed by other users"
    (parallel CREATE DATABASE) is retried. Raises if the server is unreachable.
    """
    target = make_url(url)
    admin = create_engine(target.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        for attempt in range(attempts):
            try:
                with admin.connect() as conn:
                    exists = conn.execute(
                        text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": target.database}
                    ).scalar()
                    if exists:
                        return
                    conn.execute(text(f'CREATE DATABASE "{target.database}"'))
                    return
            except DBAPIError as exc:
                message = str(exc.orig)
                if "already exists" in message:
                    return
                if attempt == attempts - 1 or "being accessed by other users" not in message:
                    raise
                time.sleep(0.2 * (attempt + 1))
    finally:
        admin.dispose()


def server_reachable(url: str) -> bool:
    """Whether the server in `url` accepts a connection to its `postgres` DB."""
    admin = create_engine(make_url(url).set(database="postgres"))
    try:
        with admin.connect():
            return True
    except OperationalError:
        return False
    finally:
        admin.dispose()


def configure_environment(env: "dict[str, str]") -> str:
    """Point `POSTGRES_TEST_URL` at this worker's database (xdist only).

    Returns the effective URL. If the server is unreachable the URL is still
    exported and nothing is created, so the postgres tests skip exactly as
    they do without xdist. If the server IS reachable, any failure to create
    the database propagates and aborts the run: swallowing it would turn every
    postgres test of the worker into a silent skip behind a green job.
    """
    url = resolve_postgres_test_url(env)
    if env.get("PYTEST_XDIST_WORKER"):
        env["POSTGRES_TEST_URL"] = url
        if server_reachable(url):
            ensure_database(url)
    return url
