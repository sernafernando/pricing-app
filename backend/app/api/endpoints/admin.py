from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, List
from datetime import date

from app.core.database import get_db
from app.api.deps import get_current_user, get_current_admin
from app.models.usuario import Usuario
from app.models.comision_config import SubcategoriaGrupo, ComisionListaGrupo, GrupoComision
from app.models.configuracion import Configuracion

router = APIRouter()


# ──────────────────────────────────────────────
# Schemas
# ──────────────────────────────────────────────

class SubcategoriaGrupoResponse(BaseModel):
    """Subcategoría con su grupo asignado"""
    id: int
    subcat_id: int
    grupo_id: Optional[int] = None
    nombre_subcategoria: Optional[str] = None
    cat_id: Optional[str] = None
    nombre_categoria: Optional[str] = None
    oculta: bool = False

    model_config = ConfigDict(from_attributes=True)


class AsignarGrupoRequest(BaseModel):
    """Request para asignar grupo a una o varias subcategorías"""
    subcat_ids: List[int] = Field(min_length=1, description="IDs de subcategorías a actualizar")
    grupo_id: Optional[int] = Field(default=None, description="ID del grupo a asignar (null para desasignar)")


class BanlistRequest(BaseModel):
    """Request para ocultar/mostrar subcategorías"""
    subcat_ids: List[int] = Field(min_length=1, description="IDs de subcategorías")
    oculta: bool = Field(description="True para ocultar, False para mostrar")


class GrupoComisionResponse(BaseModel):
    """Grupo de comisión"""
    id: int
    nombre: str
    descripcion: Optional[str] = None
    activo: bool
    cantidad_subcategorias: int = 0

    model_config = ConfigDict(from_attributes=True)


class GrupoComisionCreate(BaseModel):
    """Request para crear un grupo de comisión"""
    nombre: str = Field(min_length=1, max_length=100)
    descripcion: Optional[str] = Field(default=None, max_length=500)


class GrupoComisionUpdate(BaseModel):
    """Request para actualizar un grupo de comisión"""
    nombre: Optional[str] = Field(default=None, min_length=1, max_length=100)
    descripcion: Optional[str] = Field(default=None, max_length=500)
    activo: Optional[bool] = None


# ──────────────────────────────────────────────
# Endpoints legacy de comisiones (mantener backward compat)
# ──────────────────────────────────────────────

@router.get("/admin/comisiones/{grupo_id}")
async def obtener_comisiones_grupo(
    grupo_id: int, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
) -> dict:
    """Obtiene todas las comisiones de un grupo (legacy)"""
    comisiones = db.query(ComisionListaGrupo).filter(ComisionListaGrupo.grupo_id == grupo_id).all()

    return {
        "grupo_id": grupo_id,
        "comisiones": [{"pricelist_id": c.pricelist_id, "comision": c.comision_porcentaje} for c in comisiones],
    }


@router.get("/admin/comision/{pricelist_id}/{grupo_id}")
async def obtener_comision_especifica(
    pricelist_id: int, grupo_id: int, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
) -> dict:
    """Obtiene la comisión para una lista y grupo específicos (legacy)"""
    comision = (
        db.query(ComisionListaGrupo)
        .filter(ComisionListaGrupo.pricelist_id == pricelist_id, ComisionListaGrupo.grupo_id == grupo_id)
        .first()
    )

    if not comision:
        raise HTTPException(404, "Comisión no encontrada")

    return {"pricelist_id": pricelist_id, "grupo_id": grupo_id, "comision": comision.comision_porcentaje}


# ──────────────────────────────────────────────
# Subcategorías <-> Grupos
# ──────────────────────────────────────────────

