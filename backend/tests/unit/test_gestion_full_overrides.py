"""Unit tests for Gestión Full override auth helpers (no DB)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.models.gestion_full_override import GestionFullOverride
from app.services.gestion_full.overrides import (
    clear_override,
    puede_editar_con_pares,
    puede_editar_override_para,
    usuario_puede_editar_algun_override,
)


def test_puede_editar_full_view() -> None:
    usuario = MagicMock()
    db = MagicMock()
    with patch(
        "app.services.gestion_full.overrides.get_pares_marca_categoria_usuario",
        return_value=None,
    ):
        assert puede_editar_override_para(usuario, db, "TP-LINK", "Camaras") is True
        assert usuario_puede_editar_algun_override(usuario, db) is True


def test_puede_editar_pm_in_scope() -> None:
    usuario = MagicMock()
    db = MagicMock()
    with patch(
        "app.services.gestion_full.overrides.get_pares_marca_categoria_usuario",
        return_value=[("TP-LINK", "CAMARAS")],
    ):
        assert puede_editar_override_para(usuario, db, "tp-link", "camaras") is True
        assert puede_editar_override_para(usuario, db, "OTRA", "Camaras") is False
        assert usuario_puede_editar_algun_override(usuario, db) is True


def test_puede_editar_empty_scope() -> None:
    usuario = MagicMock()
    db = MagicMock()
    with patch(
        "app.services.gestion_full.overrides.get_pares_marca_categoria_usuario",
        return_value=[],
    ):
        assert puede_editar_override_para(usuario, db, "TP-LINK", "Camaras") is False
        assert usuario_puede_editar_algun_override(usuario, db) is False


def test_puede_editar_con_pares_reuses_preloaded_scope() -> None:
    """Listing must not re-query pares per row (N+1 on GET /gestion-full)."""
    pares = [("TP-LINK", "CAMARAS")]
    assert puede_editar_con_pares(pares, "tp-link", "camaras") is True
    assert puede_editar_con_pares(pares, "OTRA", "Camaras") is False
    assert puede_editar_con_pares(None, "X", "Y") is True
    assert puede_editar_con_pares([], "X", "Y") is False


def test_clear_override_drops_legacy_noinv_when_real_missing() -> None:
    """Clear by live Código ML still removes NOINV twin even if real key absent."""
    db = MagicMock()
    usuario = MagicMock(id=7)
    twin = GestionFullOverride(
        inventory_id="NOINV:MLAU1",
        cantidad=4,
        updated_by_id=None,
    )
    mlau_row = MagicMock()
    mlau_row.user_product_id = "MLAU1"

    def _get(_model: object, key: str) -> GestionFullOverride | None:
        if key == "INV-REAL":
            return None
        if key == "NOINV:MLAU1":
            return twin
        return None

    db.get.side_effect = _get
    db.execute.return_value.mappings.return_value.first.return_value = mlau_row

    with patch("app.services.gestion_full.overrides.registrar") as registrar:
        assert clear_override(db, inventory_id="INV-REAL", usuario=usuario) is True
        db.delete.assert_called_once_with(twin)
        db.commit.assert_called_once()
        assert registrar.call_count == 1
        assert registrar.call_args.kwargs["antes"] == {
            "inventory_id": "NOINV:MLAU1",
            "cantidad": 4,
        }
