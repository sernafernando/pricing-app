"""Per-xdist-worker PostgreSQL database isolation (tests/pg_worker_db.py)."""

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from tests import pg_worker_db

BASE = "postgresql+psycopg2://postgres:pw@localhost:5432/pricing_test"


class TestWorkerDatabaseUrl:
    def test_appends_worker_id_to_the_database_name(self):
        url = pg_worker_db.worker_database_url(BASE, "gw0")
        assert url == "postgresql+psycopg2://postgres:pw@localhost:5432/pricing_test_gw0"

    def test_distinct_workers_get_distinct_databases(self):
        assert pg_worker_db.worker_database_url(BASE, "gw0") != pg_worker_db.worker_database_url(BASE, "gw1")

    def test_hostile_worker_id_is_rejected(self):
        with pytest.raises(ValueError):
            pg_worker_db.worker_database_url(BASE, 'gw0"; DROP DATABASE x; --')


class TestResolveEnv:
    def test_without_xdist_the_env_is_untouched(self):
        env = {"POSTGRES_TEST_URL": BASE}
        assert pg_worker_db.resolve_postgres_test_url(env) == BASE

    def test_without_xdist_and_without_env_the_default_is_used(self):
        assert pg_worker_db.resolve_postgres_test_url({}) == pg_worker_db.DEFAULT_POSTGRES_TEST_URL

    def test_under_xdist_the_url_is_per_worker(self):
        env = {"POSTGRES_TEST_URL": BASE, "PYTEST_XDIST_WORKER": "gw3"}
        assert pg_worker_db.resolve_postgres_test_url(env).endswith("/pricing_test_gw3")

    def test_under_xdist_the_default_is_also_per_worker(self):
        env = {"PYTEST_XDIST_WORKER": "gw1"}
        assert pg_worker_db.resolve_postgres_test_url(env).endswith("/pricing_test_gw1")


@pytest.mark.postgres
def test_ensure_database_creates_once_and_is_idempotent():
    from tests.conftest import _postgres_reachable

    if not _postgres_reachable():
        pytest.skip("PostgreSQL not reachable")
    import os

    base = os.environ["POSTGRES_TEST_URL"]
    url = pg_worker_db.worker_database_url(base, "unitcheck")
    pg_worker_db.ensure_database(url)
    pg_worker_db.ensure_database(url)  # second call must not raise
    eng = create_engine(url)
    with eng.connect() as conn:
        assert conn.execute(text("select 1")).scalar() == 1
    eng.dispose()
    admin = create_engine(base, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{make_url(url).database}"'))
    admin.dispose()
