"""
compras_adjuntos_service — subida / listado / descarga / borrado de adjuntos polimórficos.

Soporta dos entidades (pedido_compra, orden_pago) sobre UNA sola tabla.
El patrón de validación de magic bytes + tamaño replica el usado en
`rrhh_empleados.py` (RRHH_UPLOADS_DIR / RRHH_MAX_FILE_SIZE_MB), pero
restringido a los formatos permitidos por el negocio de compras:

    PDF, JPG/JPEG, PNG, WebP, DOCX, XLSX, DOC (legacy), XLS (legacy).

Los DOCX/XLSX son contenedores ZIP (magic PK\\x03\\x04). Los legacy DOC/XLS
comparten magic OLE2 (D0CF11E0A1B11AE1). Aceptamos ambos headers — no
discriminamos por extensión porque para el usuario son "archivos de Office"
y el browser igualmente mandará su content_type específico.

Los archivos se guardan en:
    {COMPRAS_UPLOADS_DIR}/{entidad_tipo}/{entidad_id}/{uuid}_{filename}

La columna `path_archivo` es RELATIVA (no incluye la raíz). El endpoint de
descarga concatena `settings.COMPRAS_UPLOADS_DIR` + `path_archivo` al
resolver el archivo físico.

NO hay commit implícito — el caller orquesta. El service hace `flush` para
que el ID esté disponible.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Literal, Optional

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.logging import get_logger
from app.models.compra_adjunto import CompraAdjunto

logger = get_logger("services.compras_adjuntos_service")


EntidadAdjuntable = Literal["pedido_compra", "orden_pago"]
TipoAdjunto = Literal["factura", "presupuesto", "comprobante", "otro"]

_ENTIDADES_VALIDAS: frozenset[str] = frozenset({"pedido_compra", "orden_pago"})
_TIPOS_VALIDOS: frozenset[str] = frozenset({"factura", "presupuesto", "comprobante", "otro"})


# ──────────────────────────────────────────────────────────────────────────
# Magic-bytes validation (whitelist estricta)
# ──────────────────────────────────────────────────────────────────────────


def _validate_magic_compras(content: bytes, filename: str) -> bool:
    """
    Valida que `content` coincida con uno de los formatos permitidos.

    Whitelist (en orden de probabilidad de uso):
      - PDF:            `%PDF`
      - JPEG:           `FF D8 FF`
      - PNG:            `89 50 4E 47 0D 0A 1A 0A`
      - WebP:           `RIFF....WEBP`
      - DOCX/XLSX/ZIP:  `PK\\x03\\x04` (Office Open XML = ZIP)
      - DOC/XLS legacy: `D0CF11E0A1B11AE1` (OLE2 Compound)

    Args:
        content: primeros bytes del archivo (idealmente el buffer completo).
        filename: nombre del archivo (solo para logging — NO se usa para validar,
            porque la extensión es manipulable).

    Returns:
        True si el header matchea algún formato permitido, False si no.
    """
    if len(content) < 8:
        return False

    header = content[:16]

    # PDF
    if header.startswith(b"%PDF"):
        return True
    # JPEG
    if header.startswith(b"\xff\xd8\xff"):
        return True
    # PNG
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return True
    # WebP (RIFF container con "WEBP" en offset 8)
    if header[:4] == b"RIFF" and len(content) >= 12 and content[8:12] == b"WEBP":
        return True
    # DOCX / XLSX / ZIP genérico
    if header.startswith(b"PK\x03\x04"):
        return True
    # DOC / XLS legacy (OLE2 Compound Document)
    if header.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return True

    logger.warning(
        "compras_adjuntos: magic bytes no reconocidos (filename=%r, primeros_16=%r)",
        filename,
        header,
    )
    return False


# ──────────────────────────────────────────────────────────────────────────
# Helpers de path
# ──────────────────────────────────────────────────────────────────────────


def _validar_entidad_tipo(entidad_tipo: str) -> None:
    if entidad_tipo not in _ENTIDADES_VALIDAS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(f"entidad_tipo inválido: '{entidad_tipo}'. Valores: {sorted(_ENTIDADES_VALIDAS)}."),
        )


def _validar_tipo(tipo: Optional[str]) -> None:
    if tipo is None:
        return
    if tipo not in _TIPOS_VALIDOS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(f"tipo inválido: '{tipo}'. Valores: {sorted(_TIPOS_VALIDOS)} o None."),
        )


def _sanitize_filename(name: str) -> str:
    """Quita path components y chars peligrosos. Mantiene espacios y unicode."""
    base = os.path.basename(name or "archivo")
    # Bloqueo defensivo de `..` en windows rutas con `\`
    base = base.replace("\\", "_").replace("/", "_")
    return base or "archivo"


def _full_path(adj: CompraAdjunto) -> Path:
    """Resuelve el path físico absoluto del adjunto."""
    return Path(settings.COMPRAS_UPLOADS_DIR) / adj.path_archivo


# ──────────────────────────────────────────────────────────────────────────
# Operaciones públicas
# ──────────────────────────────────────────────────────────────────────────


async def subir_adjunto(
    session: Session,
    *,
    entidad_tipo: EntidadAdjuntable,
    entidad_id: int,
    file: UploadFile,
    tipo: Optional[TipoAdjunto] = None,
    descripcion: Optional[str] = None,
    user_id: Optional[int] = None,
) -> CompraAdjunto:
    """
    Valida + guarda a disco + registra en DB (flush, sin commit).

    Args:
        session: sesión activa — el caller hace commit.
        entidad_tipo: 'pedido_compra' o 'orden_pago'.
        entidad_id: PK de la entidad (el caller DEBE haber validado que exista).
        file: UploadFile que llega del endpoint.
        tipo: hint opcional sobre el rol del adjunto.
        descripcion: texto libre opcional.
        user_id: FK a usuarios (SET NULL en borrado del usuario).

    Returns:
        El `CompraAdjunto` recién insertado con `id` asignado.

    Raises:
        HTTPException 400 si:
          - entidad_tipo inválido,
          - tipo fuera de la whitelist,
          - archivo > COMPRAS_MAX_FILE_SIZE_MB,
          - magic bytes no coinciden con ningún formato permitido.
    """
    _validar_entidad_tipo(entidad_tipo)
    _validar_tipo(tipo)

    content = await file.read()
    max_bytes = settings.COMPRAS_MAX_FILE_SIZE_MB * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Archivo demasiado grande ({len(content)} bytes). "
                f"Máximo permitido: {settings.COMPRAS_MAX_FILE_SIZE_MB} MB."
            ),
        )

    safe_filename = _sanitize_filename(file.filename or "archivo")
    if not _validate_magic_compras(content, safe_filename):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=("Formato no permitido. Formatos aceptados: PDF, JPG, PNG, WebP, DOCX, XLSX, DOC, XLS."),
        )

    # Guardar en disco
    upload_dir = Path(settings.COMPRAS_UPLOADS_DIR) / entidad_tipo / str(entidad_id)
    upload_dir.mkdir(parents=True, exist_ok=True)

    stored_name = f"{uuid.uuid4().hex}_{safe_filename}"
    full_path = upload_dir / stored_name
    try:
        with open(full_path, "wb") as f:
            f.write(content)
    except OSError as exc:
        logger.exception(
            "compras_adjuntos: no pude escribir archivo en disco (path=%s): %s",
            full_path,
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al guardar el archivo en el servidor.",
        ) from exc

    rel_path = str(Path(entidad_tipo) / str(entidad_id) / stored_name)

    adj = CompraAdjunto(
        entidad_tipo=entidad_tipo,
        entidad_id=entidad_id,
        nombre_archivo=safe_filename,
        path_archivo=rel_path,
        mime_type=file.content_type,
        tamano_bytes=len(content),
        tipo=tipo,
        descripcion=descripcion,
        subido_por_id=user_id,
    )
    session.add(adj)
    session.flush()

    logger.info(
        "compras_adjuntos: creado id=%s entidad=%s:%s nombre=%r tamano=%s user_id=%s",
        adj.id,
        entidad_tipo,
        entidad_id,
        safe_filename,
        len(content),
        user_id,
    )
    return adj


def listar_adjuntos(
    session: Session,
    *,
    entidad_tipo: EntidadAdjuntable,
    entidad_id: int,
) -> list[CompraAdjunto]:
    """Devuelve adjuntos de una entidad ordenados por `created_at DESC`."""
    _validar_entidad_tipo(entidad_tipo)
    stmt = (
        select(CompraAdjunto)
        .options(selectinload(CompraAdjunto.subido_por))
        .where(
            CompraAdjunto.entidad_tipo == entidad_tipo,
            CompraAdjunto.entidad_id == entidad_id,
        )
        .order_by(CompraAdjunto.created_at.desc(), CompraAdjunto.id.desc())
    )
    return list(session.execute(stmt).scalars().all())


def obtener_adjunto(session: Session, adjunto_id: int) -> CompraAdjunto:
    """Busca un adjunto por ID o levanta 404."""
    adj = session.get(CompraAdjunto, adjunto_id)
    if adj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Adjunto id={adjunto_id} no encontrado.",
        )
    return adj


def eliminar_adjunto(session: Session, *, adjunto_id: int) -> None:
    """
    Elimina el registro de la DB y el archivo físico del disco.

    Si el archivo físico no existe (caso edge: borrado manual, restore
    parcial), NO falla: solo loggea WARNING y borra la fila. Objetivo:
    que la UI pueda limpiar huérfanos sin quedar tascada.

    NO commit — el caller orquesta.
    """
    adj = obtener_adjunto(session, adjunto_id)
    full_path = _full_path(adj)
    if full_path.exists():
        try:
            full_path.unlink()
        except OSError as exc:
            logger.warning(
                "compras_adjuntos: fallo al borrar archivo físico id=%s path=%s: %s",
                adj.id,
                full_path,
                exc,
            )
    else:
        logger.warning(
            "compras_adjuntos: archivo físico no existía al borrar id=%s path=%s",
            adj.id,
            full_path,
        )
    session.delete(adj)
    session.flush()
    logger.info(
        "compras_adjuntos: eliminado id=%s entidad=%s:%s",
        adj.id,
        adj.entidad_tipo,
        adj.entidad_id,
    )


__all__ = [
    "EntidadAdjuntable",
    "TipoAdjunto",
    "_validate_magic_compras",
    "subir_adjunto",
    "listar_adjuntos",
    "obtener_adjunto",
    "eliminar_adjunto",
]
