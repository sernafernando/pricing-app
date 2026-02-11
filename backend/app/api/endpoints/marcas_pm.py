from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, tuple_
from pydantic import BaseModel, ConfigDict
from typing import List, Optional, Dict
from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.usuario import Usuario, RolUsuario
from app.models.marca_pm import MarcaPM
from app.models.producto import ProductoERP
from app.models.subcategoria import Subcategoria

router = APIRouter()

# ── Pydantic Models ──────────────────────────────────────────────────────────

class MarcaPMResponse(BaseModel):
    id: int
    marca: str
    categoria: str
    usuario_id: Optional[int]
    usuario_nombre: Optional[str] = None
    usuario_email: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

class MarcaPMUpdate(BaseModel):
    usuario_id: Optional[int] = None

class MarcaPMUpdateResponse(BaseModel):
    mensaje: str
    marca: str
    categoria: str
    usuario_id: Optional[int]

class AsignacionMarcaRequest(BaseModel):
    """Asigna un PM a categorías específicas de una marca."""
    marca: str
    categorias: List[str]
    usuario_id: Optional[int] = None

class AsignacionMarcaResponse(BaseModel):
    mensaje: str
    marca: str
    categorias_actualizadas: int

class SyncMarcasResponse(BaseModel):
    mensaje: str
    pares_nuevos: int

class CategoriasPorMarcaItem(BaseModel):
    marca: str
    categorias: List[str]

class CategoriasPorMarcaResponse(BaseModel):
    data: List[CategoriasPorMarcaItem]
    total_marcas: int
    total_pares: int

class MarcasListResponse(BaseModel):
    marcas: List[str]
    total: int

class MarcasCategoriaItem(BaseModel):
    marca: str
    categoria: str

class MarcasCategoriasListResponse(BaseModel):
    marcas: List[str]
    pares: List[MarcasCategoriaItem]
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


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/marcas-pm", response_model=List[MarcaPMResponse])
async def listar_marcas_pm(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
) -> List[MarcaPMResponse]:
    """
    Lista todas las marcas+categorías con sus PMs asignados.

    Endpoint administrativo que permite ver todos los pares marca-categoría
    del ERP con sus respectivos Product Managers asignados.

    Requiere rol: ADMIN o SUPERADMIN
    """
    if current_user.rol not in [RolUsuario.ADMIN, RolUsuario.SUPERADMIN]:
        raise HTTPException(403, "No tienes permisos")

    marcas = db.query(MarcaPM).options(joinedload(MarcaPM.usuario)).all()

    resultado = []
    for marca in marcas:
        resultado.append({
            "id": marca.id,
            "marca": marca.marca,
            "categoria": marca.categoria,
            "usuario_id": marca.usuario_id,
            "usuario_nombre": marca.usuario.nombre if marca.usuario else None,
            "usuario_email": marca.usuario.email if marca.usuario else None,
        })

    return resultado


@router.get("/marcas-pm/categorias-disponibles", response_model=CategoriasPorMarcaResponse)
async def categorias_disponibles_por_marca(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
) -> CategoriasPorMarcaResponse:
    """
    Devuelve todas las categorías disponibles por marca desde productos_erp.

    Consulta los pares (marca, categoría) distintos que existen en productos.
    Útil para el frontend de GestionPM para saber qué checkboxes mostrar.

    Requiere rol: ADMIN o SUPERADMIN
    """
    if current_user.rol not in [RolUsuario.ADMIN, RolUsuario.SUPERADMIN]:
        raise HTTPException(403, "No tienes permisos")

    pares = db.query(
        ProductoERP.marca,
        ProductoERP.categoria
    ).filter(
        ProductoERP.marca.isnot(None),
        ProductoERP.categoria.isnot(None)
    ).distinct().order_by(
        ProductoERP.marca,
        ProductoERP.categoria
    ).all()

    # Agrupar por marca
    marcas_dict: Dict[str, List[str]] = {}
    for marca, categoria in pares:
        if marca not in marcas_dict:
            marcas_dict[marca] = []
        marcas_dict[marca].append(categoria)

    data = [
        CategoriasPorMarcaItem(marca=marca, categorias=cats)
        for marca, cats in marcas_dict.items()
    ]

    return CategoriasPorMarcaResponse(
        data=data,
        total_marcas=len(marcas_dict),
        total_pares=len(pares)
    )


@router.patch("/marcas-pm/{marca_id}", response_model=MarcaPMUpdateResponse)
async def actualizar_pm_marca(
    marca_id: int,
    datos: MarcaPMUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
) -> MarcaPMUpdateResponse:
    """Asigna o desasigna un PM a un par marca-categoría (solo admin/superadmin)."""
    if current_user.rol not in [RolUsuario.ADMIN, RolUsuario.SUPERADMIN]:
        raise HTTPException(403, "No tienes permisos")

    marca = db.query(MarcaPM).filter(MarcaPM.id == marca_id).first()
    if not marca:
        raise HTTPException(404, "Registro marca-categoría no encontrado")

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
        categoria=marca.categoria,
        usuario_id=marca.usuario_id
    )