@router.get("/admin/subcategorias-grupos", response_model=List[SubcategoriaGrupoResponse])
async def listar_subcategorias_grupos(
    categoria: Optional[str] = Query(default=None, description="Filtrar por cat_id"),
    grupo_id: Optional[int] = Query(default=None, description="Filtrar por grupo_id"),
    sin_grupo: Optional[bool] = Query(default=None, description="Solo subcategorías sin grupo asignado"),
    buscar: Optional[str] = Query(default=None, description="Buscar por nombre de subcategoría o categoría"),
    incluir_ocultas: bool = Query(default=False, description="Incluir subcategorías ocultas (banlist)"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> List[SubcategoriaGrupoResponse]:
    """
    Lista todas las subcategorías con su grupo asignado.
    Soporta filtros por categoría, grupo, sin grupo y búsqueda de texto.
    Por defecto oculta las subcategorías en la banlist (oculta=True).
    """
    query = db.query(SubcategoriaGrupo).filter(
        SubcategoriaGrupo.subcat_id.isnot(None),
    ).order_by(
        SubcategoriaGrupo.nombre_categoria,
        SubcategoriaGrupo.nombre_subcategoria,
    )

    if not incluir_ocultas:
        query = query.filter(
            (SubcategoriaGrupo.oculta == False) | (SubcategoriaGrupo.oculta.is_(None))
        )

    if categoria is not None:
        query = query.filter(SubcategoriaGrupo.cat_id == categoria)

    if grupo_id is not None:
        query = query.filter(SubcategoriaGrupo.grupo_id == grupo_id)

    if sin_grupo is True:
        query = query.filter(SubcategoriaGrupo.grupo_id.is_(None))

    if buscar:
        patron = f"%{buscar}%"
        query = query.filter(
            SubcategoriaGrupo.nombre_subcategoria.ilike(patron)
            | SubcategoriaGrupo.nombre_categoria.ilike(patron)
        )

    mappings = query.all()
    return [SubcategoriaGrupoResponse.model_validate(m) for m in mappings]


@router.patch("/admin/subcategorias-grupos/asignar")
async def asignar_grupo_a_subcategorias(
    data: AsignarGrupoRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_admin),
) -> dict:
    """
    Asigna un grupo de comisión a una o varias subcategorías.
    Requiere rol admin. Permite asignación masiva.
    grupo_id null desasigna el grupo.
    """
    # Validar que el grupo existe si se especificó uno
    if data.grupo_id is not None:
        grupo = db.query(GrupoComision).filter(
            GrupoComision.id == data.grupo_id,
            GrupoComision.activo == True,
        ).first()
        if not grupo:
            raise HTTPException(404, f"Grupo de comisión {data.grupo_id} no encontrado o inactivo")

    # Actualizar subcategorías
    actualizadas = (
        db.query(SubcategoriaGrupo)
        .filter(SubcategoriaGrupo.subcat_id.in_(data.subcat_ids))
        .update({SubcategoriaGrupo.grupo_id: data.grupo_id}, synchronize_session="fetch")
    )

    if actualizadas == 0:
        raise HTTPException(404, "No se encontraron subcategorías con los IDs proporcionados")

    db.commit()

    return {
        "mensaje": f"{actualizadas} subcategoría(s) actualizada(s)",
        "actualizadas": actualizadas,
        "grupo_id": data.grupo_id,
    }


@router.patch("/admin/subcategorias-grupos/banlist")
async def toggle_banlist_subcategorias(
    data: BanlistRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_admin),
) -> dict:
    """
    Oculta o muestra subcategorías (banlist).
    Las subcategorías ocultas no aparecen en listados por defecto.
    Requiere rol admin.
    """
    actualizadas = (
        db.query(SubcategoriaGrupo)
        .filter(SubcategoriaGrupo.subcat_id.in_(data.subcat_ids))
        .update({SubcategoriaGrupo.oculta: data.oculta}, synchronize_session="fetch")
    )

    if actualizadas == 0:
        raise HTTPException(404, "No se encontraron subcategorías con los IDs proporcionados")

    db.commit()

    accion = "oculta(s)" if data.oculta else "restaurada(s)"
    return {
        "mensaje": f"{actualizadas} subcategoría(s) {accion}",
        "actualizadas": actualizadas,
        "oculta": data.oculta,
    }


# ──────────────────────────────────────────────
# CRUD Grupos de Comisión
# ──────────────────────────────────────────────

@router.get("/admin/grupos-comision", response_model=List[GrupoComisionResponse])
async def listar_grupos_comision(
    incluir_inactivos: bool = Query(default=False, description="Incluir grupos inactivos"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> List[GrupoComisionResponse]:
    """Lista todos los grupos de comisión con la cantidad de subcategorías asignadas"""
    query = db.query(GrupoComision)

    if not incluir_inactivos:
        query = query.filter(GrupoComision.activo == True)

    grupos = query.order_by(GrupoComision.id).all()

    resultado = []
    for g in grupos:
        cantidad = db.query(SubcategoriaGrupo).filter(SubcategoriaGrupo.grupo_id == g.id).count()
        resultado.append(
            GrupoComisionResponse(
                id=g.id,
                nombre=g.nombre,
                descripcion=g.descripcion,
                activo=g.activo,
                cantidad_subcategorias=cantidad,
            )
        )

    return resultado


@router.post("/admin/grupos-comision", response_model=GrupoComisionResponse, status_code=201)
async def crear_grupo_comision(
    data: GrupoComisionCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_admin),
) -> GrupoComisionResponse:
    """Crea un nuevo grupo de comisión. Requiere rol admin."""
    # Verificar nombre único
    existente = db.query(GrupoComision).filter(GrupoComision.nombre == data.nombre).first()
    if existente:
        raise HTTPException(400, f"Ya existe un grupo con el nombre '{data.nombre}'")

    grupo = GrupoComision(
        nombre=data.nombre,
        descripcion=data.descripcion,
        activo=True,
    )
    db.add(grupo)
    db.commit()
    db.refresh(grupo)

    return GrupoComisionResponse(
        id=grupo.id,
        nombre=grupo.nombre,
        descripcion=grupo.descripcion,
        activo=grupo.activo,
        cantidad_subcategorias=0,
    )


@router.patch("/admin/grupos-comision/{grupo_id}", response_model=GrupoComisionResponse)
async def actualizar_grupo_comision(
    grupo_id: int,
    data: GrupoComisionUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_admin),
) -> GrupoComisionResponse:
    """Actualiza un grupo de comisión existente. Requiere rol admin."""
    grupo = db.query(GrupoComision).filter(GrupoComision.id == grupo_id).first()
    if not grupo:
        raise HTTPException(404, f"Grupo {grupo_id} no encontrado")

    if data.nombre is not None:
        # Verificar nombre único (excluir el grupo actual)
        existente = db.query(GrupoComision).filter(
            GrupoComision.nombre == data.nombre,
            GrupoComision.id != grupo_id,
        ).first()
        if existente:
            raise HTTPException(400, f"Ya existe un grupo con el nombre '{data.nombre}'")
        grupo.nombre = data.nombre

    if data.descripcion is not None:
        grupo.descripcion = data.descripcion

    if data.activo is not None:
        grupo.activo = data.activo

    db.commit()
    db.refresh(grupo)

    cantidad = db.query(SubcategoriaGrupo).filter(SubcategoriaGrupo.grupo_id == grupo.id).count()

    return GrupoComisionResponse(
        id=grupo.id,
        nombre=grupo.nombre,
        descripcion=grupo.descripcion,
        activo=grupo.activo,
        cantidad_subcategorias=cantidad,
    )


