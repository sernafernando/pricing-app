"""
Servicio para gestión de roles del sistema.
"""
from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_
from app.models.rol import Rol
from app.models.permiso import Permiso, RolPermisoBase
from app.models.usuario import Usuario


class RolesService:
    """Servicio para CRUD de roles y asignación de permisos"""

    def __init__(self, db: Session):
        self.db = db

    def listar_roles(self, incluir_inactivos: bool = False) -> List[Rol]:
        """Lista todos los roles del sistema"""
        query = self.db.query(Rol)
        if not incluir_inactivos:
            query = query.filter(Rol.activo == True)
        return query.order_by(Rol.orden).all()

    def obtener_rol(self, rol_id: int) -> Optional[Rol]:
        """Obtiene un rol por ID"""
        return self.db.query(Rol).filter(Rol.id == rol_id).first()

    def obtener_rol_por_codigo(self, codigo: str) -> Optional[Rol]:
        """Obtiene un rol por código"""
        return self.db.query(Rol).filter(Rol.codigo == codigo).first()

    def crear_rol(
        self,
        codigo: str,
        nombre: str,
        descripcion: Optional[str] = None,
        orden: int = 0
    ) -> Rol:
        """
        Crea un nuevo rol.

        Raises:
            ValueError: Si ya existe un rol con ese código
        """
        existente = self.obtener_rol_por_codigo(codigo)
        if existente:
            raise ValueError(f"Ya existe un rol con código '{codigo}'")

        rol = Rol(
            codigo=codigo.upper(),
            nombre=nombre,
            descripcion=descripcion,
            orden=orden,
            es_sistema=False,
            activo=True
        )
        self.db.add(rol)
        self.db.commit()
        self.db.refresh(rol)
        return rol

    def actualizar_rol(
        self,
        rol_id: int,
        nombre: Optional[str] = None,
        descripcion: Optional[str] = None,
        orden: Optional[int] = None,
        activo: Optional[bool] = None
    ) -> Optional[Rol]:
        """
        Actualiza un rol existente.
        No permite modificar código ni es_sistema.
        """
        rol = self.obtener_rol(rol_id)
        if not rol:
            return None

        if nombre is not None:
            rol.nombre = nombre
        if descripcion is not None:
            rol.descripcion = descripcion
        if orden is not None:
            rol.orden = orden
        if activo is not None and not rol.es_sistema:
            # No permitir desactivar roles de sistema
            rol.activo = activo

        self.db.commit()
        self.db.refresh(rol)
        return rol

    def eliminar_rol(self, rol_id: int) -> bool:
        """
        Elimina un rol si no es de sistema y no tiene usuarios asignados.

        Returns:
            True si se eliminó, False si no se pudo
        """
        rol = self.obtener_rol(rol_id)
        if not rol:
            return False

        if rol.es_sistema:
            raise ValueError(f"No se puede eliminar el rol de sistema '{rol.codigo}'")

        # Verificar si hay usuarios con este rol
        usuarios_con_rol = self.db.query(Usuario).filter(Usuario.rol_id == rol_id).count()
        if usuarios_con_rol > 0:
            raise ValueError(f"No se puede eliminar el rol '{rol.codigo}' porque tiene {usuarios_con_rol} usuarios asignados")

        self.db.delete(rol)
        self.db.commit()
        return True

    def clonar_rol(
        self,
        rol_origen_id: int,
        nuevo_codigo: str,
        nuevo_nombre: str,
        descripcion: Optional[str] = None
    ) -> Rol:
        """
        Clona un rol existente con sus permisos.
        """
        rol_origen = self.obtener_rol(rol_origen_id)
        if not rol_origen:
            raise ValueError(f"No existe el rol con ID {rol_origen_id}")

        # Crear nuevo rol
        nuevo_rol = self.crear_rol(
            codigo=nuevo_codigo,
            nombre=nuevo_nombre,
            descripcion=descripcion or f"Clonado de {rol_origen.nombre}",
            orden=rol_origen.orden + 1
        )

        # Copiar permisos
        permisos_origen = self.db.query(RolPermisoBase).filter(
            RolPermisoBase.rol_id == rol_origen_id
        ).all()

        for permiso_base in permisos_origen:
            nuevo_permiso = RolPermisoBase(
                rol_id=nuevo_rol.id,
                permiso_id=permiso_base.permiso_id
            )
            self.db.add(nuevo_permiso)

        self.db.commit()
        return nuevo_rol

    # ==========================================================================
    # Gestión de permisos del rol
    # ==========================================================================

    def obtener_permisos_rol(self, rol_id: int) -> List[str]:
        """Obtiene los códigos de permisos de un rol"""
        permisos = self.db.query(Permiso.codigo).join(
            RolPermisoBase, RolPermisoBase.permiso_id == Permiso.id
        ).filter(
            RolPermisoBase.rol_id == rol_id
        ).all()

        return [p.codigo for p in permisos]

    def obtener_permisos_rol_detallados(self, rol_id: int) -> List[dict]:
        """Obtiene los permisos de un rol con detalles"""
        permisos = self.db.query(Permiso).join(
            RolPermisoBase, RolPermisoBase.permiso_id == Permiso.id
        ).filter(
            RolPermisoBase.rol_id == rol_id
        ).order_by(Permiso.orden).all()

        return [{
            'codigo': p.codigo,
            'nombre': p.nombre,
            'descripcion': p.descripcion,
            'categoria': p.categoria,
            'es_critico': p.es_critico
        } for p in permisos]

    def set_permisos_rol(self, rol_id: int, permisos_codigos: List[str]) -> int:
        """
        Establece los permisos de un rol (reemplaza todos).

        Args:
            rol_id: ID del rol
            permisos_codigos: Lista de códigos de permisos

        Returns:
            Cantidad de permisos asignados
        """
        rol = self.obtener_rol(rol_id)
        if not rol:
            raise ValueError(f"No existe el rol con ID {rol_id}")

        # No permitir modificar permisos de SUPERADMIN
        if rol.codigo == "SUPERADMIN":
            raise ValueError("No se pueden modificar los permisos de SUPERADMIN")

        # Obtener IDs de los permisos
        permisos = self.db.query(Permiso).filter(Permiso.codigo.in_(permisos_codigos)).all()
        permiso_ids = {p.id for p in permisos}

        # Eliminar permisos existentes
        self.db.query(RolPermisoBase).filter(RolPermisoBase.rol_id == rol_id).delete()

        # Agregar nuevos permisos
        for permiso_id in permiso_ids:
            nuevo = RolPermisoBase(rol_id=rol_id, permiso_id=permiso_id)
            self.db.add(nuevo)

        self.db.commit()
        return len(permiso_ids)

    def agregar_permiso_rol(self, rol_id: int, permiso_codigo: str) -> bool:
        """Agrega un permiso a un rol"""
        permiso = self.db.query(Permiso).filter(Permiso.codigo == permiso_codigo).first()
        if not permiso:
            raise ValueError(f"No existe el permiso '{permiso_codigo}'")

        # Verificar si ya existe
        existente = self.db.query(RolPermisoBase).filter(
            and_(RolPermisoBase.rol_id == rol_id, RolPermisoBase.permiso_id == permiso.id)
        ).first()

        if existente:
            return False

        nuevo = RolPermisoBase(rol_id=rol_id, permiso_id=permiso.id)
        self.db.add(nuevo)
        self.db.commit()
        return True

    def quitar_permiso_rol(self, rol_id: int, permiso_codigo: str) -> bool:
        """Quita un permiso de un rol"""
        permiso = self.db.query(Permiso).filter(Permiso.codigo == permiso_codigo).first()
        if not permiso:
            return False

        resultado = self.db.query(RolPermisoBase).filter(
            and_(RolPermisoBase.rol_id == rol_id, RolPermisoBase.permiso_id == permiso.id)
        ).delete()

        self.db.commit()
        return resultado > 0

    # ==========================================================================
    # Asignación de roles a usuarios
    # ==========================================================================

    def asignar_rol_usuario(self, usuario_id: int, rol_id: int) -> bool:
        """Asigna un rol a un usuario"""
        usuario = self.db.query(Usuario).filter(Usuario.id == usuario_id).first()
        if not usuario:
            raise ValueError(f"No existe el usuario con ID {usuario_id}")

        rol = self.obtener_rol(rol_id)
        if not rol:
            raise ValueError(f"No existe el rol con ID {rol_id}")

        usuario.rol_id = rol_id
        self.db.commit()
        return True

    def obtener_usuarios_rol(self, rol_id: int) -> List[dict]:
        """Obtiene los usuarios que tienen un rol específico"""
        usuarios = self.db.query(Usuario).filter(Usuario.rol_id == rol_id).all()
        return [{
            'id': u.id,
            'email': u.email,
            'nombre': u.nombre,
            'activo': u.activo
        } for u in usuarios]

    def contar_usuarios_rol(self, rol_id: int) -> int:
        """Cuenta cuántos usuarios tienen un rol específico"""
        return self.db.query(Usuario).filter(Usuario.rol_id == rol_id).count()
