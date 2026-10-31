"""Unit tests for Gestión Full units-per-box service (no DB)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services.gestion_full.unidades_caja import clear_unidades_caja, upsert_unidades_caja


def test_upsert_unidades_caja_rejects_below_one() -> None:
    db = MagicMock()
    usuario = SimpleNamespace(id=1)
    with pytest.raises(ValueError, match="unidades"):
        upsert_unidades_caja(db, producto_item_id=10, unidades=0, usuario=usuario)
    db.commit.assert_not_called()


def test_upsert_unidades_caja_creates_when_missing() -> None:
    db = MagicMock()
    db.get.return_value = None
    usuario = SimpleNamespace(id=7)

    row = upsert_unidades_caja(db, producto_item_id=42, unidades=12, usuario=usuario)

    db.add.assert_called_once()
    db.commit.assert_called_once()
    assert row.producto_item_id == 42
    assert row.unidades == 12
    assert row.updated_by_id == 7


def test_clear_unidades_caja_noop_when_missing() -> None:
    db = MagicMock()
    db.get.return_value = None
    clear_unidades_caja(db, producto_item_id=1)
    db.delete.assert_not_called()
    db.commit.assert_not_called()
