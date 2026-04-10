"""
Endpoints de carga y borrado de etiquetas de envío.

Incluye:
- Upload de archivos ZPL (.zip/.txt)
- Escaneo manual con pistola (QR individual)
- Borrado de etiquetas (con auditoría)
"""

import json
import zipfile
from datetime import date
from io import BytesIO
from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, File
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.sse import sse_publish_bg
from app.api.deps import get_current_user
from app.models.usuario import Usuario
from app.models.etiqueta_envio import EtiquetaEnvio
from app.models.etiqueta_envio_audit import EtiquetaEnvioAudit
from app.services.etiqueta_enrichment_service import enriquecer_etiquetas_sync

from app.api.endpoints.etiquetas_shared import (
    _check_permiso,
    _extraer_qrs_de_texto,
    _insertar_etiqueta,
    _parse_qr_json,
    BorrarEtiquetasRequest,
    ManualScanRequest,
    ManualScanResponse,
    UploadResultResponse,
)

router = APIRouter()


@router.post(
    "/etiquetas-envio/upload",
    response_model=UploadResultResponse,
    summary="Subir archivo ZPL (.zip o .txt) con etiquetas",
)
def upload_etiquetas(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="Archivo .zip o .txt con etiquetas ZPL"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> UploadResultResponse:
    """
    Recibe un .zip (que contiene .txt) o directamente un .txt con etiquetas ZPL.
    Extrae los JSONs de los QR codes, parsea shipping_id/sender_id/hash_code
    e inserta en etiquetas_envio con ON CONFLICT(shipping_id) DO NOTHING.
    """
    _check_permiso(db, current_user, "envios_flex.subir_etiquetas")

    if not file.filename:
        raise HTTPException(400, "Archivo sin nombre")

    filename = file.filename.lower()
    if not filename.endswith((".zip", ".txt")):
        raise HTTPException(400, "Solo se aceptan archivos .zip o .txt")

    contents = file.file.read()
    nombre_archivo = file.filename
    text_content = ""

    if filename.endswith(".zip"):
        try:
            with zipfile.ZipFile(BytesIO(contents)) as zf:
                # Buscar el primer .txt dentro del zip
                txt_files = [
                    name for name in zf.namelist() if name.lower().endswith(".txt") and not name.startswith("__MACOSX")
                ]
                if not txt_files:
                    raise HTTPException(400, "El .zip no contiene archivos .txt")

                text_content = zf.read(txt_files[0]).decode("utf-8", errors="replace")
        except zipfile.BadZipFile:
            raise HTTPException(400, "Archivo .zip inválido o corrupto")
    else:
        text_content = contents.decode("utf-8", errors="replace")

    # Extraer QR JSONs
    qr_jsons = _extraer_qrs_de_texto(text_content)

    if not qr_jsons:
        raise HTTPException(400, "No se encontraron etiquetas QR en el archivo")

    total = len(qr_jsons)
    nuevas = 0
    duplicadas = 0
    errores = 0
    detalle_errores: List[str] = []
    nuevos_shipping_ids: List[str] = []
    hoy = date.today()

    for raw_json in qr_jsons:
        try:
            parsed = _parse_qr_json(raw_json)
            es_nueva = _insertar_etiqueta(
                db=db,
                shipping_id=parsed["shipping_id"],
                sender_id=parsed["sender_id"],
                hash_code=parsed["hash_code"],
                nombre_archivo=nombre_archivo,
                fecha_envio=hoy,
            )
            if es_nueva:
                nuevas += 1
                nuevos_shipping_ids.append(parsed["shipping_id"])
            else:
                duplicadas += 1
        except (json.JSONDecodeError, ValueError) as e:
            errores += 1
            detalle_errores.append(f"Error parseando QR: {str(e)[:100]}")

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"Error guardando en base de datos: {str(e)}")

    # Enriquecer etiquetas nuevas en background (coords, dirección, comentario)
    if nuevos_shipping_ids:
        background_tasks.add_task(enriquecer_etiquetas_sync, nuevos_shipping_ids)

    # SSE: notify clients that etiquetas changed (single event for bulk upload)
    sse_publish_bg("etiquetas:changed", {"hint": "reload"})

    return UploadResultResponse(
        total=total,
        nuevas=nuevas,
        duplicadas=duplicadas,
        errores=errores,
        detalle_errores=detalle_errores[:20],
    )


