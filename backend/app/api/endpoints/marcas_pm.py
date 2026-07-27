from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, tuple_
from sqlalchemy.exc import IntegrityError
from pydantic import BaseModel, ConfigDict
from typing import List, Optional, Dict
from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.usuario import Usuario, RolUsuario
from app.models.marca_pm import MarcaPM
from app.models.marca_sub_pm import MarcaSubPM
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


class SubPMGrantRequest(BaseModel):
    """Payload to grant a sub-PM on a (marca, categoria) pair."""

    marca: str
    categoria: str
    usuario_id: int


class SubPMResponse(BaseModel):
    id: int
    marca: str
    categoria: str
    usuario_id: int
    usuario_nombre: Optional[str] = None
    creado_por: Optional[int] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class ParTitularidadItem(BaseModel):
    id: int
    marca: str
    categoria: str


class MisTitularidadesResponse(BaseModel):
    pares: List[ParTitularidadItem]
    total: int


class GrantsUsuarioResponse(BaseModel):
    pares: List[MarcasCategoriaItem]
    total: int


class ConteoUsuarioItem(BaseModel):
    usuario_id: int
    total: int


class ConteosUsuarioResponse(BaseModel):
    conteos: List[ConteoUsuarioItem]


class BulkSubPMRequest(BaseModel):
    """Desired full set of (marca, categoria) pairs for a user, confined to
    the caller's writable scope."""

    pares: List[MarcasCategoriaItem]


