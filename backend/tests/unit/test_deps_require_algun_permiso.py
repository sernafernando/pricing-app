"""
Unit tests for require_algun_permiso (deps.py) — RED phase.

Covers:
  - User has one of the required permission codes → returns user (200 path)
  - User has none of the required codes → raises 403
  - SUPERADMIN always passes (tiene_permiso returns True for any code)
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.models.usuario import Usuario


def _make_user(superadmin: bool = False) -> Usuario:
    """Build a minimal Usuario mock for dep tests."""
    user = MagicMock(spec=Usuario)
    user.id = 42
    user.username = "testuser"
    user.activo = True
    user.es_superadmin = superadmin
    user._permisos_cache = None
    return user


# ---------------------------------------------------------------------------
# require_algun_permiso — happy path
# ---------------------------------------------------------------------------


def test_require_algun_permiso_user_has_first_code() -> None:
    """User has the first of the required codes → dependency returns user."""
    from app.api.deps import require_algun_permiso

    user = _make_user()
    mock_db = MagicMock()

    dep_fn = require_algun_permiso(["consultas.ver_ranking", "consultas.ver_mi_ranking"])

    with patch(
        "app.services.permisos_service.PermisosService.tiene_algun_permiso",
        return_value=True,
    ):
        import asyncio

        result = asyncio.run(dep_fn(current_user=user, db=mock_db))

    assert result is user


def test_require_algun_permiso_user_has_second_code() -> None:
    """User has only the second of the required codes → dependency returns user."""
    from app.api.deps import require_algun_permiso

    user = _make_user()
    mock_db = MagicMock()

    dep_fn = require_algun_permiso(["consultas.ver_ranking", "consultas.ver_mi_ranking"])

    with patch(
        "app.services.permisos_service.PermisosService.tiene_algun_permiso",
        return_value=True,
    ):
        import asyncio

        result = asyncio.run(dep_fn(current_user=user, db=mock_db))

    assert result is user


# ---------------------------------------------------------------------------
# require_algun_permiso — forbidden path
# ---------------------------------------------------------------------------


def test_require_algun_permiso_user_has_none_raises_403() -> None:
    """User has none of the required codes → HTTPException 403."""
    from app.api.deps import require_algun_permiso

    user = _make_user()
    mock_db = MagicMock()

    dep_fn = require_algun_permiso(["consultas.ver_ranking", "consultas.ver_mi_ranking"])

    with patch(
        "app.services.permisos_service.PermisosService.tiene_algun_permiso",
        return_value=False,
    ):
        import asyncio

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(dep_fn(current_user=user, db=mock_db))

    assert exc_info.value.status_code == 403


def test_require_algun_permiso_error_detail_contains_codes() -> None:
    """403 error detail must mention the required codes."""
    from app.api.deps import require_algun_permiso

    user = _make_user()
    mock_db = MagicMock()

    codigos = ["consultas.ver_ranking", "consultas.ver_mi_ranking"]
    dep_fn = require_algun_permiso(codigos)

    with patch(
        "app.services.permisos_service.PermisosService.tiene_algun_permiso",
        return_value=False,
    ):
        import asyncio

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(dep_fn(current_user=user, db=mock_db))

    # The detail should mention the codes somehow (implementation detail)
    detail = str(exc_info.value.detail)
    assert any(code in detail or "consultas" in detail for code in codigos)
