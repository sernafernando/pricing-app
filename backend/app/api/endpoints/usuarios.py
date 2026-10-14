from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, ConfigDict, EmailStr
from typing import List, Optional
from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.usuario import Usuario
from app.models.rol import Rol
from app.core.security import get_password_hash
from app.services.roles_service import ConflictoRolesAdicionales, RolesService

router = APIRouter()


class UsuarioCreate(BaseModel):
    username: str
    email: Optional[EmailStr] = None
    nombre: str
    password: str
    rol: str = "AUDITOR"


class UsuarioUpdate(BaseModel):
    username: Optional[str] = None
    email: Optional[str] = None
    nombre: Optional[str] = None
    activo: Optional[bool] = None
    rol: Optional[str] = None


class PasswordUpdate(BaseModel):
    nueva_password: str


class UsuarioResponse(BaseModel):
    id: int
    username: str
    email: Optional[str]
    nombre: str
    rol: str  # Se llena desde rol_codigo property del modelo
    activo: bool

    model_config = ConfigDict(from_attributes=True)

    @staticmethod
    def model_validate(obj):
        """Custom validation para usar rol_codigo cuando rol es None"""
        data = {
            "id": obj.id,
            "username": obj.username,
            "email": obj.email,
            "nombre": obj.nombre,
            "rol": obj.rol_codigo,  # Usar property rol_codigo en lugar del enum
            "activo": obj.activo,
        }
        return UsuarioResponse(**data)


