"""Extract-only Factura/s · Pedido/s refresh. Never rematch, Excel, or flip status."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import select

from app.core.config import settings
from app.core.database import get_background_db
from app.core.logging import get_logger
from app.models.compra_adjunto import CompraAdjunto
from app.models.oc_match_job import OcMatchJob
from app.models.pedido_compra import PedidoCompra
from app.services import pedidos_service
from app.services.oc_match.doc_refs import apply_writeback, normalize_tipo, token_or_none
from app.services.oc_match.extract import extract_one
from app.services.oc_match.gemini_pool import load_pool

logger = get_logger("services.oc_match.refresh_doc_refs")

_REFRESHABLE = frozenset({OcMatchJob.STATUS_DONE, OcMatchJob.STATUS_ERROR})


@dataclass(frozen=True)
class _LoadedAdjunto:
    data: bytes
    filename: str


def refresh_doc_refs_job(job_id: int) -> None:
    """Two-session extract-only persist. Never claim_queued_job or progress_phase."""
    loaded = _load_adjunto_if_refreshable(job_id)
    if loaded is None:
        return
    try:
        pool = load_pool()
        extracted = extract_one(pool, loaded.data, loaded.filename)
    except Exception as exc:  # noqa: BLE001 — failed extract leaves stamp/job/pedido
        logger.exception("oc-match refresh-doc-refs job_id=%s extract falló: %s", job_id, exc)
        return
    _persist_writeback(job_id, extracted)


def _load_adjunto_if_refreshable(job_id: int) -> Optional[_LoadedAdjunto]:
    with get_background_db() as db:
        job = db.get(OcMatchJob, job_id)
        if job is None or job.status not in _REFRESHABLE:
            return None
        adjunto = db.get(CompraAdjunto, job.attachment_id)
        if adjunto is None:
            logger.warning("oc-match refresh-doc-refs job_id=%s adjunto ausente", job_id)
            return None
        path = Path(settings.COMPRAS_UPLOADS_DIR) / (adjunto.path_archivo or "")
        filename = adjunto.nombre_archivo or "documento.pdf"
        if not path.is_file():
            logger.warning(
                "oc-match refresh-doc-refs job_id=%s archivo ausente path=%s",
                job_id,
                path,
            )
            return None
        return _LoadedAdjunto(data=path.read_bytes(), filename=filename)


def _persist_writeback(job_id: int, extracted: dict[str, Any]) -> None:
    with get_background_db() as db:
        job = db.execute(select(OcMatchJob).where(OcMatchJob.id == job_id).with_for_update()).scalars().one_or_none()
        if job is None or job.status not in _REFRESHABLE:
            logger.info("oc-match refresh-doc-refs persist skip job_id=%s (status left)", job_id)
            return
        job.doc_refs_aplicado_at = None
        pedido = (
            db.execute(select(PedidoCompra).where(PedidoCompra.id == job.pedido_id).with_for_update())
            .scalars()
            .one_or_none()
        )
        if pedido is None:
            logger.warning("oc-match refresh-doc-refs job_id=%s pedido ausente", job_id)
            return
        if apply_writeback(pedido, extracted):
            job.doc_refs_aplicado_at = datetime.now(UTC)
            nro_documento = token_or_none(extracted.get("nro_documento"))
            if normalize_tipo(extracted.get("tipo_documento")) == "factura" and nro_documento is not None:
                pedidos_service.persist_factura_documento(
                    db,
                    pedido=pedido,
                    numero=nro_documento,
                    created_by_id=int(pedido.creado_por_id),
                )
            db.flush()
