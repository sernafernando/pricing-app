"""
Unit tests para `require_permiso(codigo)` en `app.api.deps`.

No levantan app real — mockean `PermisosService.tiene_permiso` y
simulan la inyección de dependencias de FastAPI llamando directo al
`_check` async interno. Cubren:
  - Usuario con permiso → retorna el usuario intacto.
  - Usuario sin permiso → HTTPException 403 con code INSUFFICIENT_PERMISSIONS.
  - El mensaje incluye el código del permiso (debug friendly).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.deps import require_permiso
from app.core.exceptions import ErrorCode


def _fake_user() -> MagicMock:
    """Construye un Usuario mock sin tocar la DB."""
    user = MagicMock()
    user.id = 42
    user.username = "tester"
    user.es_superadmin = False
    return user


class TestRequirePermiso:
    """Tests del factory `require_permiso(codigo)`."""

    def test_retorna_callable_async(self) -> None:
        dep = require_permiso("compras.leer")
        assert callable(dep)

    @pytest.mark.asyncio
    async def test_usuario_con_permiso_retorna_usuario(self) -> None:
        user = _fake_user()
        db_mock = MagicMock()

        with patch("app.services.permisos_service.PermisosService") as svc_cls:
            svc_cls.return_value.tiene_permiso.return_value = True
            dep = require_permiso("administracion.gestionar_ordenes_compra")
            result = await dep(current_user=user, db=db_mock)

        assert result is user
        svc_cls.return_value.tiene_permiso.assert_called_once_with(user, "administracion.gestionar_ordenes_compra")

    @pytest.mark.asyncio
    async def test_usuario_sin_permiso_raises_http_403(self) -> None:
        user = _fake_user()
        db_mock = MagicMock()

        with patch("app.services.permisos_service.PermisosService") as svc_cls:
            svc_cls.return_value.tiene_permiso.return_value = False
            dep = require_permiso("administracion.aprobar_ordenes_compra")

            with pytest.raises(HTTPException) as exc_info:
                await dep(current_user=user, db=db_mock)

        assert exc_info.value.status_code == 403
        detail = exc_info.value.detail
        # El handler global normaliza a {error: {code, message}}, pero HTTPException
        # propaga `detail` como dict {code, message} antes del handler.
        assert isinstance(detail, dict)
        assert detail["code"] == ErrorCode.INSUFFICIENT_PERMISSIONS
        assert "administracion.aprobar_ordenes_compra" in detail["message"]

    @pytest.mark.asyncio
    async def test_codigos_distintos_llaman_con_codigo_correspondiente(self) -> None:
        """Dos dependencies con códigos distintos no comparten estado."""
        user = _fake_user()
        db_mock = MagicMock()

        with patch("app.services.permisos_service.PermisosService") as svc_cls:
            svc_cls.return_value.tiene_permiso.return_value = True

            dep_a = require_permiso("compras.leer")
            dep_b = require_permiso("compras.escribir")

            await dep_a(current_user=user, db=db_mock)
            await dep_b(current_user=user, db=db_mock)

        llamadas = svc_cls.return_value.tiene_permiso.call_args_list
        codigos = [c.args[1] for c in llamadas]
        assert "compras.leer" in codigos
        assert "compras.escribir" in codigos
