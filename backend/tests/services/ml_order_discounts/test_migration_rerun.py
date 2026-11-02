"""The discounts migrations through the repo's real `alembic/env.py`, in one `upgrade head` with a pending parent
and a pending child (stub revisions), against a scratch database: a failed index build or a failed later migration
must leave a state that a plain rerun finishes, with a valid index."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url

from app.core.config import settings

pytestmark = pytest.mark.postgres

BACKEND = Path(__file__).resolve().parents[3]
VERSIONS = BACKEND / "alembic" / "versions"
REAL = [VERSIONS / "20261228_ml_order_discounts.py", VERSIONS / "20261228_ml_pay_ops_coupon_idx.py"]
HEAD = "20261228_ml_pay_ops_coupon_idx"
BASE = """
revision = "probe_base"
down_revision = None
branch_labels = depends_on = None
def upgrade():
    pass
def downgrade():
    pass
"""
PARENT = """
from alembic import op
revision = "20261227_sell_in_modos_producto"
down_revision = "probe_base"
branch_labels = depends_on = None
def upgrade():
    op.execute("CREATE TABLE probe_parent (id int)")
def downgrade():
    op.execute("DROP TABLE probe_parent")
"""
CHILD = """
from alembic import op
revision = "probe_child"
down_revision = "20261228_ml_pay_ops_coupon_idx"
branch_labels = depends_on = None
def upgrade():
    op.execute("CREATE TABLE probe_child (id int)")
    if BOOM:
        op.execute("SELECT 1/0")
def downgrade():
    op.execute("DROP TABLE probe_child")
"""


@pytest.fixture()
def scratch(tmp_path, monkeypatch):
    if not os.environ.get("POSTGRES_TEST_URL"):
        pytest.skip("POSTGRES_TEST_URL is not set")
    base_url = make_url(os.environ["POSTGRES_TEST_URL"])
    name = f"discounts_mig_{uuid4().hex[:8]}"
    admin = sa.create_engine(base_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(sa.text(f"CREATE DATABASE {name}"))
    url = base_url.set(database=name)
    monkeypatch.setattr(settings, "DATABASE_URL_DIRECT", url.render_as_string(hide_password=False), raising=False)
    engine = sa.create_engine(url, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        conn.execute(
            sa.text(
                "CREATE TABLE ml_payments_ops (payment_id bigint primary key, order_id bigint, coupon_amount numeric)"
            )
        )
        conn.execute(sa.text("INSERT INTO ml_payments_ops SELECT g, g, g % 2 FROM generate_series(1, 2000) g"))
    versions = tmp_path / "versions"
    versions.mkdir()
    (versions / "base.py").write_text(BASE)
    (versions / "parent.py").write_text(PARENT)
    for path in REAL:
        shutil.copy(path, versions / path.name)
    cfg = Config()
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    cfg.set_main_option("version_locations", str(versions))
    command.stamp(cfg, "probe_base")
    yield cfg, engine, versions
    engine.dispose()
    with admin.connect() as conn:
        conn.execute(sa.text(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)"))
    admin.dispose()


def child(versions, boom=False):
    (versions / "child.py").write_text(CHILD.replace("BOOM", str(boom)))


def version(engine):
    with engine.connect() as conn:
        return conn.execute(sa.text("SELECT version_num FROM alembic_version")).scalars().all()


def index_valid(engine):
    with engine.connect() as conn:
        return conn.execute(
            sa.text(
                "SELECT i.indisvalid FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
                "WHERE c.relname = 'ix_ml_payments_ops_coupon_order_id'"
            )
        ).scalar()


def tables(engine):
    return set(sa.inspect(engine).get_table_names())


def test_one_upgrade_head_with_pending_neighbours_builds_a_valid_index(scratch):
    cfg, engine, versions = scratch
    child(versions)
    command.upgrade(cfg, "head")
    assert version(engine) == ["probe_child"]
    assert index_valid(engine) is True
    assert {"probe_parent", "probe_child", "ml_order_discounts", "ml_order_discounts_state"} <= tables(engine)


def test_a_build_stopped_by_a_writer_is_finished_by_a_plain_rerun(scratch):
    cfg, engine, versions = scratch
    # An open write transaction keeps CONCURRENTLY waiting until the migration's lock_timeout stops it, as a
    # Ctrl-C or a killed deploy would: the tables are committed and the index is left INVALID.
    blocker = engine.connect().execution_options(isolation_level="READ COMMITTED")
    tx = blocker.begin()
    blocker.execute(sa.text("UPDATE ml_payments_ops SET coupon_amount = coupon_amount WHERE payment_id = 1"))
    try:
        with pytest.raises(sa.exc.OperationalError):
            command.upgrade(cfg, "head")
    finally:
        tx.rollback()
        blocker.close()
    assert version(engine) == ["20261228_ml_order_discounts"]
    assert index_valid(engine) is False

    command.upgrade(cfg, "head")
    assert version(engine) == [HEAD]
    assert index_valid(engine) is True


def test_a_later_migration_failing_in_the_same_upgrade_is_finished_by_a_plain_rerun(scratch):
    cfg, engine, versions = scratch
    child(versions, boom=True)
    with pytest.raises(sa.exc.DataError):
        command.upgrade(cfg, "head")
    child(versions, boom=False)
    command.upgrade(cfg, "head")
    assert version(engine) == ["probe_child"]
    assert index_valid(engine) is True
