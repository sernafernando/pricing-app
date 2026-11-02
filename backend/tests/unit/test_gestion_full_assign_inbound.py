"""Unit tests for inbound assign / hard-lock helpers."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services.gestion_full.assign_inbound import (
    assign_inbound_to_lines,
    clear_inbound_ids,
    human_envio_id,
    maybe_hard_lock,
)


def _db_returning(pkg: object) -> MagicMock:
    db = MagicMock()
    db.query.return_value.filter.return_value.populate_existing.return_value.with_for_update.return_value.one.return_value = pkg
    db.get.return_value = None
    # clear_inbound orphan check: no remaining line refs
    db.query.return_value.filter.return_value.count.return_value = 0
    return db


def test_human_envio_id() -> None:
    pkg = SimpleNamespace(week_monday=date(2026, 10, 26))
    assert human_envio_id(pkg, "81061502") == "20261026_81061502"


def test_clear_inbound_blocked_when_locked() -> None:
    pkg = SimpleNamespace(id=1, status="locked", lines=[])
    db = _db_returning(pkg)
    with pytest.raises(PermissionError):
        clear_inbound_ids(db, pkg)


def test_assign_rejects_open_package() -> None:
    ln1 = SimpleNamespace(id=1, inbound_id=None, qty_export=2)
    pkg = SimpleNamespace(id=1, status="open", lines=[ln1])
    db = _db_returning(pkg)
    with pytest.raises(ValueError, match="exported"):
        assign_inbound_to_lines(db, pkg, line_ids=[1], inbound_id="A")


def test_assign_then_hard_lock() -> None:
    from unittest.mock import patch

    ln1 = SimpleNamespace(
        id=1,
        inbound_id=None,
        qty_export=2,
        producto_item_id=10,
        user_product_id="U1",
    )
    ln2 = SimpleNamespace(
        id=2,
        inbound_id=None,
        qty_export=3,
        producto_item_id=20,
        user_product_id="U2",
    )
    pkg = SimpleNamespace(
        id=1,
        status="exported",
        exported_at=None,
        locked_at=None,
        week_monday=date(2026, 10, 26),
        lines=[ln1, ln2],
    )
    db = _db_returning(pkg)

    with patch("app.services.gestion_full.reconcile.ensure_envio") as ensure:
        assign_inbound_to_lines(db, pkg, line_ids=[1], inbound_id="A")
        assert ln1.inbound_id == "A"
        assert pkg.status == "exported"  # not all assigned yet
        ensure.assert_called()

        assign_inbound_to_lines(db, pkg, line_ids=[2], inbound_id="B")
        assert ln2.inbound_id == "B"
        assert pkg.status == "locked"


def test_maybe_hard_lock_ignores_zero_qty_lines() -> None:
    db = MagicMock()
    pkg = SimpleNamespace(
        id=1,
        status="exported",
        exported_at=None,
        locked_at=None,
        lines=[
            SimpleNamespace(
                inbound_id="1",
                qty_export=5,
                producto_item_id=1,
                user_product_id="A",
            ),
            SimpleNamespace(
                inbound_id=None,
                qty_export=0,
                producto_item_id=2,
                user_product_id="B",
            ),
        ],
    )
    db.query.return_value.filter.return_value.populate_existing.return_value.with_for_update.return_value.one.return_value = pkg
    db.get.return_value = None

    out = maybe_hard_lock(db, pkg)
    assert out is pkg
    assert pkg.status == "locked"
    db.commit.assert_called_once()


def test_maybe_hard_lock_consumes_pm_ready() -> None:
    ready = MagicMock()
    ln = SimpleNamespace(
        inbound_id="X",
        qty_export=1,
        producto_item_id=7,
        user_product_id="MLAU",
    )
    pkg = SimpleNamespace(
        id=1,
        status="exported",
        exported_at=None,
        locked_at=None,
        lines=[ln],
    )
    db = MagicMock()
    db.query.return_value.filter.return_value.populate_existing.return_value.with_for_update.return_value.one.return_value = pkg
    db.get.return_value = ready

    maybe_hard_lock(db, pkg)
    db.delete.assert_called_once_with(ready)
    assert pkg.status == "locked"


def test_maybe_hard_lock_noop_partial() -> None:
    db = MagicMock()
    pkg = SimpleNamespace(
        id=1,
        status="exported",
        lines=[
            SimpleNamespace(inbound_id="1", qty_export=2),
            SimpleNamespace(inbound_id=None, qty_export=3),
        ],
    )
    db.query.return_value.filter.return_value.populate_existing.return_value.with_for_update.return_value.one.return_value = pkg
    assert maybe_hard_lock(db, pkg) is None
    assert pkg.status == "exported"


def test_clear_inbound_closes_orphan_envio() -> None:
    from datetime import UTC, datetime

    ln = SimpleNamespace(id=1, inbound_id="ORPHAN-1", qty_export=2)
    pkg = SimpleNamespace(id=1, status="exported", exported_at=datetime(2026, 10, 27, tzinfo=UTC), lines=[ln])
    envio = SimpleNamespace(inbound_id="ORPHAN-1", reception_closed_at=None)
    db = _db_returning(pkg)
    db.get.return_value = envio

    n = clear_inbound_ids(db, pkg)
    assert n == 1
    assert ln.inbound_id is None
    assert envio.reception_closed_at is not None
    db.flush.assert_called()
    db.commit.assert_called_once()
