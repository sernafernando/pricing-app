"""`PxqSyncResult.audit_warning` (D6, slice C): the router must not silently
drop the audit-isolation warning `ml_pxq_write_service.sync_pxq_tiers` can
attach to an otherwise-successful outcome.

`publicar_sin_markup` is deliberately OUT OF SCOPE here -- it is exposed on
`PxqSyncRequest` in the next slice (C2). This file only proves the RESPONSE
side of D6: `synced: true` plus a warning both reach the caller, not
`synced: true` alone with the warning silently dropped by
`PxqSyncResult(**outcome)` ignoring an unmodeled key.
"""

from __future__ import annotations

import pytest

from app.core.security import get_password_hash
from app.models.usuario import AuthProvider, RolUsuario, Usuario
from app.routers import pxq as pxq_router
from app.routers.pxq import PxqSyncRequest


@pytest.fixture()
def pxq_user(db, rol_ventas) -> Usuario:
    user = Usuario(
        username="pxq_audit_warning_router_user",
        email="pxq_audit_warning_router_user@example.com",
        nombre="PxQ Audit Warning Router User",
        password_hash=get_password_hash("TestPass123!"),
        rol=RolUsuario.VENTAS,
        rol_id=rol_ventas.id,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(user)
    db.flush()
    return user


def _sync(db, usuario, item_id: str):
    return pxq_router.sincronizar_pxq(item_id=item_id, body=PxqSyncRequest(), current_user=usuario, db=db)


class TestAuditWarningReachesTheResponse:
    def test_audit_warning_present_in_the_response_when_the_service_reports_one(
        self, db, pxq_user, monkeypatch
    ) -> None:
        monkeypatch.setattr(
            pxq_router,
            "sync_pxq_tiers",
            lambda *args, **kwargs: {
                "synced": True,
                "status": "sincronizado",
                "array": [],
                "audit_warning": "Precios actualizados en MercadoLibre, pero no se pudo registrar la auditoría.",
            },
        )

        result = _sync(db, pxq_user, "MLA000001")

        assert result.synced is True
        assert result.audit_warning == "Precios actualizados en MercadoLibre, pero no se pudo registrar la auditoría."

    def test_audit_warning_is_absent_when_the_service_does_not_report_one(self, db, pxq_user, monkeypatch) -> None:
        monkeypatch.setattr(
            pxq_router,
            "sync_pxq_tiers",
            lambda *args, **kwargs: {"synced": True, "status": "sincronizado", "array": []},
        )

        result = _sync(db, pxq_user, "MLA000001")

        assert result.synced is True
        assert result.audit_warning is None
