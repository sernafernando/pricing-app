"""SQL-level tests (real PostgreSQL) for the shared catalog-expiry predicate
used by the set-based ml_item_promotions readers.

An expired catalog row (ml_promotions.finish_date in the past) must not count
as an active promo; future / NULL catalog finish / no catalog row must. The
readers' SQL really runs here (bool_or, FILTER, array_agg are Postgres-only),
against minimal mlwebhook-shaped tables in a throwaway schema.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, text

pytestmark = pytest.mark.postgres

PAST = "2020-01-01T00:00:00Z"
FUTURE = "2099-01-01T00:00:00Z"

# (mla, promotion_id, status)
_ITEM_ROWS = [
    ("S_EXP", "P_EXP", "started"),
    ("S_FUT", "P_FUT", "started"),
    ("S_NOCAT", "P_NOCAT", "started"),
    ("S_NULL", "P_NULL", "started"),
    ("C_EXP", "P_EXP", "candidate"),
    ("C_FUT", "P_FUT", "candidate"),
    ("C_NOCAT", "P_NOCAT", "candidate"),
    # candidate still valid + started already expired
    ("MIX", "P_FUT", "candidate"),
    ("MIX", "P_EXP", "started"),
]


@pytest.fixture(scope="module")
def mlw_engine():
    from tests.conftest import POSTGRES_TEST_URL, _postgres_reachable

    if not _postgres_reachable():
        pytest.skip(f"PostgreSQL not reachable at {POSTGRES_TEST_URL}")
    schema = f"mlw_expiry_{uuid.uuid4().hex[:8]}"
    admin = create_engine(POSTGRES_TEST_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f"CREATE SCHEMA {schema}"))
    eng = create_engine(POSTGRES_TEST_URL, connect_args={"options": f"-csearch_path={schema}"})
    with eng.begin() as c:
        c.execute(
            text("""
            CREATE TABLE ml_promotions (
                promotion_id TEXT PRIMARY KEY, promotion_type TEXT, name TEXT,
                finish_date TIMESTAMPTZ)
        """)
        )
        c.execute(
            text("""
            CREATE TABLE ml_item_promotions (
                mla TEXT, promotion_id TEXT, promotion_type TEXT, sub_type TEXT,
                status TEXT, original_price NUMERIC, price NUMERIC,
                min_discounted_price NUMERIC, max_discounted_price NUMERIC,
                suggested_discounted_price NUMERIC, payload JSONB DEFAULT '{}'::jsonb,
                updated_at TIMESTAMPTZ DEFAULT NOW(), PRIMARY KEY (mla, promotion_id))
        """)
        )
        c.execute(
            text(
                "INSERT INTO ml_promotions VALUES "
                "('P_EXP','DEAL','Camp EXP',:past),('P_FUT','DEAL','Camp FUT',:fut),"
                "('P_NULL','DEAL','Camp NULL',NULL)"
            ),
            {"past": PAST, "fut": FUTURE},
        )
        for mla, pid, status in _ITEM_ROWS:
            c.execute(
                text(
                    "INSERT INTO ml_item_promotions (mla, promotion_id, promotion_type, status, price) VALUES (:m,:p,'DEAL',:s,100)"
                ),
                {"m": mla, "p": pid, "s": status},
            )
    yield eng
    eng.dispose()
    with admin.connect() as c:
        c.execute(text(f"DROP SCHEMA {schema} CASCADE"))
    admin.dispose()


@pytest.fixture()
def svc(mlw_engine):
    with patch("app.services.ml_promotions_service.get_mlwebhook_engine", return_value=mlw_engine):
        import app.services.ml_promotions_service as s

        yield s


ALL = [r[0] for r in _ITEM_ROWS]


def test_with_started_excludes_expired(svc):
    assert svc.fetch_mlas_with_started() == {"S_FUT", "S_NOCAT", "S_NULL"}


def test_with_started_scoped_by_mla_ids(svc):
    assert svc.fetch_mlas_with_started(["S_EXP", "S_FUT"]) == {"S_FUT"}


def test_active_promo_type_available_excludes_expired(svc):
    got = svc.fetch_mlas_with_active_promo_type(["DEAL"])
    assert got == {"S_FUT", "S_NOCAT", "S_NULL", "C_FUT", "C_NOCAT", "MIX"}


def test_active_promo_type_applied_only_excludes_expired(svc):
    got = svc.fetch_mlas_with_active_promo_type(["DEAL"], applied_only=True)
    assert got == {"S_FUT", "S_NOCAT", "S_NULL"}


def test_candidate_only_expired_started_no_longer_disqualifies(svc):
    assert svc.fetch_mlas_with_candidate_only() == {"C_FUT", "C_NOCAT", "MIX"}


def test_candidate_only_for_types_excludes_expired(svc):
    assert svc.fetch_mlas_with_candidate_only_for_types(["DEAL"]) == {"C_FUT", "C_NOCAT", "MIX"}


def test_by_promo_name_excludes_expired(svc):
    assert svc.fetch_mlas_by_promo_name("Camp") == {"S_FUT", "S_NULL", "C_FUT", "MIX"}


def test_promo_summary_excludes_expired(svc):
    got = svc.fetch_promo_summary_by_mla(ALL)
    assert set(got) == {"S_FUT", "S_NOCAT", "S_NULL", "C_FUT", "C_NOCAT", "MIX"}
    assert got["MIX"]["active_count"] == 1
    assert got["MIX"]["has_applied"] is False
    assert got["S_FUT"]["has_applied"] is True


def test_node_summary_excludes_expired(svc):
    got = svc.fetch_promo_node_summary_by_mla(ALL)
    assert set(got) == {"S_FUT", "S_NOCAT", "S_NULL", "C_FUT", "C_NOCAT", "MIX"}
    assert got["MIX"]["started_count"] == 0
    assert got["MIX"]["candidate_count"] == 1