class BulkSubPMResponse(BaseModel):
    otorgados: int
    revocados: int
    total: int


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.get("/marcas-pm", response_model=List[MarcaPMResponse])
def listar_marcas_pm(
    db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
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
        resultado.append(
            {
                "id": marca.id,
                "marca": marca.marca,
                "categoria": marca.categoria,
                "usuario_id": marca.usuario_id,
                "usuario_nombre": marca.usuario.nombre if marca.usuario else None,
                "usuario_email": marca.usuario.email if marca.usuario else None,
            }
        )

    return resultado


@router.get("/marcas-pm/categorias-disponibles", response_model=CategoriasPorMarcaResponse)
def categorias_disponibles_por_marca(
    db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
) -> CategoriasPorMarcaResponse:
    """
    Devuelve todas las categorías disponibles por marca desde productos_erp.

    Consulta los pares (marca, categoría) distintos que existen en productos.
    Útil para el frontend de GestionPM para saber qué checkboxes mostrar.

    Requiere rol: ADMIN o SUPERADMIN
    """
    if current_user.rol not in [RolUsuario.ADMIN, RolUsuario.SUPERADMIN]:
        raise HTTPException(403, "No tienes permisos")

    pares = (
        db.query(ProductoERP.marca, ProductoERP.categoria)
        .filter(ProductoERP.marca.isnot(None), ProductoERP.categoria.isnot(None))
        .distinct()
        .order_by(ProductoERP.marca, ProductoERP.categoria)
        .all()
    )

    # Agrupar por marca
    marcas_dict: Dict[str, List[str]] = {}
    for marca, categoria in pares:
        if marca not in marcas_dict:
            marcas_dict[marca] = []
        marcas_dict[marca].append(categoria)

    data = [CategoriasPorMarcaItem(marca=marca, categorias=cats) for marca, cats in marcas_dict.items()]

    return CategoriasPorMarcaResponse(data=data, total_marcas=len(marcas_dict), total_pares=len(pares))


@router.patch("/marcas-pm/{marca_id}", response_model=MarcaPMUpdateResponse)
def actualizar_pm_marca(
    marca_id: int,
    datos: MarcaPMUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
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
        mensaje="PM actualizado", marca=marca.marca, categoria=marca.categoria, usuario_id=marca.usuario_id
    )


@router.put("/marcas-pm/asignar", response_model=AsignacionMarcaResponse)
def asignar_pm_por_categorias(
    datos: AsignacionMarcaRequest, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
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
    registros = (
        db.query(MarcaPM)
        .filter(func.upper(MarcaPM.marca) == datos.marca.upper(), MarcaPM.categoria.in_(datos.categorias))
        .all()
    )

    if not registros:
        raise HTTPException(404, f"No se encontraron registros para marca '{datos.marca}' con las categorías indicadas")

    for reg in registros:
        reg.usuario_id = datos.usuario_id

    db.commit()

    return AsignacionMarcaResponse(
        mensaje="PM asignado a categorías", marca=datos.marca, categorias_actualizadas=len(registros)
    )


@router.post("/marcas-pm/sync", response_model=SyncMarcasResponse)
def sincronizar_marcas(
    db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
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
    pares_erp = (
        db.query(ProductoERP.marca, ProductoERP.categoria)
        .filter(ProductoERP.marca.isnot(None), ProductoERP.categoria.isnot(None))
        .distinct()
        .all()
    )

    # Obtener todos los pares ya existentes en marcas_pm (en memoria)
    pares_existentes = {
        (m.marca.upper(), m.categoria.upper()) for m in db.query(MarcaPM.marca, MarcaPM.categoria).all()
    }

    pares_nuevos = 0
    for marca, categoria in pares_erp:
        if (marca.upper(), categoria.upper()) not in pares_existentes:
            db.add(MarcaPM(marca=marca, categoria=categoria, usuario_id=None))
            pares_nuevos += 1

    db.commit()

    return SyncMarcasResponse(mensaje="Sincronización completada", pares_nuevos=pares_nuevos)


@router.get("/pms/marcas", response_model=MarcasCategoriasListResponse)
def obtener_marcas_por_pms(
    pm_ids: str, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
) -> MarcasCategoriasListResponse:
    """
    Obtiene los pares marca-categoría asignados a uno o más PMs.

    Args:
        pm_ids: IDs de usuarios PM separados por coma (ejemplo: "1,2,3")

    Acceso: Todos los usuarios autenticados
    """
    try:
        pm_ids_list = [int(pm.strip()) for pm in pm_ids.split(",")]
    except ValueError:
        raise HTTPException(400, "IDs de PM inválidos")

    pares = db.query(MarcaPM.marca, MarcaPM.categoria).filter(MarcaPM.usuario_id.in_(pm_ids_list)).all()

    pares_list = [MarcasCategoriaItem(marca=p[0], categoria=p[1]) for p in pares]

    # Marcas únicas para retrocompatibilidad con el frontend
    marcas_unicas = sorted(set(p[0] for p in pares))

    return MarcasCategoriasListResponse(marcas=marcas_unicas, pares=pares_list, total=len(pares_list))


@router.get("/pms/subcategorias", response_model=SubcategoriasListResponse)
def obtener_subcategorias_por_pms(
    pm_ids: str, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
) -> SubcategoriasListResponse:
    """
    Obtiene las subcategorías de productos cuya marca+categoría están
    asignadas a uno o más PMs.

    Args:
        pm_ids: IDs de usuarios PM separados por coma (ejemplo: "1,2,3")

    Acceso: Todos los usuarios autenticados
    """
    try:
        pm_ids_list = [int(pm.strip()) for pm in pm_ids.split(",")]
    except ValueError:
        raise HTTPException(400, "IDs de PM inválidos")

    # Obtener pares marca-categoría asignados a esos PMs
    pares = db.query(MarcaPM.marca, MarcaPM.categoria).filter(MarcaPM.usuario_id.in_(pm_ids_list)).all()

    if not pares:
        return SubcategoriasListResponse(subcategorias=[], total=0)

    [p[0] for p in pares]
    [p[1] for p in pares]

    # Obtener subcategorías de productos con esas marcas Y categorías
    subcategorias = (
        db.query(Subcategoria.id, Subcategoria.nombre)
        .join(ProductoERP, ProductoERP.subcategoria_id == Subcategoria.id)
        .filter(
            tuple_(func.upper(ProductoERP.marca), func.upper(ProductoERP.categoria)).in_(
                [(m.upper(), c.upper()) for m, c in pares]
            )
        )
        .distinct()
        .all()
    )

    subcategorias_list = [SubcategoriaItem(id=s[0], nombre=s[1]) for s in subcategorias]

    return SubcategoriasListResponse(subcategorias=subcategorias_list, total=len(subcategorias_list))


@router.get("/usuarios/pms", response_model=List[UsuarioPMResponse])
def listar_usuarios_pm(
    solo_con_marcas: bool = False, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
) -> List[UsuarioPMResponse]:
    """Lista usuarios disponibles para filtrar como PMs (todos los usuarios)."""
    if solo_con_marcas:
        usuarios_con_marcas = (
            db.query(Usuario)
            .join(MarcaPM, Usuario.id == MarcaPM.usuario_id)
            .filter(Usuario.activo == True)
            .distinct()
            .all()
        )

        return [
            UsuarioPMResponse(id=u.id, nombre=u.nombre, email=u.email, rol=u.rol_codigo) for u in usuarios_con_marcas
        ]
    else:
        usuarios = db.query(Usuario).filter(Usuario.activo == True).all()

        return [UsuarioPMResponse(id=u.id, nombre=u.nombre, email=u.email, rol=u.rol_codigo) for u in usuarios]


# ── Sub-PM CRUD (design D3: admin role gate OR data-scoped titular guard) ────


def _resolve_writable_pairs(db: Session, user: Usuario) -> set:
    """Resolve the caller's writable (marca, categoria) pairs ONCE.

    Admin/superadmin: ALL pairs in `marcas_pm`, including the untitled ones
    (usuario_id IS NULL) — those are admin-only manageable.
    Titular: only the pairs where they are the current titular
    (marcas_pm.usuario_id == user.id).

    Matching is on the exact (marca, categoria) string tuple — case-SENSITIVE,
    consistent with `_require_titular_or_admin` below. This intentionally
    diverges from `sincronizar_marcas`'s case-insensitive `.upper()` dedup
    (see :296-312 or nearby) — that mismatch is pre-existing and out of scope
    here; fixing it belongs in its own change.

    Returns:
        A set of (marca, categoria) tuples the caller may read/grant on.
    """
    query = db.query(MarcaPM.marca, MarcaPM.categoria)
    if user.rol not in (RolUsuario.ADMIN, RolUsuario.SUPERADMIN):
        query = query.filter(MarcaPM.usuario_id == user.id)

    return {(marca, categoria) for marca, categoria in query.all()}


def _require_titular_or_admin(db: Session, marca: str, categoria: str, user: Usuario) -> None:
    """Authorize a sub-PM write/read on a (marca, categoria) pair.

    Admin/superadmin roles always pass. Otherwise the caller MUST be the
    current titular of that exact pair (marcas_pm.usuario_id == user.id).
    Re-verified on every call (never cached from grant time) — a titular
    reassigned away from the pair loses access on their very next request.
    A pair with no titular (usuario_id IS NULL) is admin-only manageable.

    Raises:
        HTTPException(404): the (marca, categoria) pair does not exist.
        HTTPException(403): caller is neither admin nor the pair's titular.
    """
    if user.rol in (RolUsuario.ADMIN, RolUsuario.SUPERADMIN):
        par = db.query(MarcaPM).filter(MarcaPM.marca == marca, MarcaPM.categoria == categoria).first()
        if not par:
            raise HTTPException(404, "Par marca-categoría no encontrado")
        return

    par = db.query(MarcaPM).filter(MarcaPM.marca == marca, MarcaPM.categoria == categoria).first()
    if not par:
        raise HTTPException(404, "Par marca-categoría no encontrado")

    if par.usuario_id != user.id:
        raise HTTPException(403, "No tienes permisos sobre este par marca-categoría")


@router.get("/marcas-pm/mis-titularidades", response_model=MisTitularidadesResponse)
def mis_titularidades(
    db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
) -> MisTitularidadesResponse:
    """
    Pares (marca, categoria) de los que el usuario actual es TITULAR.

    Estrictamente titular-only (sourced from `marcas_pm`), NUNCA UNION'd con
    `marca_sub_pm` — este endpoint alimenta la superficie de gestión del
    frontend (PR3); mezclar pares delegados aquí filtraría gestión de pares
    ajenos al titular real.
    """
    pares = db.query(MarcaPM).filter(MarcaPM.usuario_id == current_user.id).all()
    items = [ParTitularidadItem(id=p.id, marca=p.marca, categoria=p.categoria) for p in pares]
    return MisTitularidadesResponse(pares=items, total=len(items))


@router.get("/marcas-pm/sub-pms", response_model=List[SubPMResponse])
def listar_sub_pms(
    marca: str,
    categoria: str,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> List[SubPMResponse]:
    """
    Lista los sub-PMs delegados de un par (marca, categoria).

    Requiere ser el titular del par o tener rol ADMIN/SUPERADMIN.
    """
    _require_titular_or_admin(db, marca, categoria, current_user)

    grants = (
        db.query(MarcaSubPM)
        .options(joinedload(MarcaSubPM.usuario))
        .filter(MarcaSubPM.marca == marca, MarcaSubPM.categoria == categoria)
        .all()
    )

    return [
        SubPMResponse(
            id=g.id,
            marca=g.marca,
            categoria=g.categoria,
            usuario_id=g.usuario_id,
            usuario_nombre=g.usuario.nombre if g.usuario else None,
            creado_por=g.creado_por,
            created_at=g.created_at,
        )
        for g in grants
    ]


@router.post("/marcas-pm/sub-pms", response_model=SubPMResponse, status_code=201)
def crear_sub_pm(
    datos: SubPMGrantRequest,
    response: Response,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> SubPMResponse:
    """
    Otorga un grant de sub-PM sobre un par (marca, categoria) a un usuario.

    Requiere ser el titular del par o tener rol ADMIN/SUPERADMIN. Idempotente
    ante grants duplicados (devuelve el existente con 200 en vez de fallar
    por la unique constraint). Rechaza auto-grant del titular a sí mismo y
    grants a usuarios inactivos.
    """
    _require_titular_or_admin(db, datos.marca, datos.categoria, current_user)

    par = db.query(MarcaPM).filter(MarcaPM.marca == datos.marca, MarcaPM.categoria == datos.categoria).first()
    if par is not None and par.usuario_id == datos.usuario_id:
        raise HTTPException(400, "El titular ya tiene acceso total; no puede auto-otorgarse como sub-PM")

    usuario = db.query(Usuario).filter(Usuario.id == datos.usuario_id).first()
    if not usuario:
        raise HTTPException(404, "Usuario no encontrado")
    if not usuario.activo:
        raise HTTPException(400, "No se puede otorgar sub-PM a un usuario inactivo")

    existente = (
        db.query(MarcaSubPM)
        .filter(
            MarcaSubPM.marca == datos.marca,
            MarcaSubPM.categoria == datos.categoria,
            MarcaSubPM.usuario_id == datos.usuario_id,
        )
        .first()
    )
    if existente:
        # Idempotent: an existing grant returns 200 (not the default 201) so a
        # duplicate POST is a no-op success instead of a unique-constraint 500.
        # Serialization still flows through the declared `response_model`.
        response.status_code = 200
        return SubPMResponse(
            id=existente.id,
            marca=existente.marca,
            categoria=existente.categoria,
            usuario_id=existente.usuario_id,
            usuario_nombre=usuario.nombre,
            creado_por=existente.creado_por,
            created_at=existente.created_at,
        )

    grant = MarcaSubPM(
        marca=datos.marca,
        categoria=datos.categoria,
        usuario_id=datos.usuario_id,
        creado_por=current_user.id,
    )
    db.add(grant)
    db.commit()
    db.refresh(grant)

    return SubPMResponse(
        id=grant.id,
        marca=grant.marca,
        categoria=grant.categoria,
        usuario_id=grant.usuario_id,
        usuario_nombre=usuario.nombre,
        creado_por=grant.creado_por,
        created_at=grant.created_at,
    )


@router.delete("/marcas-pm/sub-pms/{sub_pm_id}", status_code=204)
def revocar_sub_pm(
    sub_pm_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> None:
    """
    Revoca un grant de sub-PM.

    Ownership se re-verifica contra la titularidad ACTUAL del par (no la
    vigente al momento del grant): si el titular fue reasignado, ya no puede
    revocar sub-PMs de ese par salvo que sea admin.
    """
    grant = db.query(MarcaSubPM).filter(MarcaSubPM.id == sub_pm_id).first()
    if not grant:
        raise HTTPException(404, "Grant de sub-PM no encontrado")

    _require_titular_or_admin(db, grant.marca, grant.categoria, current_user)

    db.delete(grant)
    db.commit()
    return None


# ── Bulk assignment reads (Slice 1 of sub-pm-bulk-assignment) ───────────────


@router.get("/marcas-pm/sub-pms/usuario/{usuario_id}", response_model=GrantsUsuarioResponse)
def grants_de_usuario(
    usuario_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> GrantsUsuarioResponse:
    """
    Pares (marca, categoria) actualmente delegados a `usuario_id`, acotados
    al scope writable del caller (mismo authz que la resolución en
    `_resolve_writable_pairs`). Sirve para pre-marcar la tabla de pares al
    elegir un usuario en la asignación masiva.

    Un par sin titular (usuario_id IS NULL) sólo aparece si el caller es
    admin/superadmin — un titular no tiene scope sobre pares sin titular,
    por lo que esos grants quedan invisibles para él (no 403: se filtra el
    resultado, no se rechaza la request, ya que el endpoint lee el scope del
    CALLER, no la existencia de un par puntual).

    Raises:
        HTTPException(404): `usuario_id` no existe.
    """
    usuario = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if not usuario:
        raise HTTPException(404, "Usuario no encontrado")

    writable_pairs = _resolve_writable_pairs(db, current_user)

    grants = db.query(MarcaSubPM.marca, MarcaSubPM.categoria).filter(MarcaSubPM.usuario_id == usuario_id).all()

    items = [
        MarcasCategoriaItem(marca=marca, categoria=categoria)
        for marca, categoria in grants
        if (marca, categoria) in writable_pairs
    ]
    return GrantsUsuarioResponse(pares=items, total=len(items))


@router.get("/marcas-pm/sub-pms/conteos", response_model=ConteosUsuarioResponse)
def conteos_sub_pms(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> ConteosUsuarioResponse:
    """
    Conteo agregado de grants por usuario, acotado al scope writable del
    caller, para el contador del picker ("Juan Pérez (12)").

    Una sola query agrupada por usuario_id — NUNCA una query por usuario del
    picker. Un titular sólo ve conteos de grants sobre pares que puede
    gestionar; grants sobre pares fuera de su scope no suman a nadie desde
    su perspectiva.
    """
    writable_pairs = _resolve_writable_pairs(db, current_user)
    if not writable_pairs:
        return ConteosUsuarioResponse(conteos=[])

    marcas = {marca for marca, _ in writable_pairs}
    categorias = {categoria for _, categoria in writable_pairs}

    filas = (
        db.query(MarcaSubPM.marca, MarcaSubPM.categoria, MarcaSubPM.usuario_id, func.count(MarcaSubPM.id))
        .filter(MarcaSubPM.marca.in_(marcas), MarcaSubPM.categoria.in_(categorias))
        .group_by(MarcaSubPM.marca, MarcaSubPM.categoria, MarcaSubPM.usuario_id)
        .all()
    )

    conteos: Dict[int, int] = {}
    for marca, categoria, usuario_id, total in filas:
        if (marca, categoria) not in writable_pairs:
            continue
        conteos[usuario_id] = conteos.get(usuario_id, 0) + total

    items = [ConteoUsuarioItem(usuario_id=uid, total=total) for uid, total in conteos.items()]
    return ConteosUsuarioResponse(conteos=items)


# ── Bulk assignment write (Slice 2 of sub-pm-bulk-assignment) ───────────────


@router.put("/marcas-pm/sub-pms/usuario/{usuario_id}", response_model=BulkSubPMResponse)
def asignar_sub_pms_bulk(
    usuario_id: int,
    datos: BulkSubPMRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> BulkSubPMResponse:
    """
    Reemplaza el set completo de sub-PM grants de `usuario_id` dentro del
    scope writable del caller por el `pares` solicitado (desired-set).

    FAIL-CLOSED, todo-o-nada: si CUALQUIER par solicitado está fuera del
    scope writable del caller o no existe en `marcas_pm`, no se aplica
    ningún cambio y se responde 403 con `pares_rechazados`. El diff
    (otorgar/revocar) se calcula únicamente contra los grants existentes
    QUE CAEN dentro del scope writable del caller — un grant sobre un par
    fuera de ese scope es invisible para esta request y sobrevive intacto,
    incluso si el `usuario_id` objetivo lo tiene.

    Idempotente: guardar el mismo set no modifica nada (0 otorgados, 0
    revocados). Concurrencia: ante una violación de la unique constraint
    (marca, categoria, usuario_id) entre la lectura de `existentes` y el
    flush, se revierte la transacción COMPLETA y se responde 409 — no se usa
    `ON CONFLICT DO NOTHING` porque CI corre SQLite y producción Postgres,
    lo que dejaría un camino específico de dialecto sin testear.

    Raises:
        HTTPException(404): `usuario_id` no existe.
        HTTPException(400): auto-grant del titular a sí mismo, o usuario
            objetivo inactivo.
        HTTPException(403): algún par solicitado está fuera de scope o no
            existe — no se aplica nada.
        HTTPException(409): conflicto de concurrencia detectado al aplicar
            — no se aplica nada.
    """
    usuario = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if not usuario:
        raise HTTPException(404, "Usuario no encontrado")

    if usuario_id == current_user.id:
        raise HTTPException(400, "El titular ya tiene acceso total; no puede auto-otorgarse como sub-PM")
    if not usuario.activo:
        raise HTTPException(400, "No se puede otorgar sub-PM a un usuario inactivo")

    writable_pairs = _resolve_writable_pairs(db, current_user)

    desired = {(p.marca, p.categoria) for p in datos.pares}
    rechazados = sorted(desired - writable_pairs)
    if rechazados:
        raise HTTPException(
            403,
            {
                "mensaje": "Uno o más pares están fuera de tu scope o no existen",
                "pares_rechazados": [{"marca": m, "categoria": c} for m, c in rechazados],
            },
        )

    existentes_rows = (
        db.query(MarcaSubPM.marca, MarcaSubPM.categoria)
        .filter(MarcaSubPM.usuario_id == usuario_id, tuple_(MarcaSubPM.marca, MarcaSubPM.categoria).in_(writable_pairs))
        .all()
    )
    existentes = {(marca, categoria) for marca, categoria in existentes_rows}

    a_otorgar = desired - existentes
    a_revocar = existentes - desired

    try:
        if a_revocar:
            db.query(MarcaSubPM).filter(
                MarcaSubPM.usuario_id == usuario_id,
                tuple_(MarcaSubPM.marca, MarcaSubPM.categoria).in_(a_revocar),
            ).delete(synchronize_session=False)

        for marca, categoria in a_otorgar:
            db.add(
                MarcaSubPM(
                    marca=marca,
                    categoria=categoria,
                    usuario_id=usuario_id,
                    creado_por=current_user.id,
                )
            )

        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Conflicto de concurrencia al aplicar los cambios; reintentá")

    return BulkSubPMResponse(otorgados=len(a_otorgar), revocados=len(a_revocar), total=len(desired))
