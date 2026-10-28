"""PARA GANAR revision queue states (P4 persistence; P5 will call upsert)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.models.para_ganar_revision_mla import (
    REVISION_ESTADOS,
    ParaGanarRevisionMla,
)


def normalize_revision_estado(raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
    token = str(raw).strip().lower()
    if not token:
        return None
    if token not in REVISION_ESTADOS:
        raise ValueError(f"revision_estado inválido: {raw}")
    return token


def upsert_revision_estado(
    db: Session,
    *,
    mla: str,
    estado: str,
    updated_by_id: Optional[int] = None,
) -> ParaGanarRevisionMla:
    """Create or update the Advisor revision badge for one MLA."""
    mla_norm = (mla or "").strip().upper()
    if not mla_norm:
        raise ValueError("MLA inválido")
    estado_norm = normalize_revision_estado(estado)
    if not estado_norm:
        raise ValueError("revision_estado requerido")

    row = db.get(ParaGanarRevisionMla, mla_norm)
    now = datetime.now(UTC)
    if row is None:
        row = ParaGanarRevisionMla(
            mla=mla_norm,
            estado=estado_norm,
            evaluated_at=now,
            updated_at=now,
            updated_by_id=updated_by_id,
        )
        db.add(row)
    else:
        row.estado = estado_norm
        row.evaluated_at = now
        row.updated_at = now
        row.updated_by_id = updated_by_id
    db.flush()
    return row
