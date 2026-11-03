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


def test_consume_pm_ready_and_orphan_close_are_batched() -> None:
    """Fernando N+1: hard-lock delete and orphan close must not per-row get/count."""
    import inspect

    from app.services.gestion_full import assign_inbound as mod

    consume = inspect.getsource(mod._consume_pm_ready_for_package)
    assert ".delete(" in consume
    assert "db.get(" not in consume
    close = inspect.getsource(mod._close_orphan_envios)
    assert "group_by" in close
    assert "func.count()" in close
    assert ").count()" not in close


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

    try:
        import app.services.gestion_full.reconcile  # noqa: F401
    except ImportError:
        # Stack 14 CI: reconcile/envío land in #1981 — assign still hard-locks alone.
        assign_inbound_to_lines(db, pkg, line_ids=[1], inbound_id="A")
        assert ln1.inbound_id == "A"
        assign_inbound_to_lines(db, pkg, line_ids=[2], inbound_id="B")
        assert ln2.inbound_id == "B"
        assert pkg.status == "locked"
        return

    with patch("app.services.gestion_full.reconcile.ensure_envio") as ensure:
        assign_inbound_to_lines(db, pkg, line_ids=[1], inbound_id="A")
        assert ln1.inbound_id == "A"
        assert pkg.status == "exported"  # not all assigned yet
        ensure.assert_called()
        # Same transaction as assign: ensure_envio must flush, not commit alone.
        assert ensure.call_args.kwargs.get("commit") is False
        assert db.commit.call_count >= 1

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
    package_q = MagicMock()
    package_q.filter.return_value.populate_existing.return_value.with_for_update.return_value.one.return_value = pkg
    pm_q = MagicMock()
    pm_q.filter.return_value.delete.return_value = 1

    def _query(*args: object) -> MagicMock:
        model = args[0] if args else None
        name = getattr(model, "__name__", "")
        if name == "GestionFullPmReady":
            return pm_q
        return package_q

    db.query.side_effect = _query

    maybe_hard_lock(db, pkg)
    pm_q.filter.return_value.delete.assert_called_once_with(synchronize_session=False)
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


def _db_clear_inbound(pkg: object, *, envios: list[object]) -> MagicMock:
    """Session mock for clear_inbound_ids after batched orphan-close."""
    db = MagicMock()
    package_q = MagicMock()
    package_q.filter.return_value.populate_existing.return_value.with_for_update.return_value.one.return_value = pkg
    line_q = MagicMock()
    line_q.filter.return_value.group_by.return_value.all.return_value = []
    envio_q = MagicMock()
    envio_q.filter.return_value.all.return_value = envios

    def _query(*args: object) -> MagicMock:
        first = args[0] if args else None
        name = getattr(first, "__name__", None)
        if name == "GestionFullEnvio":
            return envio_q
        if name == "GestionFullPackage":
            return package_q
        cls_name = getattr(getattr(first, "class_", None), "__name__", None)
        if name == "GestionFullPackageLine" or cls_name == "GestionFullPackageLine":
            return line_q
        return package_q

    db.query.side_effect = _query
    return db


def test_clear_inbound_closes_orphan_envio() -> None:
    pytest.importorskip("app.models.gestion_full_envio")
    from datetime import UTC, datetime

    ln = SimpleNamespace(id=1, inbound_id="ORPHAN-1", qty_export=2)
    pkg = SimpleNamespace(id=1, status="exported", exported_at=datetime(2026, 10, 27, tzinfo=UTC), lines=[ln])
    envio = SimpleNamespace(
        inbound_id="ORPHAN-1",
        reception_closed_at=None,
        last_reception_at=None,
    )
    db = _db_clear_inbound(pkg, envios=[envio])

    n = clear_inbound_ids(db, pkg)
    assert n == 1
    assert ln.inbound_id is None
    assert envio.reception_closed_at is not None
    db.flush.assert_called()
    db.commit.assert_called_once()


def test_clear_inbound_keeps_envio_that_already_received() -> None:
    pytest.importorskip("app.models.gestion_full_envio")
    from datetime import UTC, datetime

    ln = SimpleNamespace(id=1, inbound_id="GOT-STOCK", qty_export=2)
    pkg = SimpleNamespace(id=1, status="exported", exported_at=datetime(2026, 10, 27, tzinfo=UTC), lines=[ln])
    envio = SimpleNamespace(
        inbound_id="GOT-STOCK",
        reception_closed_at=None,
        last_reception_at=datetime(2026, 10, 28, tzinfo=UTC),
    )
    db = _db_clear_inbound(pkg, envios=[envio])

    clear_inbound_ids(db, pkg)
    assert envio.reception_closed_at is None
