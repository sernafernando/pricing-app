"""Unit tests for Gestión Full Excel helpers (no DB / no template IO)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services.gestion_full.excel_export import (
    _mla_digits,
    assert_package_exportable,
)


def test_mla_digits_strips_prefix() -> None:
    assert _mla_digits("MLA1173239744") == "1173239744"
    assert _mla_digits("1173239744") == "1173239744"
    assert _mla_digits("MLAU123") is None
    assert _mla_digits(None) is None


def test_assert_package_exportable_locked() -> None:
    db = MagicMock()
    pkg = SimpleNamespace(status="locked", lines=[])
    with pytest.raises(ValueError, match="hard-locked"):
        assert_package_exportable(db, pkg)


def test_assert_package_exportable_inbound_blocks_regen() -> None:
    db = MagicMock()
    pkg = SimpleNamespace(
        status="exported",
        lines=[SimpleNamespace(inbound_id="99", qty_export=1, producto_item_id=1)],
    )
    with pytest.raises(ValueError, match="inbound_id"):
        assert_package_exportable(db, pkg)


def test_assert_package_exportable_requires_caja() -> None:
    db = MagicMock()
    db.get.return_value = None
    pkg = SimpleNamespace(
        status="open",
        lines=[SimpleNamespace(inbound_id=None, qty_export=2, producto_item_id=7)],
    )
    with pytest.raises(ValueError, match="unidades/caja"):
        assert_package_exportable(db, pkg)
