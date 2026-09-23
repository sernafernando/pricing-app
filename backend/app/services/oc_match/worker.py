"""Two-session OC-match worker: claim; Gemini/excel with no Session; persist."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.compras_empresa_oc_map import sucursal_oc_para_empresa
from app.core.config import settings
from app.core.database import get_background_db
from app.core.logging import get_logger
from app.models.compra_adjunto import CompraAdjunto
from app.models.oc_match_job import OcMatchJob, OcMatchRenglon
from app.models.pedido_compra import PedidoCompra
from app.services import pedidos_service
from app.services.oc_match.acta import acta_cierre, nombre_excel
from app.services.oc_match.doc_refs import apply_writeback, normalize_tipo, token_or_none
from app.services.oc_match.enqueue import claim_queued_job
from app.services.oc_match.excel import RechazoExcel, generar
from app.services.oc_match.extract import extract_one
from app.services.oc_match.gemini_pool import MissingGeminiKeysError, load_pool
from app.services.oc_match.maestro import Articulo, cargar_maestro, sin_combos_internos
from app.services.oc_match.match import match_renglones

logger = get_logger("services.oc_match.worker")


@dataclass(frozen=True)
class _Claimed:
    job_id: int
    started_at: datetime
    sucursal: Optional[str]
    adjunto_path: Path
    filename: str
    articulos: list[Articulo]


def process_oc_match_job(job_id: int) -> None:
    """Background entry: claim queued→running, run pipeline, persist done|error."""
    claimed = _claim_and_load(job_id)
    if claimed is None:
        return
    extracted: Optional[dict[str, Any]] = None
    matched: dict[str, Any] = {}
    excel_rel: Optional[str] = None
    excel_name: Optional[str] = None
    excel_path: Optional[Path] = None
    error: Optional[str] = None
    try:
        if claimed.sucursal is None:
            raise RuntimeError("empresa del pedido no está mapeada a sucursal OC")
        if not claimed.adjunto_path.is_file():
            raise FileNotFoundError(f"adjunto ausente en disco: {claimed.adjunto_path}")
        pool = load_pool()
        _write_progress_phase(claimed.job_id, "extracting", claimed.started_at)
        extracted = extract_one(pool, claimed.adjunto_path.read_bytes(), claimed.filename)
        _write_progress_phase(claimed.job_id, "matching", claimed.started_at)
        matched = match_renglones(extracted, claimed.articulos, pool)
        _write_progress_phase(claimed.job_id, "excel", claimed.started_at)
        excel_path = _excel_dest(claimed.job_id, claimed.started_at, matched)
        generar(matched, excel_path)
        excel_rel = excel_path.name
        excel_name = excel_path.name
    except RechazoExcel as exc:
        error = str(exc)
        logger.info("oc-match job_id=%s rechazo excel: %s", job_id, error)
        _unlink_xlsx(excel_path)
    except MissingGeminiKeysError as exc:
        error = str(exc)
        logger.warning("oc-match job_id=%s sin keys Gemini", job_id)
    except Exception as exc:  # noqa: BLE001 — persist any pipeline failure as job error
        error = str(exc)
        logger.exception("oc-match job_id=%s falló: %s", job_id, exc)
        _unlink_xlsx(excel_path)

    acta = acta_cierre(
        matched,
        {"Sucursal": claimed.sucursal or "-"},
        error=error,
        excel_nombre=excel_name,
    )
    _persist(
        claimed.job_id,
        matched,
        acta,
        excel_rel,
        error,
        claimed_started_at=claimed.started_at,
        extracted=extracted,
    )


def _claim_and_load(job_id: int) -> Optional[_Claimed]:
    with get_background_db() as db:
        job = claim_queued_job(db, job_id)
        if job is None:
            return None
        if job.started_at is None:
            logger.warning("oc-match claim job_id=%s sin started_at; abort", job_id)
            return None
        pedido = db.get(PedidoCompra, job.pedido_id)
        adjunto = db.get(CompraAdjunto, job.attachment_id)
        sucursal = sucursal_oc_para_empresa(int(pedido.empresa_id)) if pedido is not None else None
        uploads = Path(settings.COMPRAS_UPLOADS_DIR)
        rel = adjunto.path_archivo if adjunto is not None else ""
        filename = adjunto.nombre_archivo if adjunto is not None else "proforma.pdf"
        articulos = sin_combos_internos(cargar_maestro(db))
        return _Claimed(
            job_id=job.id,
            started_at=job.started_at,
            sucursal=sucursal,
            adjunto_path=uploads / rel,
            filename=filename,
            articulos=articulos,
        )


def _write_progress_phase(job_id: int, phase: str, claimed_started_at: datetime) -> None:
    """UX-only stage stamp in a short session. Never changes status. Fail-soft + claim fence."""
    stamp = datetime.now(UTC)
    try:
        with get_background_db() as db:
            result = db.execute(
                update(OcMatchJob)
                .where(
                    OcMatchJob.id == job_id,
                    OcMatchJob.status == OcMatchJob.STATUS_RUNNING,
                    OcMatchJob.started_at == claimed_started_at,
                )
                .values(progress_phase=phase, updated_at=stamp)
            )
            if int(result.rowcount or 0) == 0:
                logger.info(
                    "oc-match progress_phase discarded job_id=%s phase=%s (lost claim fence)",
                    job_id,
                    phase,
                )
    except Exception:
        logger.warning(
            "oc-match job_id=%s no pudo persistir progress_phase=%s",
            job_id,
            phase,
            exc_info=True,
        )


def _claim_mid(job_id: int, started_at: datetime) -> str:
    """Stable unique token per claim for Excel filenames (not truncated by nombre_excel)."""
    ts = started_at if started_at.tzinfo is not None else started_at.replace(tzinfo=UTC)
    return f"{job_id}_{int(ts.timestamp())}"


def _excel_dest(job_id: int, started_at: datetime, matched: dict[str, Any]) -> Path:
    root = Path(settings.COMPRAS_OC_MATCH_DIR)
    root.mkdir(parents=True, exist_ok=True)
    return root / nombre_excel(matched, _claim_mid(job_id, started_at))


def _unlink_xlsx(path: Optional[Path]) -> None:
    """Remove only this claim's workbook path (never glob by job_id)."""
    if path is None:
        return
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.warning("oc-match no pudo borrar xlsx residual %s", path)


