"""
Servicio de Caja — Cash Register module.

Gestiona cajas, movimientos (con balance atómico), categorías,
tipos de documento, documentos (N:M con movimientos), y archivos adjuntos.

Convención de saldo:
- monto siempre positivo; el tipo (ingreso/egreso) determina dirección
- saldo_posterior = snapshot del saldo de la caja DESPUÉS de cada movimiento
- saldo_actual en la cabecera Caja = denormalizado, updated transaccionalmente
"""

import os
import uuid
from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session, joinedload

from app.core.config import settings
from app.models.caja import (
    Caja,
    CajaArchivo,
    CajaCategoria,
    CajaDocumento,
    CajaDocumentoMovimiento,
    CajaMovimiento,
    CajaTipoDocumento,
)

# Allowed MIME types for file uploads
ALLOWED_MIME_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/webp",
}
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB


class CajaService:
    """Servicio para operaciones de caja."""

    def __init__(self, db: Session):
        self.db = db

    # ──────────────────────────────────────────────
    # Cajas CRUD
    # ──────────────────────────────────────────────

    def listar_cajas(
        self,
        activo: Optional[bool] = None,
        empresa_id: Optional[int] = None,
    ) -> list[Caja]:
        """Lista cajas con empresa joined."""
        query = self.db.query(Caja).options(joinedload(Caja.empresa))
        if activo is not None:
            query = query.filter(Caja.activo == activo)
        if empresa_id is not None:
            query = query.filter(Caja.empresa_id == empresa_id)
        return query.order_by(Caja.nombre).all()

    def obtener_caja(self, caja_id: int) -> Caja:
        """Obtiene caja por ID o lanza 404."""
        caja = self.db.query(Caja).options(joinedload(Caja.empresa)).filter(Caja.id == caja_id).first()
        if not caja:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Caja {caja_id} no encontrada",
            )
        return caja

    def crear_caja(
        self,
        nombre: str,
        empresa_id: int,
        moneda: str,
        saldo_inicial: Decimal,
    ) -> Caja:
        """Crea caja con saldo_actual = saldo_inicial."""
        caja = Caja(
            nombre=nombre,
            empresa_id=empresa_id,
            moneda=moneda,
            saldo_inicial=saldo_inicial,
            saldo_actual=saldo_inicial,
        )
        self.db.add(caja)
        self.db.flush()
        return caja

    def actualizar_caja(
        self,
        caja_id: int,
        nombre: Optional[str] = None,
        activo: Optional[bool] = None,
    ) -> Caja:
        """Actualiza solo nombre y/o activo. moneda/empresa no se cambian."""
        caja = self.obtener_caja(caja_id)
        if nombre is not None:
            caja.nombre = nombre
        if activo is not None:
            caja.activo = activo
        self.db.flush()
        return caja

    def eliminar_caja(self, caja_id: int) -> None:
        """Elimina caja si no tiene movimientos. 409 si tiene."""
        caja = self.obtener_caja(caja_id)
        mov_count = self.db.query(sa_func.count(CajaMovimiento.id)).filter(CajaMovimiento.caja_id == caja_id).scalar()
        if mov_count > 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"No se puede eliminar la caja con {mov_count} movimientos. Desactive en su lugar.",
            )
        self.db.delete(caja)
        self.db.flush()

    # ──────────────────────────────────────────────
    # Movimientos
    # ──────────────────────────────────────────────

    def registrar_movimiento(
        self,
        caja_id: int,
        fecha: date,
        detalle: str,
        tipo: str,
        monto: Decimal,
        user_id: Optional[int] = None,
        categoria_id: Optional[int] = None,
        observaciones: Optional[str] = None,
        origen: str = "manual",
    ) -> CajaMovimiento:
        """
        Registra un movimiento con balance atómico.

        Uses SELECT FOR UPDATE to lock the caja row,
        calculates saldo_posterior, creates movement,
        and updates caja.saldo_actual — all in one transaction.
        """
        # SELECT FOR UPDATE — lock the caja row
        caja = self.db.query(Caja).filter(Caja.id == caja_id).with_for_update().first()
        if not caja:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Caja {caja_id} no encontrada",
            )

        # Validate category compatibility
        if categoria_id is not None:
            categoria = self.db.query(CajaCategoria).filter(CajaCategoria.id == categoria_id).first()
            if not categoria:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Categoría {categoria_id} no encontrada",
                )
            if categoria.tipo_aplicable != "ambos" and categoria.tipo_aplicable != tipo:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Categoría '{categoria.nombre}' no es aplicable a movimientos de tipo '{tipo}'",
                )

        # Calculate new balance
        saldo_actual = Decimal(str(caja.saldo_actual))
        monto_dec = Decimal(str(monto))
        if tipo == "ingreso":
            saldo_posterior = saldo_actual + monto_dec
        else:
            saldo_posterior = saldo_actual - monto_dec

        # Create movement
        movimiento = CajaMovimiento(
            caja_id=caja_id,
            fecha=fecha,
            detalle=detalle,
            tipo=tipo,
            monto=monto_dec,
            saldo_posterior=saldo_posterior,
            categoria_id=categoria_id,
            origen=origen,
            registrado_por_id=user_id,
            observaciones=observaciones,
        )
        self.db.add(movimiento)

        # Update caja running balance
        caja.saldo_actual = saldo_posterior
        self.db.flush()
        return movimiento

    def obtener_movimientos(
        self,
        caja_id: int,
        page: int = 1,
        page_size: int = 50,
        fecha_desde: Optional[date] = None,
        fecha_hasta: Optional[date] = None,
        tipo: Optional[str] = None,
        categoria_id: Optional[int] = None,
        busqueda: Optional[str] = None,
    ) -> tuple[list[CajaMovimiento], int, dict]:
        """
        Returns (items, total_count, summary_dict).

        summary_dict: {total_ingresos, total_egresos, saldo_periodo}
        """
        query = (
            self.db.query(CajaMovimiento)
            .options(
                joinedload(CajaMovimiento.categoria),
                joinedload(CajaMovimiento.registrado_por),
            )
            .filter(CajaMovimiento.caja_id == caja_id)
        )

        if fecha_desde:
            query = query.filter(CajaMovimiento.fecha >= fecha_desde)
        if fecha_hasta:
            query = query.filter(CajaMovimiento.fecha <= fecha_hasta)
        if tipo:
            query = query.filter(CajaMovimiento.tipo == tipo)
        if categoria_id is not None:
            query = query.filter(CajaMovimiento.categoria_id == categoria_id)
        if busqueda:
            query = query.filter(CajaMovimiento.detalle.ilike(f"%{busqueda}%"))

        total = query.count()

        # Summary (on the same filtered set)
        summary_query = self.db.query(
            CajaMovimiento.tipo,
            sa_func.sum(CajaMovimiento.monto).label("total"),
        ).filter(CajaMovimiento.caja_id == caja_id)
        if fecha_desde:
            summary_query = summary_query.filter(CajaMovimiento.fecha >= fecha_desde)
        if fecha_hasta:
            summary_query = summary_query.filter(CajaMovimiento.fecha <= fecha_hasta)
        if tipo:
            summary_query = summary_query.filter(CajaMovimiento.tipo == tipo)
        if categoria_id is not None:
            summary_query = summary_query.filter(CajaMovimiento.categoria_id == categoria_id)
        if busqueda:
            summary_query = summary_query.filter(CajaMovimiento.detalle.ilike(f"%{busqueda}%"))

        summary_rows = summary_query.group_by(CajaMovimiento.tipo).all()
        total_ingresos = Decimal("0")
        total_egresos = Decimal("0")
        for row in summary_rows:
            if row.tipo == "ingreso":
                total_ingresos = Decimal(str(row.total or 0))
            elif row.tipo == "egreso":
                total_egresos = Decimal(str(row.total or 0))

        summary = {
            "total_ingresos": float(total_ingresos),
            "total_egresos": float(total_egresos),
            "saldo_periodo": float(total_ingresos - total_egresos),
        }

        # Paginated items
        offset = (page - 1) * page_size
        items = (
            query.order_by(CajaMovimiento.fecha.desc(), CajaMovimiento.id.desc()).offset(offset).limit(page_size).all()
        )

        return items, total, summary

    def recalcular_saldo(self, caja_id: int) -> Decimal:
        """Recalcula saldo_actual desde saldo_inicial + todos los movimientos."""
        caja = self.obtener_caja(caja_id)
        saldo = Decimal(str(caja.saldo_inicial))

        movimientos = (
            self.db.query(CajaMovimiento)
            .filter(CajaMovimiento.caja_id == caja_id)
            .order_by(CajaMovimiento.fecha.asc(), CajaMovimiento.id.asc())
            .all()
        )
        for mov in movimientos:
            monto = Decimal(str(mov.monto))
            if mov.tipo == "ingreso":
                saldo += monto
            else:
                saldo -= monto
            mov.saldo_posterior = saldo

        caja.saldo_actual = saldo
        self.db.flush()
        return saldo

    # ──────────────────────────────────────────────
    # Categorías
    # ──────────────────────────────────────────────

    def listar_categorias(self, incluir_inactivas: bool = False) -> list[CajaCategoria]:
        """Lista categorías."""
        query = self.db.query(CajaCategoria)
        if not incluir_inactivas:
            query = query.filter(CajaCategoria.activo.is_(True))
        return query.order_by(CajaCategoria.nombre).all()

    def crear_categoria(self, nombre: str, tipo_aplicable: str = "ambos") -> CajaCategoria:
        """Crea categoría. 409 si nombre duplicado."""
        existing = self.db.query(CajaCategoria).filter(CajaCategoria.nombre == nombre).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Ya existe una categoría con el nombre '{nombre}'",
            )
        cat = CajaCategoria(nombre=nombre, tipo_aplicable=tipo_aplicable)
        self.db.add(cat)
        self.db.flush()
        return cat

    def actualizar_categoria(
        self,
        cat_id: int,
        nombre: Optional[str] = None,
        tipo_aplicable: Optional[str] = None,
        activo: Optional[bool] = None,
    ) -> CajaCategoria:
        """Actualiza categoría."""
        cat = self.db.query(CajaCategoria).filter(CajaCategoria.id == cat_id).first()
        if not cat:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Categoría {cat_id} no encontrada",
            )
        if nombre is not None:
            cat.nombre = nombre
        if tipo_aplicable is not None:
            cat.tipo_aplicable = tipo_aplicable
        if activo is not None:
            cat.activo = activo
        self.db.flush()
        return cat

    def eliminar_categoria(self, cat_id: int) -> None:
        """Elimina categoría si no está en uso. 409 si tiene movimientos."""
        cat = self.db.query(CajaCategoria).filter(CajaCategoria.id == cat_id).first()
        if not cat:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Categoría {cat_id} no encontrada",
            )
        mov_count = (
            self.db.query(sa_func.count(CajaMovimiento.id)).filter(CajaMovimiento.categoria_id == cat_id).scalar()
        )
        if mov_count > 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Categoría en uso por {mov_count} movimientos. Desactive en su lugar.",
            )
        self.db.delete(cat)
        self.db.flush()

    # ──────────────────────────────────────────────
    # Tipos de Documento
    # ──────────────────────────────────────────────

    def listar_tipo_documentos(self, incluir_inactivos: bool = False) -> list[CajaTipoDocumento]:
        """Lista tipos de documento."""
        query = self.db.query(CajaTipoDocumento)
        if not incluir_inactivos:
            query = query.filter(CajaTipoDocumento.activo.is_(True))
        return query.order_by(CajaTipoDocumento.nombre).all()

    def crear_tipo_documento(self, nombre: str, descripcion: Optional[str] = None) -> CajaTipoDocumento:
        """Crea tipo de documento. 409 si duplicado."""
        existing = self.db.query(CajaTipoDocumento).filter(CajaTipoDocumento.nombre == nombre).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Ya existe un tipo de documento con el nombre '{nombre}'",
            )
        tipo = CajaTipoDocumento(nombre=nombre, descripcion=descripcion)
        self.db.add(tipo)
        self.db.flush()
        return tipo

    def actualizar_tipo_documento(
        self,
        tipo_id: int,
        nombre: Optional[str] = None,
        descripcion: Optional[str] = None,
        activo: Optional[bool] = None,
    ) -> CajaTipoDocumento:
        """Actualiza tipo de documento."""
        tipo = self.db.query(CajaTipoDocumento).filter(CajaTipoDocumento.id == tipo_id).first()
        if not tipo:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Tipo de documento {tipo_id} no encontrado",
            )
        if nombre is not None:
            tipo.nombre = nombre
        if descripcion is not None:
            tipo.descripcion = descripcion
        if activo is not None:
            tipo.activo = activo
        self.db.flush()
        return tipo

    # ──────────────────────────────────────────────
    # Documentos
    # ──────────────────────────────────────────────

    def crear_documento(
        self,
        tipo_documento_id: int,
        user_id: int,
        numero: Optional[str] = None,
        descripcion: Optional[str] = None,
        fecha_documento: Optional[date] = None,
        monto_documento: Optional[Decimal] = None,
        movimiento_ids: Optional[list[int]] = None,
        entidad_tipo: Optional[str] = None,
        entidad_id: Optional[int] = None,
    ) -> CajaDocumento:
        """Crea documento y opcionalmente lo vincula a movimientos."""
        # Validate tipo exists and is active
        tipo = self.db.query(CajaTipoDocumento).filter(CajaTipoDocumento.id == tipo_documento_id).first()
        if not tipo:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Tipo de documento {tipo_documento_id} no encontrado",
            )
        if not tipo.activo:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Tipo de documento '{tipo.nombre}' está inactivo",
            )

        doc = CajaDocumento(
            tipo_documento_id=tipo_documento_id,
            numero=numero,
            descripcion=descripcion,
            fecha_documento=fecha_documento,
            monto_documento=monto_documento,
            entidad_tipo=entidad_tipo,
            entidad_id=entidad_id,
            registrado_por_id=user_id,
        )
        self.db.add(doc)
        self.db.flush()

        # Link to movements if provided
        if movimiento_ids:
            for mov_id in movimiento_ids:
                mov = self.db.query(CajaMovimiento).filter(CajaMovimiento.id == mov_id).first()
                if not mov:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"Movimiento {mov_id} no encontrado",
                    )
                link = CajaDocumentoMovimiento(
                    documento_id=doc.id,
                    movimiento_id=mov_id,
                )
                self.db.add(link)

            self.db.flush()

        return doc

    def actualizar_documento(
        self,
        doc_id: int,
        tipo_documento_id: Optional[int] = None,
        numero: Optional[str] = None,
        descripcion: Optional[str] = None,
        fecha_documento: Optional[date] = None,
        monto_documento: Optional[Decimal] = None,
    ) -> CajaDocumento:
        """Actualiza metadatos del documento (no links)."""
        doc = self.db.query(CajaDocumento).filter(CajaDocumento.id == doc_id).first()
        if not doc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Documento {doc_id} no encontrado",
            )
        if tipo_documento_id is not None:
            doc.tipo_documento_id = tipo_documento_id
        if numero is not None:
            doc.numero = numero
        if descripcion is not None:
            doc.descripcion = descripcion
        if fecha_documento is not None:
            doc.fecha_documento = fecha_documento
        if monto_documento is not None:
            doc.monto_documento = monto_documento
        self.db.flush()
        return doc

    def eliminar_documento(self, doc_id: int) -> None:
        """Elimina documento solo si no está vinculado a movimientos. 409 si tiene links."""
        doc = (
            self.db.query(CajaDocumento)
            .options(joinedload(CajaDocumento.archivos))
            .filter(CajaDocumento.id == doc_id)
            .first()
        )
        if not doc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Documento {doc_id} no encontrado",
            )
        link_count = (
            self.db.query(sa_func.count(CajaDocumentoMovimiento.id))
            .filter(CajaDocumentoMovimiento.documento_id == doc_id)
            .scalar()
        )
        if link_count > 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Documento vinculado a {link_count} movimientos. Desvincule primero.",
            )
        # Delete files from disk
        for archivo in doc.archivos:
            self._delete_file_from_disk(archivo.ruta_archivo)
        self.db.delete(doc)
        self.db.flush()

    def vincular_documento_movimiento(self, doc_id: int, mov_id: int) -> None:
        """Crea link documento-movimiento. 409 si ya existe."""
        # Validate both exist
        doc = self.db.query(CajaDocumento).filter(CajaDocumento.id == doc_id).first()
        if not doc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Documento {doc_id} no encontrado")
        mov = self.db.query(CajaMovimiento).filter(CajaMovimiento.id == mov_id).first()
        if not mov:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Movimiento {mov_id} no encontrado")

        existing = (
            self.db.query(CajaDocumentoMovimiento)
            .filter(
                CajaDocumentoMovimiento.documento_id == doc_id,
                CajaDocumentoMovimiento.movimiento_id == mov_id,
            )
            .first()
        )
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="El documento ya está vinculado a este movimiento",
            )
        link = CajaDocumentoMovimiento(documento_id=doc_id, movimiento_id=mov_id)
        self.db.add(link)
        self.db.flush()

    def desvincular_documento_movimiento(self, doc_id: int, mov_id: int) -> None:
        """Elimina link documento-movimiento. 404 si no existe."""
        link = (
            self.db.query(CajaDocumentoMovimiento)
            .filter(
                CajaDocumentoMovimiento.documento_id == doc_id,
                CajaDocumentoMovimiento.movimiento_id == mov_id,
            )
            .first()
        )
        if not link:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="El documento no está vinculado a este movimiento",
            )
        self.db.delete(link)
        self.db.flush()

    def documentos_por_movimiento(self, mov_id: int) -> list[CajaDocumento]:
        """Devuelve documentos vinculados a un movimiento con archivos cargados."""
        return (
            self.db.query(CajaDocumento)
            .join(
                CajaDocumentoMovimiento,
                CajaDocumentoMovimiento.documento_id == CajaDocumento.id,
            )
            .options(
                joinedload(CajaDocumento.archivos),
                joinedload(CajaDocumento.tipo_documento),
            )
            .filter(CajaDocumentoMovimiento.movimiento_id == mov_id)
            .all()
        )

    # ──────────────────────────────────────────────
    # Archivos
    # ──────────────────────────────────────────────

    def subir_archivo(
        self,
        doc_id: int,
        file: UploadFile,
        user_id: int,
    ) -> CajaArchivo:
        """
        Sube archivo a documento. Valida tipo y tamaño.
        Almacena en {CAJA_UPLOADS_PATH}/{doc_id}/{uuid}_{filename}.
        """
        # Validate document exists
        doc = self.db.query(CajaDocumento).filter(CajaDocumento.id == doc_id).first()
        if not doc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Documento {doc_id} no encontrado",
            )

        # Validate MIME type
        content_type = file.content_type or ""
        if content_type not in ALLOWED_MIME_TYPES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Tipo de archivo no permitido. Permitidos: PDF, JPEG, PNG, WEBP",
            )

        # Read file content and validate size
        content = file.file.read()
        size = len(content)
        if size > MAX_FILE_SIZE_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="El archivo excede el tamaño máximo de 10MB",
            )

        # Ensure directory exists
        base_path = settings.CAJA_UPLOADS_PATH
        doc_dir = os.path.join(base_path, str(doc_id))
        os.makedirs(doc_dir, exist_ok=True)

        # Save file
        filename = file.filename or "unnamed"
        safe_name = f"{uuid.uuid4().hex}_{filename}"
        file_path = os.path.join(doc_dir, safe_name)
        with open(file_path, "wb") as f:
            f.write(content)

        # Create record
        archivo = CajaArchivo(
            documento_id=doc_id,
            nombre_archivo=filename,
            ruta_archivo=file_path,
            tipo_mime=content_type,
            tamanio_bytes=size,
            registrado_por_id=user_id,
        )
        self.db.add(archivo)
        self.db.flush()
        return archivo

    def descargar_archivo(self, archivo_id: int) -> tuple[str, str]:
        """Retorna (ruta_archivo, tipo_mime) para streaming response."""
        archivo = self.db.query(CajaArchivo).filter(CajaArchivo.id == archivo_id).first()
        if not archivo:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Archivo {archivo_id} no encontrado",
            )
        if not os.path.exists(archivo.ruta_archivo):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="El archivo físico no se encuentra en el servidor",
            )
        return archivo.ruta_archivo, archivo.tipo_mime

    def eliminar_archivo(self, archivo_id: int) -> None:
        """Elimina archivo del disco y de la BD."""
        archivo = self.db.query(CajaArchivo).filter(CajaArchivo.id == archivo_id).first()
        if not archivo:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Archivo {archivo_id} no encontrado",
            )
        self._delete_file_from_disk(archivo.ruta_archivo)
        self.db.delete(archivo)
        self.db.flush()

    def _delete_file_from_disk(self, path: str) -> None:
        """Best-effort delete of a file from disk."""
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError:
            pass  # Log in production, don't fail the DB operation

    # ──────────────────────────────────────────────
    # Helpers — document count per movement
    # ──────────────────────────────────────────────

    def documentos_count_por_movimiento(self, movimiento_ids: list[int]) -> dict[int, int]:
        """Returns {movimiento_id: doc_count} for a batch of movements."""
        if not movimiento_ids:
            return {}
        rows = (
            self.db.query(
                CajaDocumentoMovimiento.movimiento_id,
                sa_func.count(CajaDocumentoMovimiento.id).label("cnt"),
            )
            .filter(CajaDocumentoMovimiento.movimiento_id.in_(movimiento_ids))
            .group_by(CajaDocumentoMovimiento.movimiento_id)
            .all()
        )
        return {row.movimiento_id: row.cnt for row in rows}
