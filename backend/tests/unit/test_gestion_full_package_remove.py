"""Unit tests for removing package lines by selection."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.services.gestion_full.package import remove_package_lines


def test_remove_package_lines_deletes_selection_and_closes_orphans() -> None:
    db = MagicMock()
    line_keep = SimpleNamespace(id=1, inbound_id=None)
    line_drop = SimpleNamespace(id=2, inbound_id="INB-1")
    pkg = SimpleNamespace(id=9, status="open", lines=[line_keep, line_drop])

    with (
        patch("app.services.gestion_full.package._package_for_update", return_value=pkg),
        patch("app.services.gestion_full.assign_inbound._close_orphan_envios") as close_orphans,
        patch("app.services.gestion_full.assign_inbound.maybe_hard_lock") as hard_lock,
    ):
        n = remove_package_lines(db, pkg, line_ids=[2])

    assert n == 1
    db.delete.assert_called_once_with(line_drop)
    close_orphans.assert_called_once()
    assert close_orphans.call_args.args[1] == {"INB-1"}
    hard_lock.assert_called_once()
    db.commit.assert_called_once()


def test_remove_package_lines_refuses_locked() -> None:
    db = MagicMock()
    pkg = SimpleNamespace(id=9, status="locked", lines=[])
    with patch("app.services.gestion_full.package._package_for_update", return_value=pkg):
        with pytest.raises(PermissionError, match="hard-locked"):
            remove_package_lines(db, pkg, line_ids=[1])
