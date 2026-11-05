"""Unit tests for Gestión Full → global auditoria helper."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.models.auditoria import TipoAccion
from app.services.gestion_full.audit import line_snapshot, registrar


def test_registrar_adds_auditoria_without_commit() -> None:
    db = MagicMock()
    registrar(
        db,
        tipo=TipoAccion.GESTION_FULL_LINES_REMOVE,
        usuario_id=9,
        despues={"package_id": 1, "removed": []},
        masivo=True,
        productos_afectados=2,
    )
    db.add.assert_called_once()
    row = db.add.call_args.args[0]
    assert row.usuario_id == 9
    assert row.tipo_accion == TipoAccion.GESTION_FULL_LINES_REMOVE
    assert row.es_masivo is True
    assert row.productos_afectados == 2
    db.commit.assert_not_called()


def test_line_snapshot_is_denormalized() -> None:
    line = SimpleNamespace(
        id=5,
        package_id=3,
        producto_item_id=99,
        user_product_id="MLAU",
        inventory_id="INV-X",
        qty_pm=4,
        qty_export=3,
        qty_export_reason="ajuste",
        inbound_id="INB",
    )
    assert line_snapshot(line) == {
        "line_id": 5,
        "package_id": 3,
        "producto_item_id": 99,
        "user_product_id": "MLAU",
        "inventory_id": "INV-X",
        "qty_pm": 4,
        "qty_export": 3,
        "qty_export_reason": "ajuste",
        "inbound_id": "INB",
    }
