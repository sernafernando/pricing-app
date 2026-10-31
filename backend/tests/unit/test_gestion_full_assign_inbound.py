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


def test_human_envio_id() -> None:
    pkg = SimpleNamespace(week_monday=date(2026, 10, 26))
    assert human_envio_id(pkg, "81061502") == "20261026_81061502"


def test_clear_inbound_blocked_when_locked() -> None:
    db = MagicMock()
    pkg = SimpleNamespace(status="locked", lines=[])
    with pytest.raises(PermissionError):
        clear_inbound_ids(db, pkg)


def test_assign_then_hard_lock() -> None:
    db = MagicMock()
    ln1 = SimpleNamespace(id=1, inbound_id=None)
    ln2 = SimpleNamespace(id=2, inbound_id=None)
    pkg = SimpleNamespace(
        status="exported",
        exported_at=None,
        locked_at=None,
        lines=[ln1, ln2],
    )

    assign_inbound_to_lines(db, pkg, line_ids=[1], inbound_id="A")
    assert ln1.inbound_id == "A"
    assert pkg.status == "exported"  # not all assigned yet

    assign_inbound_to_lines(db, pkg, line_ids=[2], inbound_id="B")
    assert ln2.inbound_id == "B"
    assert pkg.status == "locked"


def test_maybe_hard_lock_noop_partial() -> None:
    db = MagicMock()
    pkg = SimpleNamespace(
        status="exported",
        lines=[
            SimpleNamespace(inbound_id="1"),
            SimpleNamespace(inbound_id=None),
        ],
    )
    assert maybe_hard_lock(db, pkg) is None
    assert pkg.status == "exported"
