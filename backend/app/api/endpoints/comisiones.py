from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import date, timedelta
from app.core.database import get_db
from app.models.comision_versionada import ComisionVersion, ComisionBase, ComisionAdicionalCuota
from app.models.comision_config import GrupoComision
from app.api.deps import get_current_user
from app.models.usuario import Usuario

router = APIRouter()

# Schemas
class ComisionBaseCreate(BaseModel):
    grupo_id: int
    comision_base: float = Field(ge=0, le=100)

class ComisionAdicionalCreate(BaseModel):
    cuotas: int = Field(ge=3, le=12)
    adicional: float = Field(ge=0, le=100)

class ComisionVersionCreate(BaseModel):
    nombre: str
    descripcion: Optional[str] = None
    fecha_desde: date
    comisiones_base: List[ComisionBaseCreate]
    adicionales_cuota: List[ComisionAdicionalCreate]

class ComisionBaseResponse(BaseModel):
    grupo_id: int
    comision_base: float

class ComisionAdicionalResponse(BaseModel):
    cuotas: int
    adicional: float

class ComisionVersionResponse(BaseModel):
    id: int
    nombre: str
    descripcion: Optional[str]
    fecha_desde: date
    fecha_hasta: Optional[date]
    activo: bool
    comisiones_base: List[ComisionBaseResponse]
    adicionales_cuota: List[ComisionAdicionalResponse]

class ComisionCalculadaResponse(BaseModel):
    grupo_id: int
    lista_4: float
    lista_3_cuotas: float
    lista_6_cuotas: float
    lista_9_cuotas: float
    lista_12_cuotas: float