@router.post(
    "/etiquetas-envio/manual",
    response_model=ManualScanResponse,
    summary="Registrar etiqueta individual (escaneo con pistola)",
)
def registrar_manual(
    payload: ManualScanRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> ManualScanResponse:
    """
    Recibe el JSON del QR escaneado con pistola de código de barras.
    Inserta la etiqueta si no existe.
    """
    _check_permiso(db, current_user, "envios_flex.subir_etiquetas")

    try:
        parsed = _parse_qr_json(payload.json_data)
    except (json.JSONDecodeError, ValueError) as e:
        raise HTTPException(400, f"JSON inválido: {str(e)}")

    es_nueva = _insertar_etiqueta(
        db=db,
        shipping_id=parsed["shipping_id"],
        sender_id=parsed["sender_id"],
        hash_code=parsed["hash_code"],
        nombre_archivo="escaneo_manual",
        fecha_envio=date.today(),
    )

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"Error guardando: {str(e)}")

    shipping_id = parsed["shipping_id"]

    if es_nueva:
        # Enriquecer en background (coords, dirección, comentario)
        background_tasks.add_task(enriquecer_etiquetas_sync, [shipping_id])

        # SSE: notify clients that etiquetas changed
        sse_publish_bg("etiquetas:changed", {"hint": "reload"})

        return ManualScanResponse(
            duplicada=False,
            shipping_id=shipping_id,
            mensaje=f"Cargado: {shipping_id}",
        )
    else:
        return ManualScanResponse(
            duplicada=True,
            shipping_id=shipping_id,
            mensaje=f"Ya existía: {shipping_id}",
        )


@router.delete(
    "/etiquetas-envio",
    response_model=dict,
    summary="Borrar etiquetas de envío (con auditoría)",
)
def borrar_etiquetas(
    payload: BorrarEtiquetasRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> dict:
    """
    Elimina etiquetas por shipping_id.
    Antes de borrar, copia cada etiqueta a etiquetas_envio_audit
    con el usuario que borró, timestamp y comentario opcional.
    """
    _check_permiso(db, current_user, "envios_flex.eliminar")

    # Buscar etiquetas a borrar
    etiquetas = db.query(EtiquetaEnvio).filter(EtiquetaEnvio.shipping_id.in_(payload.shipping_ids)).all()

    if not etiquetas:
        raise HTTPException(404, "No se encontraron etiquetas para borrar")

    # Copiar a audit antes de borrar
    for etiq in etiquetas:
        audit = EtiquetaEnvioAudit(
            shipping_id=etiq.shipping_id,
            sender_id=etiq.sender_id,
            hash_code=etiq.hash_code,
            nombre_archivo=etiq.nombre_archivo,
            fecha_envio=etiq.fecha_envio,
            logistica_id=etiq.logistica_id,
            latitud=etiq.latitud,
            longitud=etiq.longitud,
            direccion_completa=etiq.direccion_completa,
            direccion_comentario=etiq.direccion_comentario,
            pistoleado_at=etiq.pistoleado_at,
            pistoleado_caja=etiq.pistoleado_caja,
            pistoleado_operador_id=etiq.pistoleado_operador_id,
            original_created_at=etiq.created_at,
            original_updated_at=etiq.updated_at,
            deleted_by=current_user.id,
            delete_comment=payload.comment,
        )
        db.add(audit)

    # Desasociar items de RMA que referencian estas etiquetas
    if payload.shipping_ids:
        placeholders = ", ".join(f":id_{i}" for i in range(len(payload.shipping_ids)))
        params = {f"id_{i}": sid for i, sid in enumerate(payload.shipping_ids)}
        db.execute(
            text(f"UPDATE rma_caso_items SET shipping_id = NULL WHERE shipping_id IN ({placeholders})"),
            params,
        )

    # Borrar originales
    deleted = (
        db.query(EtiquetaEnvio)
        .filter(EtiquetaEnvio.shipping_id.in_(payload.shipping_ids))
        .delete(synchronize_session="fetch")
    )

    db.commit()
    sse_publish_bg("etiquetas:changed", {"hint": "reload"})

    return {"ok": True, "eliminadas": deleted}