@router.put("/marcas-pm/asignar", response_model=AsignacionMarcaResponse)
async def asignar_pm_por_categorias(
    datos: AsignacionMarcaRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
) -> AsignacionMarcaResponse:
    """
    Asigna un PM a categorías específicas de una marca.

    Recibe una marca, una lista de categorías y un usuario_id.
    Actualiza todos los registros marca+categoría correspondientes.
    Útil para la UI de checkboxes donde se seleccionan categorías por marca.

    Requiere rol: ADMIN o SUPERADMIN
    """
    if current_user.rol not in [RolUsuario.ADMIN, RolUsuario.SUPERADMIN]:
        raise HTTPException(403, "No tienes permisos")

    if datos.usuario_id is not None:
        usuario = db.query(Usuario).filter(Usuario.id == datos.usuario_id).first()
        if not usuario:
            raise HTTPException(404, "Usuario no encontrado")

    # Actualizar todos los registros de esa marca con esas categorías
    registros = db.query(MarcaPM).filter(
        func.upper(MarcaPM.marca) == datos.marca.upper(),
        MarcaPM.categoria.in_(datos.categorias)
    ).all()

    if not registros:
        raise HTTPException(404, f"No se encontraron registros para marca '{datos.marca}' con las categorías indicadas")

    for reg in registros:
        reg.usuario_id = datos.usuario_id

    db.commit()

    return AsignacionMarcaResponse(
        mensaje="PM asignado a categorías",
        marca=datos.marca,
        categorias_actualizadas=len(registros)
    )


@router.post("/marcas-pm/sync", response_model=SyncMarcasResponse)
async def sincronizar_marcas(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
) -> SyncMarcasResponse:
    """
    Sincroniza pares marca-categoría nuevos desde productos_erp.

    Consulta pares (marca, categoría) distintos en productos_erp y agrega
    los que aún no existen en marcas_pm con usuario_id=None.

    Requiere rol: ADMIN o SUPERADMIN
    """
    if current_user.rol not in [RolUsuario.ADMIN, RolUsuario.SUPERADMIN]:
        raise HTTPException(403, "No tienes permisos")

    # Obtener todos los pares únicos de productos_erp
    pares_erp = db.query(
        ProductoERP.marca,
        ProductoERP.categoria
    ).filter(
        ProductoERP.marca.isnot(None),
        ProductoERP.categoria.isnot(None)
    ).distinct().all()

    # Obtener todos los pares ya existentes en marcas_pm (en memoria)
    pares_existentes = {
        (m.marca.upper(), m.categoria.upper())
        for m in db.query(MarcaPM.marca, MarcaPM.categoria).all()
    }

    pares_nuevos = 0
    for marca, categoria in pares_erp:
        if (marca.upper(), categoria.upper()) not in pares_existentes:
            db.add(MarcaPM(marca=marca, categoria=categoria, usuario_id=None))
            pares_nuevos += 1

    db.commit()

    return SyncMarcasResponse(
        mensaje="Sincronización completada",
        pares_nuevos=pares_nuevos
    )


@router.get("/pms/marcas", response_model=MarcasCategoriasListResponse)
async def obtener_marcas_por_pms(
    pm_ids: str,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
) -> MarcasCategoriasListResponse:
    """
    Obtiene los pares marca-categoría asignados a uno o más PMs.

    Args:
        pm_ids: IDs de usuarios PM separados por coma (ejemplo: "1,2,3")

    Acceso: Todos los usuarios autenticados
    """
    try:
        pm_ids_list = [int(pm.strip()) for pm in pm_ids.split(',')]
    except ValueError:
        raise HTTPException(400, "IDs de PM inválidos")

    pares = db.query(MarcaPM.marca, MarcaPM.categoria).filter(
        MarcaPM.usuario_id.in_(pm_ids_list)
    ).all()

    pares_list = [
        MarcasCategoriaItem(marca=p[0], categoria=p[1])
        for p in pares
    ]

    # Marcas únicas para retrocompatibilidad con el frontend
    marcas_unicas = sorted(set(p[0] for p in pares))

    return MarcasCategoriasListResponse(
        marcas=marcas_unicas,
        pares=pares_list,
        total=len(pares_list)
    )


@router.get("/pms/subcategorias", response_model=SubcategoriasListResponse)
async def obtener_subcategorias_por_pms(
    pm_ids: str,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
) -> SubcategoriasListResponse:
    """
    Obtiene las subcategorías de productos cuya marca+categoría están
    asignadas a uno o más PMs.

    Args:
        pm_ids: IDs de usuarios PM separados por coma (ejemplo: "1,2,3")

    Acceso: Todos los usuarios autenticados
    """
    try:
        pm_ids_list = [int(pm.strip()) for pm in pm_ids.split(',')]
    except ValueError:
        raise HTTPException(400, "IDs de PM inválidos")

    # Obtener pares marca-categoría asignados a esos PMs
    pares = db.query(MarcaPM.marca, MarcaPM.categoria).filter(
        MarcaPM.usuario_id.in_(pm_ids_list)
    ).all()

    if not pares:
        return SubcategoriasListResponse(subcategorias=[], total=0)

    [p[0] for p in pares]
    [p[1] for p in pares]

    # Obtener subcategorías de productos con esas marcas Y categorías
    subcategorias = db.query(
        Subcategoria.id,
        Subcategoria.nombre
    ).join(
        ProductoERP,
        ProductoERP.subcategoria_id == Subcategoria.id
    ).filter(
        tuple_(
            func.upper(ProductoERP.marca),
            func.upper(ProductoERP.categoria)
        ).in_(
            [(m.upper(), c.upper()) for m, c in pares]
        )
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
) -> List[UsuarioPMResponse]:
    """Lista usuarios disponibles para filtrar como PMs (todos los usuarios)."""
    if solo_con_marcas:
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