@router.get("/comisiones/versiones", response_model=List[ComisionVersionResponse])
async def listar_versiones_comisiones(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Lista todas las versiones de comisiones ordenadas por fecha"""
    versiones = db.query(ComisionVersion).order_by(
        ComisionVersion.fecha_desde.desc()
    ).all()

    resultado = []
    for v in versiones:
        comisiones_base = [
            ComisionBaseResponse(grupo_id=cb.grupo_id, comision_base=float(cb.comision_base))
            for cb in v.comisiones_base
        ]
        adicionales = [
            ComisionAdicionalResponse(cuotas=ac.cuotas, adicional=float(ac.adicional))
            for ac in v.adicionales_cuota
        ]

        resultado.append(ComisionVersionResponse(
            id=v.id,
            nombre=v.nombre,
            descripcion=v.descripcion,
            fecha_desde=v.fecha_desde,
            fecha_hasta=v.fecha_hasta,
            activo=v.activo,
            comisiones_base=comisiones_base,
            adicionales_cuota=adicionales
        ))

    return resultado


@router.get("/comisiones/version/{version_id}", response_model=ComisionVersionResponse)
async def obtener_version_comision(
    version_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Obtiene una versión específica de comisiones"""
    version = db.query(ComisionVersion).filter(ComisionVersion.id == version_id).first()

    if not version:
        raise HTTPException(404, "Versión de comisiones no encontrada")

    comisiones_base = [
        ComisionBaseResponse(grupo_id=cb.grupo_id, comision_base=float(cb.comision_base))
        for cb in version.comisiones_base
    ]
    adicionales = [
        ComisionAdicionalResponse(cuotas=ac.cuotas, adicional=float(ac.adicional))
        for ac in version.adicionales_cuota
    ]

    return ComisionVersionResponse(
        id=version.id,
        nombre=version.nombre,
        descripcion=version.descripcion,
        fecha_desde=version.fecha_desde,
        fecha_hasta=version.fecha_hasta,
        activo=version.activo,
        comisiones_base=comisiones_base,
        adicionales_cuota=adicionales
    )


@router.get("/comisiones/vigente", response_model=ComisionVersionResponse)
async def obtener_comisiones_vigentes(
    fecha: Optional[date] = None,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Obtiene la versión de comisiones vigente para una fecha (por defecto hoy)"""
    if not fecha:
        fecha = date.today()

    version = db.query(ComisionVersion).filter(
        and_(
            ComisionVersion.fecha_desde <= fecha,
            or_(
                ComisionVersion.fecha_hasta.is_(None),
                ComisionVersion.fecha_hasta >= fecha
            ),
            ComisionVersion.activo == True
        )
    ).first()

    if not version:
        raise HTTPException(404, f"No hay comisiones vigentes para la fecha {fecha}")

    comisiones_base = [
        ComisionBaseResponse(grupo_id=cb.grupo_id, comision_base=float(cb.comision_base))
        for cb in version.comisiones_base
    ]
    adicionales = [
        ComisionAdicionalResponse(cuotas=ac.cuotas, adicional=float(ac.adicional))
        for ac in version.adicionales_cuota
    ]

    return ComisionVersionResponse(
        id=version.id,
        nombre=version.nombre,
        descripcion=version.descripcion,
        fecha_desde=version.fecha_desde,
        fecha_hasta=version.fecha_hasta,
        activo=version.activo,
        comisiones_base=comisiones_base,
        adicionales_cuota=adicionales
    )


@router.get("/comisiones/calculadas", response_model=List[ComisionCalculadaResponse])
async def obtener_comisiones_calculadas(
    fecha: Optional[date] = None,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Obtiene la matriz completa de comisiones calculadas (base + adicionales) para una fecha"""
    if not fecha:
        fecha = date.today()

    # Obtener versión vigente
    version = db.query(ComisionVersion).filter(
        and_(
            ComisionVersion.fecha_desde <= fecha,
            or_(
                ComisionVersion.fecha_hasta.is_(None),
                ComisionVersion.fecha_hasta >= fecha
            ),
            ComisionVersion.activo == True
        )
    ).first()

    if not version:
        raise HTTPException(404, f"No hay comisiones vigentes para la fecha {fecha}")

    # Crear diccionario de adicionales por cuota
    adicionales = {ac.cuotas: float(ac.adicional) for ac in version.adicionales_cuota}

    # Calcular matriz completa
    resultado = []
    for cb in version.comisiones_base:
        base = float(cb.comision_base)
        resultado.append(ComisionCalculadaResponse(
            grupo_id=cb.grupo_id,
            lista_4=base,
            lista_3_cuotas=base + adicionales.get(3, 0),
            lista_6_cuotas=base + adicionales.get(6, 0),
            lista_9_cuotas=base + adicionales.get(9, 0),
            lista_12_cuotas=base + adicionales.get(12, 0)
        ))

    return resultado


@router.post("/comisiones/nueva-version", response_model=ComisionVersionResponse)
async def crear_nueva_version_comisiones(
    data: ComisionVersionCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Crea una nueva versión de comisiones.
    - Cierra la versión activa actual (fecha_hasta = data.fecha_desde - 1 día)
    - Crea la nueva versión (fecha_desde = data.fecha_desde, activo = True)
    """

    # Verificar que el usuario sea admin
    if current_user.rol_codigo not in ['ADMIN', 'SUPERADMIN']:
        raise HTTPException(403, "No tienes permisos para crear versiones de comisiones")

    # Validar que haya 13 grupos
    if len(data.comisiones_base) != 13:
        raise HTTPException(400, "Deben especificarse comisiones base para los 13 grupos")

    # Validar que haya 4 adicionales (3, 6, 9, 12 cuotas)
    if len(data.adicionales_cuota) != 4:
        raise HTTPException(400, "Deben especificarse 4 adicionales (3, 6, 9, 12 cuotas)")

    cuotas_especificadas = {ac.cuotas for ac in data.adicionales_cuota}
    if cuotas_especificadas != {3, 6, 9, 12}:
        raise HTTPException(400, "Los adicionales deben ser para 3, 6, 9 y 12 cuotas")

    # Cerrar versión activa actual
    version_actual = db.query(ComisionVersion).filter(
        ComisionVersion.activo == True,
        ComisionVersion.fecha_hasta.is_(None)
    ).first()

    if version_actual:
        # Calcular fecha_hasta como un día antes de la nueva fecha_desde
        version_actual.fecha_hasta = data.fecha_desde - timedelta(days=1)
        version_actual.activo = False

    # Crear nueva versión
    nueva_version = ComisionVersion(
        nombre=data.nombre,
        descripcion=data.descripcion,
        fecha_desde=data.fecha_desde,
        fecha_hasta=None,
        activo=True,
        usuario_creacion=current_user.email
    )
    db.add(nueva_version)
    db.flush()  # Para obtener el ID

    # Crear comisiones base
    for cb_data in data.comisiones_base:
        cb = ComisionBase(
            version_id=nueva_version.id,
            grupo_id=cb_data.grupo_id,
            comision_base=cb_data.comision_base
        )
        db.add(cb)

    # Crear adicionales
    for ac_data in data.adicionales_cuota:
        ac = ComisionAdicionalCuota(
            version_id=nueva_version.id,
            cuotas=ac_data.cuotas,
            adicional=ac_data.adicional
        )
        db.add(ac)

    db.commit()
    db.refresh(nueva_version)

    # Preparar respuesta
    comisiones_base = [
        ComisionBaseResponse(grupo_id=cb.grupo_id, comision_base=float(cb.comision_base))
        for cb in nueva_version.comisiones_base
    ]
    adicionales = [
        ComisionAdicionalResponse(cuotas=ac.cuotas, adicional=float(ac.adicional))
        for ac in nueva_version.adicionales_cuota
    ]

    return ComisionVersionResponse(
        id=nueva_version.id,
        nombre=nueva_version.nombre,
        descripcion=nueva_version.descripcion,
        fecha_desde=nueva_version.fecha_desde,
        fecha_hasta=nueva_version.fecha_hasta,
        activo=nueva_version.activo,
        comisiones_base=comisiones_base,
        adicionales_cuota=adicionales
    )


@router.patch("/comisiones/version/{version_id}")
async def actualizar_version_comisiones(
    version_id: int,
    data: ComisionVersionCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Actualiza una versión existente de comisiones.
    Solo se puede editar si es la versión activa actual.
    """
    # Verificar permisos
    if current_user.rol_codigo not in ['ADMIN', 'SUPERADMIN']:
        raise HTTPException(403, "No tienes permisos para editar versiones de comisiones")

    # Obtener versión
    version = db.query(ComisionVersion).filter(ComisionVersion.id == version_id).first()
    if not version:
        raise HTTPException(404, "Versión no encontrada")

    # Solo se puede editar si es la versión activa
    if not version.activo or version.fecha_hasta is not None:
        raise HTTPException(400, "Solo se puede editar la versión activa actual")

    # Validar datos
    if len(data.comisiones_base) != 13:
        raise HTTPException(400, "Deben especificarse comisiones base para los 13 grupos")

    if len(data.adicionales_cuota) != 4:
        raise HTTPException(400, "Deben especificarse 4 adicionales (3, 6, 9, 12 cuotas)")

    cuotas_especificadas = {ac.cuotas for ac in data.adicionales_cuota}
    if cuotas_especificadas != {3, 6, 9, 12}:
        raise HTTPException(400, "Los adicionales deben ser para 3, 6, 9 y 12 cuotas")

    # Actualizar metadatos
    version.nombre = data.nombre
    version.descripcion = data.descripcion
    version.fecha_desde = data.fecha_desde

    # Eliminar comisiones antiguas
    db.query(ComisionBase).filter(ComisionBase.version_id == version_id).delete()
    db.query(ComisionAdicionalCuota).filter(ComisionAdicionalCuota.version_id == version_id).delete()

    # Crear nuevas comisiones
    for cb_data in data.comisiones_base:
        cb = ComisionBase(
            version_id=version_id,
            grupo_id=cb_data.grupo_id,
            comision_base=cb_data.comision_base
        )
        db.add(cb)

    for ac_data in data.adicionales_cuota:
        ac = ComisionAdicionalCuota(
            version_id=version_id,
            cuotas=ac_data.cuotas,
            adicional=ac_data.adicional
        )
        db.add(ac)

    db.commit()
    db.refresh(version)

    # Preparar respuesta
    comisiones_base = [
        ComisionBaseResponse(grupo_id=cb.grupo_id, comision_base=float(cb.comision_base))
        for cb in version.comisiones_base
    ]
    adicionales = [
        ComisionAdicionalResponse(cuotas=ac.cuotas, adicional=float(ac.adicional))
        for ac in version.adicionales_cuota
    ]

    return ComisionVersionResponse(
        id=version.id,
        nombre=version.nombre,
        descripcion=version.descripcion,
        fecha_desde=version.fecha_desde,
        fecha_hasta=version.fecha_hasta,
        activo=version.activo,
        comisiones_base=comisiones_base,
        adicionales_cuota=adicionales
    )


class EliminarVersionRequest(BaseModel):
    motivo: str = Field(min_length=10, max_length=500)


@router.delete("/comisiones/version/{version_id}")
async def eliminar_version_comisiones(
    version_id: int,
    request: EliminarVersionRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Elimina una versión de comisiones.
    Solo se puede eliminar si es la última versión creada y está activa.
    Requiere motivo para auditoría.
    """
    # Verificar permisos
    if current_user.rol_codigo not in ['ADMIN', 'SUPERADMIN']:
        raise HTTPException(403, "No tienes permisos para eliminar versiones de comisiones")

    # Obtener versión
    version = db.query(ComisionVersion).filter(ComisionVersion.id == version_id).first()
    if not version:
        raise HTTPException(404, "Versión no encontrada")

    # Verificar que sea la última versión creada
    ultima_version = db.query(ComisionVersion).order_by(
        ComisionVersion.fecha_creacion.desc()
    ).first()

    if version.id != ultima_version.id:
        raise HTTPException(400, "Solo se puede eliminar la última versión creada")

    # Verificar que esté activa
    if not version.activo:
        raise HTTPException(400, "Solo se puede eliminar una versión activa")

    # Obtener versión anterior para reactivarla
    version_anterior = db.query(ComisionVersion).filter(
        ComisionVersion.id != version_id,
        ComisionVersion.fecha_hasta.isnot(None)
    ).order_by(ComisionVersion.fecha_desde.desc()).first()

    # Registrar en auditoría (usando el campo de descripción como log)
    from datetime import datetime
    log_eliminacion = f"[ELIMINADA {datetime.now().isoformat()}] Usuario: {current_user.email} | Motivo: {request.motivo}"
    version.descripcion = (version.descripcion or "") + "\n" + log_eliminacion

    # Guardar antes de eliminar (para tener el log)
    db.commit()

    # Reactivar versión anterior
    if version_anterior:
        version_anterior.fecha_hasta = None
        version_anterior.activo = True

    # Eliminar versión (cascade eliminará comisiones_base y adicionales_cuota)
    db.delete(version)
    db.commit()

    return {
        "mensaje": "Versión eliminada correctamente",
        "version_reactivada": {
            "id": version_anterior.id,
            "nombre": version_anterior.nombre
        } if version_anterior else None
    }


@router.get("/comisiones/grupos")
async def listar_grupos(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Lista todos los grupos de comisiones disponibles"""
    grupos = db.query(GrupoComision).filter(GrupoComision.activo == True).all()
    return {
        "grupos": [
            {
                "id": g.id,
                "nombre": g.nombre,
                "descripcion": g.descripcion
            }
            for g in grupos
        ]
    }