def _unlink_xlsx_rel(excel_rel: Optional[str]) -> None:
    if not excel_rel:
        return
    _unlink_xlsx(Path(settings.COMPRAS_OC_MATCH_DIR) / excel_rel)


def _persist(
    job_id: int,
    matched: dict[str, Any],
    acta: str,
    excel_rel: Optional[str],
    error: Optional[str],
    *,
    claimed_started_at: datetime,
    extracted: Optional[dict[str, Any]] = None,
) -> None:
    """Persist done|error only if this claim still owns the job (status+started_at fence)."""
    stamp = datetime.now(UTC)
    if error:
        status = OcMatchJob.STATUS_ERROR
        excel_value: Optional[str] = None
    else:
        status = OcMatchJob.STATUS_DONE
        excel_value = excel_rel
    with get_background_db() as db:
        result = db.execute(
            update(OcMatchJob)
            .where(
                OcMatchJob.id == job_id,
                OcMatchJob.status == OcMatchJob.STATUS_RUNNING,
                OcMatchJob.started_at == claimed_started_at,
            )
            .values(
                acta=acta,
                error_message=error,
                progress_phase=None,
                finished_at=stamp,
                updated_at=stamp,
                status=status,
                excel_rel_path=excel_value,
            )
        )
        if int(result.rowcount or 0) == 0:
            logger.info(
                "oc-match persist discarded job_id=%s (lost claim fence)",
                job_id,
            )
            _unlink_xlsx_rel(excel_rel)
            return
        if error:
            _unlink_xlsx_rel(excel_rel)
        job = db.get(OcMatchJob, job_id)
        if job is None:
            logger.warning("oc-match persist: job_id=%s desapareció tras fence", job_id)
            return
        _replace_renglones(db, job, matched)
        if extracted is None:
            return
        if job.doc_refs_aplicado_at is not None:
            return
        locked = (
            db.execute(select(PedidoCompra).where(PedidoCompra.id == job.pedido_id).with_for_update())
            .scalars()
            .one_or_none()
        )
        if locked is None:
            return
        if apply_writeback(locked, extracted):
            job.doc_refs_aplicado_at = datetime.now(UTC)
            nro_documento = token_or_none(extracted.get("nro_documento"))
            if normalize_tipo(extracted.get("tipo_documento")) == "factura" and nro_documento is not None:
                pedidos_service.persist_factura_documento(
                    db,
                    pedido=locked,
                    numero=nro_documento,
                    created_by_id=int(locked.creado_por_id),
                )
            db.flush()


def _replace_renglones(db: Session, job: OcMatchJob, matched: dict[str, Any]) -> None:
    job.renglones.clear()
    db.flush()
    for i, row in enumerate(matched.get("renglones") or []):
        m = row.get("match") or {}
        estado = m.get("estado")
        if estado not in (
            OcMatchRenglon.MATCH_OK,
            OcMatchRenglon.MATCH_NO_HALLADO,
            OcMatchRenglon.MATCH_OMITIDO,
        ):
            estado = None
        db.add(
            OcMatchRenglon(
                job_id=job.id,
                indice=i,
                descripcion=row.get("descripcion"),
                cantidad=_decimal_or_none(row.get("cantidad")),
                precio_unitario=_decimal_or_none(row.get("precio_unitario")),
                moneda=_str_or_none(row.get("moneda"), 3),
                codigo_proveedor=_str_or_none(row.get("codigo_proveedor"), 100),
                codigo_fabricante=_str_or_none(row.get("codigo_fabricante"), 100),
                ean_extract=_str_or_none(row.get("ean_proforma"), 32),
                ean_ultimos4=_str_or_none(row.get("ean_ultimos4"), 4),
                omitir=bool(row.get("omitir")),
                motivo_omitir=row.get("motivo_omitir"),
                match_estado=estado,
                item_id=_str_or_none(m.get("item_id"), 64),
                ean=_str_or_none(m.get("ean"), 32),
                confianza=_str_or_none(m.get("confianza"), 16),
                motivo=m.get("motivo"),
            )
        )


def _decimal_or_none(raw: object) -> Optional[Decimal]:
    if raw is None or isinstance(raw, bool):
        return None
    try:
        return Decimal(str(raw))
    except Exception:  # noqa: BLE001 — persist null on bad numeric
        return None


def _str_or_none(raw: object, max_len: int) -> Optional[str]:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    return text[:max_len]
