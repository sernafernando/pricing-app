"""Unit tests for Gestión Full units-per-box service (no DB)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.services.gestion_full.unidades_caja import (
    clear_unidades_caja,
    import_unidades_caja_por_ean,
    list_pendientes_unidades_caja,
    upsert_unidades_caja,
)


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


def test_import_unidades_caja_por_ean_skips_unknown() -> None:
    db = MagicMock()
    db.execute.return_value.scalar_one_or_none.return_value = None
    usuario = SimpleNamespace(id=1)

    out = import_unidades_caja_por_ean(
        db,
        rows=[{"ean": "NOPE", "unidades": 2}],
        usuario=usuario,
    )
    assert out["updated"] == 0
    assert len(out["errors"]) == 1
    db.commit.assert_not_called()


def test_list_pendientes_unidades_caja_empty_when_no_candidates() -> None:
    db = MagicMock()
    with patch(
        "app.services.gestion_full.unidades_caja.get_active_package",
        return_value=None,
    ):
        db.query.return_value.distinct.return_value.all.return_value = []
        assert list_pendientes_unidades_caja(db) == []


def test_list_pendientes_unidades_caja_package_first_excludes_with_caja() -> None:
    db = MagicMock()
    pkg = SimpleNamespace(id=9)
    product_pkg = SimpleNamespace(item_id=1, codigo="AAA", descripcion="En paquete")
    product_ready = SimpleNamespace(item_id=2, codigo="BBB", descripcion="Solo ready")

    package_q = MagicMock()
    package_q.filter.return_value.distinct.return_value.all.return_value = [(1,)]
    ready_q = MagicMock()
    ready_q.distinct.return_value.all.return_value = [(2,), (1,)]
    caja_q = MagicMock()
    caja_q.filter.return_value.all.return_value = []
    product_q = MagicMock()
    product_q.filter.return_value.all.return_value = [product_ready, product_pkg]

    queries = [package_q, ready_q, caja_q, product_q]

    def query_router(*_args: object, **_kwargs: object) -> MagicMock:
        if not queries:
            raise AssertionError("unexpected extra db.query")
        return queries.pop(0)

    db.query.side_effect = query_router

    with patch(
        "app.services.gestion_full.unidades_caja.get_active_package",
        return_value=pkg,
    ):
        items = list_pendientes_unidades_caja(db)

    assert [i["producto_item_id"] for i in items] == [1, 2]
    assert items[0]["en_paquete"] is True and items[0]["pm_ready"] is True
    assert items[1]["en_paquete"] is False and items[1]["pm_ready"] is True
