"""
Endpoint for rewriting ^LH y-offset values in ZPL label files.

Route: POST /api/etiquetas-envio/reescribir-lh
Permission: etiquetas.reescribir_lh

Accepts .txt or .zip uploads, rewrites every ^LH y-value to target_y,
returns the corrected .txt as a StreamingResponse blob with feedback headers.
"""

import logging
from io import BytesIO
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.usuario import Usuario
from app.services.permisos_service import verificar_permiso
from app.services.zpl_label_home_service import (
    AmbiguousZipError,
    BadZipError,
    NoLabelHomeError,
    NoTxtInZipError,
    derive_output_filename,
    extract_inner_txt,
    rewrite_label_home,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _check_permiso(db: Session, user: Usuario, codigo: str) -> None:
    """Verify the user holds the given permission; raise 403 if not."""
    if not verificar_permiso(db, user, codigo):
        raise HTTPException(
            status_code=403,
            detail=f"No tenés permiso: {codigo}",
        )


@router.post(
    "/etiquetas-envio/reescribir-lh",
    summary="Reescribir ^LH y-offset en archivos ZPL de etiquetas",
    response_class=StreamingResponse,
)
def reescribir_lh(
    file: UploadFile = File(...),
    target_y: int = Form(450),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> StreamingResponse:
    """Rewrite every ^LH y-value in a ZPL label file to the given target_y.

    Accepts .txt or .zip uploads. Returns the corrected .txt as a blob.
    Feedback is delivered via custom X-* response headers.

    Permission required: etiquetas.reescribir_lh
    """
    # 1. Permission check
    _check_permiso(db, current_user, "etiquetas.reescribir_lh")

    # 2. Validate target_y — FastAPI coerces to int (422 on non-int); add range check
    if target_y < 0:
        raise HTTPException(
            status_code=400,
            detail="El offset Y debe ser un entero >= 0.",
        )

    # 3. Read raw bytes
    raw = file.file.read()

    # 4. Determine file type and extract inner bytes + stem
    filename_lower = (file.filename or "").lower()
    is_zip = filename_lower.endswith(".zip") or raw[:2] == b"PK"

    if is_zip:
        try:
            inner, stem = extract_inner_txt(raw)
        except NoTxtInZipError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except AmbiguousZipError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except BadZipError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    elif filename_lower.endswith(".txt"):
        inner = raw
        stem = Path(file.filename or "etiqueta").stem
    else:
        raise HTTPException(
            status_code=400,
            detail=("Formato no soportado. Solo se aceptan archivos .txt o .zip con ZPL de etiquetas."),
        )

    # 5. Run pure transform
    try:
        result = rewrite_label_home(inner, target_y)
    except NoLabelHomeError as exc:
        # 422 Unprocessable Content: the upload is well-formed but contains
        # no ^LH command to rewrite, so there is nothing to process.
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # 6. Derive safe output filename
    out_name = derive_output_filename(stem)

    # 7. Build StreamingResponse with file blob and feedback headers
    headers = {
        "Content-Disposition": f'attachment; filename="{out_name}"',
        "X-Etiquetas-Detectadas": str(result.labels_detected),
        "X-LH-Modificados": str(result.lh_modified),
        "X-LH-Heterogeneo": "true" if result.heterogeneous else "false",
        "X-LL-Warning": result.ll_warning,
    }

    logger.info(
        "✅ reescribir_lh: stem=%s target_y=%d labels=%d modified=%d hetero=%s",
        stem,
        target_y,
        result.labels_detected,
        result.lh_modified,
        result.heterogeneous,
    )

    return StreamingResponse(
        BytesIO(result.content),
        media_type="text/plain",
        headers=headers,
    )
