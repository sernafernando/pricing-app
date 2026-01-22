from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func
from pydantic import BaseModel, ConfigDict
from typing import List, Optional
from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.usuario import Usuario, RolUsuario
from app.models.marca_pm import MarcaPM
from app.models.producto import ProductoERP
from app.models.subcategoria import Subcategoria

router = APIRouter()

class MarcaPMResponse(BaseModel):
    id: int
    marca: str
    usuario_id: Optional[int]
    usuario_nombre: Optional[str] = None
    usuario_email: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

class MarcaPMUpdate(BaseModel):
    usuario_id: Optional[int] = None

class MarcaPMUpdateResponse(BaseModel):
    mensaje: str
    marca: str
    usuario_id: Optional[int]

class SyncMarcasResponse(BaseModel):
    mensaje: str
    marcas_nuevas: int

class MarcasListResponse(BaseModel):
    marcas: List[str]
    total: int

class SubcategoriaItem(BaseModel):
    id: int
    nombre: str

class SubcategoriasListResponse(BaseModel):
    subcategorias: List[SubcategoriaItem]
    total: int

class UsuarioPMResponse(BaseModel):
    id: int
    nombre: str
    email: Optional[str]
    rol: str

    model_config = ConfigDict(from_attributes=True)

@router.get("/marcas-pm", response_model=List[MarcaPMResponse])
async def listar_marcas_pm(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Lista todas las marcas con sus PMs asignados.
    
    Endpoint administrativo que permite ver todas las marcas del ERP
    con sus respectivos Product Managers asignados. Útil para gestionar
    la asignación de responsabilidades por marca.
    
    Requiere rol: ADMIN o SUPERADMIN
    """
    if current_user.rol not in [RolUsuario.ADMIN, RolUsuario.SUPERADMIN]:
        raise HTTPException(403, "No tienes permisos")

    # Usar joinedload para evitar N+1 queries al acceder a marca.usuario
    marcas = db.query(MarcaPM).options(joinedload(MarcaPM.usuario)).all()

    # Enriquecer con datos del usuario
    resultado = []
    for marca in marcas:
        marca_dict = {
            "id": marca.id,
            "marca": marca.marca,
            "usuario_id": marca.usuario_id,
            "usuario_nombre": marca.usuario.nombre if marca.usuario else None,
            "usuario_email": marca.usuario.email if marca.usuario else None
        }
        resultado.append(marca_dict)

    return resultado

@router.patch("/marcas-pm/{marca_id}", response_model=MarcaPMUpdateResponse)
async def actualizar_pm_marca(
    marca_id: int,
    datos: MarcaPMUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Asigna o desasigna un PM a una marca (solo admin/superadmin)"""
    if current_user.rol not in [RolUsuario.ADMIN, RolUsuario.SUPERADMIN]:
        raise HTTPException(403, "No tienes permisos")

    marca = db.query(MarcaPM).filter(MarcaPM.id == marca_id).first()
    if not marca:
        raise HTTPException(404, "Marca no encontrada")

    # Si se asigna un usuario, verificar que existe
    if datos.usuario_id is not None:
        usuario = db.query(Usuario).filter(Usuario.id == datos.usuario_id).first()
        if not usuario:
            raise HTTPException(404, "Usuario no encontrado")

    marca.usuario_id = datos.usuario_id
    db.commit()
    db.refresh(marca)

    return MarcaPMUpdateResponse(
        mensaje="PM actualizado",
        marca=marca.marca,
        usuario_id=marca.usuario_id
    )

@router.post("/marcas-pm/sync", response_model=SyncMarcasResponse)
async def sincronizar_marcas(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Sincroniza marcas nuevas desde productos_erp (solo admin/superadmin)"""
    if current_user.rol not in [RolUsuario.ADMIN, RolUsuario.SUPERADMIN]:
        raise HTTPException(403, "No tienes permisos")

    # Obtener todas las marcas únicas de productos_erp
    marcas_erp = db.query(ProductoERP.marca).distinct().filter(
        ProductoERP.marca.isnot(None)
    ).all()

    # Obtener todas las marcas ya existentes en una sola query (evita N+1)
    marcas_existentes = {m.marca for m in db.query(MarcaPM).all()}

    marcas_nuevas = 0
    for (marca,) in marcas_erp:
        # Verificar si ya existe (comparación en memoria, no DB)
        if marca not in marcas_existentes:
            nueva_marca = MarcaPM(marca=marca, usuario_id=None)
            db.add(nueva_marca)
            marcas_nuevas += 1

    db.commit()

    return SyncMarcasResponse(
        mensaje="Sincronización completada",
        marcas_nuevas=marcas_nuevas
    )

@router.get("/pms/marcas", response_model=MarcasListResponse)
async def obtener_marcas_por_pms(
    pm_ids: str,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Obtiene las marcas asignadas a uno o más PMs.
    
    Endpoint de filtrado que permite obtener las marcas que están bajo
    la responsabilidad de uno o múltiples Product Managers. Útil para
    filtrar productos por PM en el catálogo o reportes.
    
    Args:
        pm_ids: IDs de usuarios PM separados por coma (ejemplo: "1,2,3")
    
    Acceso: Todos los usuarios autenticados
    """
    try:
        pm_ids_list = [int(pm.strip()) for pm in pm_ids.split(',')]
    except ValueError:
        raise HTTPException(400, "IDs de PM inválidos")

    # Obtener marcas asignadas a esos PMs
    marcas = db.query(MarcaPM.marca).filter(
        MarcaPM.usuario_id.in_(pm_ids_list)
    ).all()

    marcas_list = [m[0] for m in marcas]

    return MarcasListResponse(
        marcas=marcas_list,
        total=len(marcas_list)
    )

@router.get("/pms/subcategorias", response_model=SubcategoriasListResponse)
async def obtener_subcategorias_por_pms(
    pm_ids: str,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Obtiene las subcategorías de productos de marcas asignadas a uno o más PMs.
    
    Endpoint de filtrado que permite obtener todas las subcategorías que tienen
    productos de marcas bajo la responsabilidad de uno o múltiples Product Managers.
    Útil para filtros en cascada (PM -> Marca -> Subcategoría) en interfaces de
    catálogo, reportes o dashboards.
    
    Args:
        pm_ids: IDs de usuarios PM separados por coma (ejemplo: "1,2,3")
    
    Acceso: Todos los usuarios autenticados
    """
    try:
        pm_ids_list = [int(pm.strip()) for pm in pm_ids.split(',')]
    except ValueError:
        raise HTTPException(400, "IDs de PM inválidos")

    # Obtener marcas asignadas a esos PMs
    marcas = db.query(MarcaPM.marca).filter(
        MarcaPM.usuario_id.in_(pm_ids_list)
    ).all()

    marcas_list = [m[0] for m in marcas]

    if not marcas_list:
        return SubcategoriasListResponse(
            subcategorias=[],
            total=0
        )

    # Obtener subcategorías de productos con esas marcas
    subcategorias = db.query(
        Subcategoria.id,
        Subcategoria.nombre
    ).join(
        ProductoERP,
        ProductoERP.subcategoria_id == Subcategoria.id
    ).filter(
        func.upper(ProductoERP.marca).in_([m.upper() for m in marcas_list])
    ).distinct().all()

    subcategorias_list = [
        SubcategoriaItem(id=s[0], nombre=s[1])
        for s in subcategorias
    ]

    return SubcategoriasListResponse(
        subcategorias=subcategorias_list,
        total=len(subcategorias_list)
    )

@router.get("/usuarios/pms", response_model=List[UsuarioPMResponse])
async def listar_usuarios_pm(
    solo_con_marcas: bool = False,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Lista usuarios disponibles para filtrar como PMs (todos los usuarios)"""
    # Removido el check de permisos - ahora todos pueden ver los PMs para filtrar

    if solo_con_marcas:
        # Obtener solo usuarios que tienen al menos una marca asignada
        usuarios_con_marcas = db.query(Usuario).join(
            MarcaPM, Usuario.id == MarcaPM.usuario_id
        ).filter(
            Usuario.activo == True
        ).distinct().all()

        return [
            UsuarioPMResponse(
                id=u.id,
                nombre=u.nombre,
                email=u.email,
                rol=u.rol_codigo
            )
            for u in usuarios_con_marcas
        ]
    else:
        # Obtener todos los usuarios activos
        usuarios = db.query(Usuario).filter(Usuario.activo == True).all()

        return [
            UsuarioPMResponse(
                id=u.id,
                nombre=u.nombre,
                email=u.email,
                rol=u.rol_codigo
            )
            for u in usuarios
        ]
