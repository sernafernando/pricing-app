"""Gestor-only bulk wipe of Planificación overrides + Qty PM (pm_ready)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.auditoria import TipoAccion
from app.models.gestion_full_override import GestionFullOverride
from app.models.gestion_full_pm_ready import GestionFullPmReady
from app.models.usuario import Usuario
from app.services.gestion_full.audit import registrar


def reset_planificacion(db: Session, *, usuario: Usuario) -> dict[str, Any]:
    """Delete every override and every pm_ready row. Returns counts deleted.

    Does not touch package lines, envíos, or U/caja. One audit row (masivo).
    """
    overrides_deleted = db.query(GestionFullOverride).delete(synchronize_session=False)
    ready_deleted = db.query(GestionFullPmReady).delete(synchronize_session=False)
    total = int(overrides_deleted) + int(ready_deleted)
    registrar(
        db,
        tipo=TipoAccion.GESTION_FULL_PLAN_RESET,
        usuario_id=int(usuario.id),
        despues={
            "overrides_deleted": int(overrides_deleted),
            "pm_ready_deleted": int(ready_deleted),
        },
        masivo=True,
        productos_afectados=total,
        comentario="Reset Planificación: overrides + Qty PM",
    )
    db.commit()
    return {
        "overrides_deleted": int(overrides_deleted),
        "pm_ready_deleted": int(ready_deleted),
    }