@router.get("/admin/subcategorias-categorias")
async def listar_categorias_unicas(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> dict:
    """Lista las categorías únicas disponibles para filtrar subcategorías"""
    categorias = (
        db.query(SubcategoriaGrupo.cat_id, SubcategoriaGrupo.nombre_categoria)
        .filter(SubcategoriaGrupo.cat_id.isnot(None))
        .distinct()
        .order_by(SubcategoriaGrupo.nombre_categoria)
        .all()
    )

    return {
        "categorias": [
            {"cat_id": c.cat_id, "nombre": c.nombre_categoria}
            for c in categorias
        ]
    }


from app.services.bna_scraper import actualizar_tipo_cambio


@router.post("/admin/actualizar-tipo-cambio")
async def actualizar_tc_manual(db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_admin)):
    """Actualiza el tipo de cambio scrapeando el BNA"""
    resultado = await actualizar_tipo_cambio(db)
    return resultado


@router.get("/admin/tipo-cambio-actual")
async def obtener_tc_actual(db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    """Obtiene el tipo de cambio actual"""
    from app.models.tipo_cambio import TipoCambio

    # Buscar primero el de hoy, si no el más reciente
    tc = db.query(TipoCambio).filter(TipoCambio.moneda == "USD", TipoCambio.fecha == date.today()).first()

    if not tc:
        tc = db.query(TipoCambio).filter(TipoCambio.moneda == "USD").order_by(TipoCambio.fecha.desc()).first()

    if not tc:
        raise HTTPException(404, "No hay tipo de cambio disponible")

    return {
        "moneda": "USD",
        "compra": tc.compra,
        "venta": tc.venta,
        "fecha": tc.fecha.isoformat(),
        "actualizado": tc.timestamp_actualizacion.isoformat() if tc.timestamp_actualizacion else None,
    }


# Endpoints de configuración
class ConfiguracionUpdate(BaseModel):
    valor: str


@router.get("/admin/configuracion")
async def obtener_configuraciones(db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_admin)):
    """Obtiene todas las configuraciones"""
    configs = db.query(Configuracion).all()
    return {
        "configuraciones": [
            {"clave": c.clave, "valor": c.valor, "descripcion": c.descripcion, "tipo": c.tipo} for c in configs
        ]
    }


@router.get("/admin/configuracion/{clave}")
async def obtener_configuracion(
    clave: str, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_admin)
):
    """Obtiene una configuración específica"""
    config = db.query(Configuracion).filter(Configuracion.clave == clave).first()

    if not config:
        raise HTTPException(404, f"Configuración '{clave}' no encontrada")

    return {"clave": config.clave, "valor": config.valor, "descripcion": config.descripcion, "tipo": config.tipo}


@router.patch("/admin/configuracion/{clave}")
async def actualizar_configuracion(
    clave: str,
    update: ConfiguracionUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_admin),
):
    """Actualiza una configuración"""
    config = db.query(Configuracion).filter(Configuracion.clave == clave).first()

    if not config:
        raise HTTPException(404, f"Configuración '{clave}' no encontrada")

    config.valor = update.valor
    db.commit()
    db.refresh(config)

    return {"clave": config.clave, "valor": config.valor, "descripcion": config.descripcion, "tipo": config.tipo}