@router.get("/usuarios", response_model=List[UsuarioResponse])
def listar_usuarios(db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    """Lista todos los usuarios (solo admin)"""
    if current_user.rol_codigo not in ["ADMIN", "SUPERADMIN"]:
        raise HTTPException(403, "No tienes permisos")

    usuarios = db.query(Usuario).all()
    return [UsuarioResponse.model_validate(u) for u in usuarios]


@router.post("/usuarios", response_model=UsuarioResponse)
def crear_usuario(
    usuario: UsuarioCreate, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
):
    """Crea un nuevo usuario (solo admin)"""
    if current_user.rol_codigo not in ["ADMIN", "SUPERADMIN"]:
        raise HTTPException(403, "No tienes permisos")

    # Verificar si el username ya existe
    existe_username = db.query(Usuario).filter(Usuario.username == usuario.username).first()
    if existe_username:
        raise HTTPException(400, "El username ya está registrado")

    # Verificar si el email ya existe (si fue proporcionado)
    if usuario.email:
        existe_email = db.query(Usuario).filter(Usuario.email == usuario.email).first()
        if existe_email:
            raise HTTPException(400, "El email ya está registrado")

    # Validar longitud mínima de password
    if len(usuario.password) < 8:
        raise HTTPException(400, "La contraseña debe tener al menos 8 caracteres")

    # Buscar el rol por código para obtener rol_id
    rol_obj = db.query(Rol).filter(Rol.codigo == usuario.rol.upper()).first()
    if not rol_obj:
        raise HTTPException(400, f"Rol '{usuario.rol}' no existe")

    # Crear usuario (rol enum deprecado, usar solo rol_id)
    nuevo_usuario = Usuario(
        username=usuario.username,
        email=usuario.email,
        nombre=usuario.nombre,
        password_hash=get_password_hash(usuario.password),
        rol=None,  # Deprecado, usar rol_id
        rol_id=rol_obj.id,
        auth_provider="local",
        activo=True,
    )

    db.add(nuevo_usuario)
    db.commit()
    db.refresh(nuevo_usuario)

    return UsuarioResponse.model_validate(nuevo_usuario)


@router.patch("/usuarios/{usuario_id}", response_model=UsuarioResponse)
def actualizar_usuario(
    usuario_id: int,
    datos: UsuarioUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Actualiza un usuario (solo admin)"""
    if current_user.rol_codigo not in ["ADMIN", "SUPERADMIN"]:
        raise HTTPException(403, "No tienes permisos")

    usuario = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if not usuario:
        raise HTTPException(404, "Usuario no encontrado")

    # PROTECCIÓN: Solo superadmin puede modificar a otro superadmin
    if usuario.rol_codigo == "SUPERADMIN" and current_user.rol_codigo != "SUPERADMIN":
        raise HTTPException(403, "No puedes modificar un superadministrador")

    # No permitir desactivarse a sí mismo
    if usuario.id == current_user.id and datos.activo == False:
        raise HTTPException(400, "No puedes desactivarte a ti mismo")

    # No permitir quitarse el rol de superadmin a sí mismo
    if usuario.id == current_user.id and usuario.rol_codigo == "SUPERADMIN" and datos.rol and datos.rol != "SUPERADMIN":
        raise HTTPException(400, "No puedes quitarte el rol de superadmin")

    if datos.activo is not None:
        usuario.activo = datos.activo

    if datos.rol is not None:
        # Buscar el rol por código para obtener rol_id
        rol_obj = db.query(Rol).filter(Rol.codigo == datos.rol.upper()).first()
        if not rol_obj:
            raise HTTPException(400, f"Rol '{datos.rol}' no existe")
        usuario.rol = None  # Deprecado, usar rol_id
        usuario.rol_id = rol_obj.id
        # Si el nuevo rol principal estaba como adicional, deja de serlo
        RolesService(db).quitar_rol_adicional_redundante(usuario.id, rol_obj.id)

    if datos.username is not None:
        # Verificar que el username no esté en uso por otro usuario
        existing = db.query(Usuario).filter(Usuario.username == datos.username, Usuario.id != usuario_id).first()
        if existing:
            raise HTTPException(400, "El username ya está en uso")
        usuario.username = datos.username

    if datos.email is not None:
        # Verificar que el email no esté en uso por otro usuario (si se proporciona)
        if datos.email:
            existing = db.query(Usuario).filter(Usuario.email == datos.email, Usuario.id != usuario_id).first()
            if existing:
                raise HTTPException(400, "El email ya está en uso")
        usuario.email = datos.email

    if datos.nombre is not None:
        usuario.nombre = datos.nombre

    db.commit()
    db.refresh(usuario)

    return UsuarioResponse.model_validate(usuario)


@router.patch("/usuarios/{usuario_id}/password")
def cambiar_password_usuario(
    usuario_id: int,
    datos: PasswordUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Cambia el password de un usuario (solo admin)"""
    if current_user.rol_codigo not in ["ADMIN", "SUPERADMIN"]:
        raise HTTPException(403, "No tienes permisos")

    usuario = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if not usuario:
        raise HTTPException(404, "Usuario no encontrado")

    # Validar longitud mínima
    if len(datos.nueva_password) < 8:
        raise HTTPException(400, "La contraseña debe tener al menos 8 caracteres")

    # PROTECCIÓN: Solo superadmin puede cambiar password de otro superadmin
    if usuario.rol_codigo == "SUPERADMIN" and current_user.rol_codigo != "SUPERADMIN":
        raise HTTPException(403, "No puedes cambiar el password de un superadministrador")

    # Cambiar password
    usuario.password_hash = get_password_hash(datos.nueva_password)
    db.commit()

    return {"mensaje": "Password actualizado correctamente"}


@router.delete("/usuarios/{usuario_id}")
def eliminar_usuario(usuario_id: int, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    """Elimina un usuario (solo admin)"""
    if current_user.rol_codigo not in ["ADMIN", "SUPERADMIN"]:
        raise HTTPException(403, "No tienes permisos")

    usuario = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if not usuario:
        raise HTTPException(404, "Usuario no encontrado")

    # PROTECCIÓN: No se puede eliminar un superadmin
    if usuario.rol == "SUPERADMIN":
        raise HTTPException(403, "No puedes eliminar un superadministrador")

    # No permitir eliminarse a sí mismo
    if usuario.id == current_user.id:
        raise HTTPException(400, "No puedes eliminarte a ti mismo")

    db.delete(usuario)
    db.commit()

    return {"message": "Usuario eliminado"}


# =============================================================================
# ROLES ADICIONALES (solo permisos; el rol principal decide la identidad)
# =============================================================================


class RolResumen(BaseModel):
    id: int
    codigo: str
    nombre: str

    model_config = ConfigDict(from_attributes=True)


class RolesAdicionalesResponse(BaseModel):
    usuario_id: int
    rol_principal: Optional[RolResumen]
    roles_adicionales: List[RolResumen]


class RolesAdicionalesUpdate(BaseModel):
    rol_ids: List[int]


def _usuario_para_roles_adicionales(db: Session, usuario_id: int, current_user: Usuario) -> Usuario:
    """Mismo guard que asignar el rol principal (PATCH /usuarios/{id}): rol principal
    ADMIN o SUPERADMIN, y solo un SUPERADMIN toca a otro SUPERADMIN."""
    if current_user.rol_codigo not in ["ADMIN", "SUPERADMIN"]:
        raise HTTPException(403, "No tienes permisos")

    usuario = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if not usuario:
        raise HTTPException(404, "Usuario no encontrado")

    if usuario.rol_codigo == "SUPERADMIN" and current_user.rol_codigo != "SUPERADMIN":
        raise HTTPException(403, "No puedes modificar un superadministrador")

    return usuario


def _roles_adicionales_response(usuario: Usuario, roles: List[Rol]) -> RolesAdicionalesResponse:
    return RolesAdicionalesResponse(
        usuario_id=usuario.id,
        rol_principal=RolResumen.model_validate(usuario.rol_obj) if usuario.rol_obj else None,
        roles_adicionales=[RolResumen.model_validate(r) for r in roles],
    )


@router.get("/usuarios/{usuario_id}/roles-adicionales", response_model=RolesAdicionalesResponse)
def obtener_roles_adicionales(
    usuario_id: int, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
):
    """Rol principal y roles adicionales de un usuario (los adicionales solo suman permisos)"""
    usuario = _usuario_para_roles_adicionales(db, usuario_id, current_user)
    return _roles_adicionales_response(usuario, RolesService(db).obtener_roles_adicionales_usuario(usuario.id))


@router.put("/usuarios/{usuario_id}/roles-adicionales", response_model=RolesAdicionalesResponse)
def reemplazar_roles_adicionales(
    usuario_id: int,
    datos: RolesAdicionalesUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """
    Reemplaza los roles adicionales de un usuario. Un rol adicional suma sus permisos base;
    no se acepta SUPERADMIN ni el rol principal del usuario (400). Un reemplazo concurrente
    que choca con otro devuelve 409.
    """
    usuario = _usuario_para_roles_adicionales(db, usuario_id, current_user)
    try:
        roles = RolesService(db).set_roles_adicionales_usuario(
            usuario.id, datos.rol_ids, otorgado_por_id=current_user.id
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except ConflictoRolesAdicionales as e:
        raise HTTPException(409, str(e))
    return _roles_adicionales_response(usuario, roles)
