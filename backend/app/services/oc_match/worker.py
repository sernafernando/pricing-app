"""Two-session OC-match worker: claim; Gemini/excel with no Session; persist."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.core.compras_empresa_oc_map import sucursal_oc_para_empresa
from app.core.config import settings
from app.core.database import get_background_db
from app.core.logging import get_logger
from app.models.compra_adjunto import CompraAdjunto
from app.models.oc_match_job import OcMatchJob, OcMatchRenglon
from app.models.pedido_compra import PedidoCompra
from app.services.oc_match.acta import acta_cierre, nombre_excel
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
    sucursal: Optional[str]
    adjunto_path: Path
    filename: str
    articulos: list[Articulo]


def process_oc_match_job(job_id: int) -> None:
    """Background entry: claim queued→running, run pipeline, persist done|error."""
    claimed = _claim_and_load(job_id)
    if claimed is None:
        return
    matched: dict[str, Any] = {}
    excel_rel: Optional[str] = None
    excel_name: Optional[str] = None
    error: Optional[str] = None
    try:
        if claimed.sucursal is None:
            raise RuntimeError("empresa del pedido no está mapeada a sucursal OC")
        if not claimed.adjunto_path.is_file():
            raise FileNotFoundError(f"adjunto ausente en disco: {claimed.adjunto_path}")
        pool = load_pool()
        extracted = extract_one(pool, claimed.adjunto_path.read_bytes(), claimed.filename)
        matched = match_renglones(extracted, claimed.articulos, pool)
        dest = _excel_dest(claimed.job_id, matched)
        generar(matched, dest)
        excel_rel = dest.name
        excel_name = dest.name
    except RechazoExcel as exc:
        error = str(exc)
        logger.info("oc-match job_id=%s rechazo excel: %s", job_id, error)
        _unlink_if_empty_xlsx(job_id)
    except MissingGeminiKeysError as exc:
        error = str(exc)
        logger.warning("oc-match job_id=%s sin keys Gemini", job_id)
    except Exception as exc:  # noqa: BLE001 — persist any pipeline failure as job error
        error = str(exc)
        logger.exception("oc-match job_id=%s falló: %s", job_id, exc)

    acta = acta_cierre(
        matched,
        {"Sucursal": claimed.sucursal or "-"},
        error=error,
        excel_nombre=excel_name,
    )
    _persist(job_id, matched, acta, excel_rel, error)


def _claim_and_load(job_id: int) -> Optional[_Claimed]:
    with get_background_db() as db:
        job = claim_queued_job(db, job_id)
        if job is None:
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
            sucursal=sucursal,
            adjunto_path=uploads / rel,
            filename=filename,
            articulos=articulos,
        )


def _excel_dest(job_id: int, matched: dict[str, Any]) -> Path:
    root = Path(settings.COMPRAS_OC_MATCH_DIR)
    root.mkdir(parents=True, exist_ok=True)
    return root / nombre_excel(matched, str(job_id))


def _unlink_if_empty_xlsx(job_id: int) -> None:
    """Never leave a failed/empty xlsx as a success artifact."""
    root = Path(settings.COMPRAS_OC_MATCH_DIR)
    if not root.is_dir():
        return
    for path in root.glob(f"*_{job_id}.xlsx"):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.warning("oc-match no pudo borrar xlsx residual %s", path)


def _persist(
    job_id: int,
    matched: dict[str, Any],
    acta: str,
    excel_rel: Optional[str],
    error: Optional[str],
) -> None:
    stamp = datetime.now(UTC)
    with get_background_db() as db:
        job = db.get(OcMatchJob, job_id)
        if job is None:
            logger.warning("oc-match persist: job_id=%s desapareció", job_id)
            return
        job.acta = acta
        job.error_message = error
        job.finished_at = stamp
        job.updated_at = stamp
        if error:
            job.status = OcMatchJob.STATUS_ERROR
            job.excel_rel_path = None
        else:
            job.status = OcMatchJob.STATUS_DONE
            job.excel_rel_path = excel_rel
        _replace_renglones(db, job, matched)


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
