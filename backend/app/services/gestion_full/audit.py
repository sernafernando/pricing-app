"""Gestión Full → global ``auditoria`` rows (same pattern as sell_out / ml_ads).

Writes stay in the caller's transaction: do not commit here.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.auditoria import Auditoria, TipoAccion


def registrar(
    db: Session,
    *,
    tipo: TipoAccion,
    usuario_id: int,
    item_id: Optional[int] = None,
    antes: Optional[dict[str, Any]] = None,
    despues: Optional[dict[str, Any]] = None,
    comentario: Optional[str] = None,
    masivo: bool = False,
    productos_afectados: Optional[int] = None,
) -> None:
    """Append one ``auditoria`` row; caller commits with the domain change."""
    db.add(
        Auditoria(
            item_id=item_id,
            usuario_id=usuario_id,
            tipo_accion=tipo,
            valores_anteriores=antes,
            valores_nuevos=despues,
            es_masivo=masivo,
            productos_afectados=productos_afectados,
            comentario=comentario,
            fecha=datetime.now(UTC).replace(tzinfo=None),  # naive UTC, column default style
        )
    )


def line_snapshot(line: Any) -> dict[str, Any]:
    """Denormalized package-line fields that survive a DELETE of the line row."""
    return {
        "line_id": int(line.id) if getattr(line, "id", None) is not None else None,
        "package_id": int(line.package_id),
        "producto_item_id": int(line.producto_item_id),
        "user_product_id": str(line.user_product_id),
        "inventory_id": str(line.inventory_id),
        "qty_pm": int(line.qty_pm),
        "qty_export": int(line.qty_export),
        "qty_export_reason": line.qty_export_reason,
        "inbound_id": None if line.inbound_id is None else str(line.inbound_id),
    }
