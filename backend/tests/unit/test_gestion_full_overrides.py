"""Unit tests for Gestión Full override auth helpers (no DB)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services.gestion_full.overrides import (
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
    assert puede_editar_con_pares(None, "TP-LINK", "Camaras") is True
    assert puede_editar_con_pares([], "TP-LINK", "Camaras") is False
    assert puede_editar_con_pares([("TP-LINK", "CAMARAS")], "tp-link", "camaras") is True
    assert puede_editar_con_pares([("TP-LINK", "CAMARAS")], "OTRA", "Camaras") is False
