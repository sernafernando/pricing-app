"""
Servicio de verificación de permisos.
Implementa el sistema híbrido: rol base + overrides por usuario.
"""
from typing import List, Optional, Set
from sqlalchemy.orm import Session
from sqlalchemy import and_
from functools import lru_cache
from app.models.permiso import Permiso, RolPermisoBase, UsuarioPermisoOverride
from app.models.usuario import Usuario


class PermisosService:
    """Servicio para verificar y gestionar permisos de usuarios"""

    def __init__(self, db: Session):
        self.db = db
        self._cache_permisos_rol = {}

    def obtener_permisos_usuario(self, usuario: Usuario) -> Set[str]:
        """
        Obtiene todos los permisos efectivos de un usuario.
        Combina permisos del rol base con overrides personalizados.

        Returns:
            Set de códigos de permisos que el usuario tiene
        """
        # SUPERADMIN siempre tiene TODOS los permisos
        if usuario.es_superadmin:
            todos_permisos = self.db.query(Permiso.codigo).all()
            return {p.codigo for p in todos_permisos}

        # Obtener permisos base del rol (usando rol_id si existe, sino fallback a rol enum)
        if usuario.rol_id:
            permisos_rol = self._obtener_permisos_rol_por_id(usuario.rol_id)
        else:
            permisos_rol = self._obtener_permisos_rol_por_codigo(usuario.rol.value if usuario.rol else "VENTAS")

        # Obtener overrides del usuario
        overrides = self.db.query(UsuarioPermisoOverride).filter(
            UsuarioPermisoOverride.usuario_id == usuario.id
        ).all()

        # Aplicar overrides
        permisos_finales = set(permisos_rol)

        for override in overrides:
            permiso = self.db.query(Permiso).filter(Permiso.id == override.permiso_id).first()
            if permiso:
                if override.concedido:
                    permisos_finales.add(permiso.codigo)
                else:
                    permisos_finales.discard(permiso.codigo)

        return permisos_finales

    def _obtener_permisos_rol_por_id(self, rol_id: int) -> List[str]:
        """Obtiene los permisos base de un rol por ID"""
        cache_key = f"id_{rol_id}"
        if cache_key in self._cache_permisos_rol:
            return self._cache_permisos_rol[cache_key]

        permisos = self.db.query(Permiso.codigo).join(
            RolPermisoBase, RolPermisoBase.permiso_id == Permiso.id
        ).filter(
            RolPermisoBase.rol_id == rol_id
        ).all()

        codigos = [p.codigo for p in permisos]
        self._cache_permisos_rol[cache_key] = codigos
        return codigos

    def _obtener_permisos_rol_por_codigo(self, rol_codigo: str) -> List[str]:
        """Obtiene los permisos base de un rol por código (compatibilidad)"""
        from app.models.rol import Rol

        cache_key = f"codigo_{rol_codigo}"
        if cache_key in self._cache_permisos_rol:
            return self._cache_permisos_rol[cache_key]

        # Buscar el rol por código
        rol = self.db.query(Rol).filter(Rol.codigo == rol_codigo).first()
        if not rol:
            return []

        return self._obtener_permisos_rol_por_id(rol.id)

    def tiene_permiso(self, usuario: Usuario, permiso_codigo: str) -> bool:
        """
        Verifica si un usuario tiene un permiso específico.

        Args:
            usuario: Usuario a verificar
            permiso_codigo: Código del permiso (ej: 'productos.editar_precios')

        Returns:
            True si el usuario tiene el permiso
        """
        # SUPERADMIN siempre tiene todos los permisos
        if usuario.es_superadmin:
            return True

        permisos = self.obtener_permisos_usuario(usuario)
        return permiso_codigo in permisos

    def tiene_algun_permiso(self, usuario: Usuario, permisos: List[str]) -> bool:
        """Verifica si el usuario tiene al menos uno de los permisos listados"""
        if usuario.es_superadmin:
            return True

        permisos_usuario = self.obtener_permisos_usuario(usuario)
        return bool(permisos_usuario.intersection(permisos))

    def tiene_todos_los_permisos(self, usuario: Usuario, permisos: List[str]) -> bool:
        """Verifica si el usuario tiene todos los permisos listados"""
        if usuario.es_superadmin:
            return True

        permisos_usuario = self.obtener_permisos_usuario(usuario)
        return all(p in permisos_usuario for p in permisos)

    def agregar_override(
        self,
        usuario_id: int,
        permiso_codigo: str,
        concedido: bool,
        otorgado_por_id: Optional[int] = None,
        motivo: Optional[str] = None
    ) -> UsuarioPermisoOverride:
        """
        Agrega o actualiza un override de permiso para un usuario.

        Args:
            usuario_id: ID del usuario
            permiso_codigo: Código del permiso
            concedido: True para agregar, False para quitar
            otorgado_por_id: ID del usuario que otorga el override
            motivo: Motivo del cambio

        Returns:
            El override creado/actualizado
        """
        # Buscar el permiso
        permiso = self.db.query(Permiso).filter(Permiso.codigo == permiso_codigo).first()
        if not permiso:
            raise ValueError(f"Permiso '{permiso_codigo}' no existe")

        # Buscar override existente
        override = self.db.query(UsuarioPermisoOverride).filter(
            and_(
                UsuarioPermisoOverride.usuario_id == usuario_id,
                UsuarioPermisoOverride.permiso_id == permiso.id
            )
        ).first()

        if override:
            # Actualizar existente
            override.concedido = concedido
            override.otorgado_por_id = otorgado_por_id
            override.motivo = motivo
        else:
            # Crear nuevo
            override = UsuarioPermisoOverride(
                usuario_id=usuario_id,
                permiso_id=permiso.id,
                concedido=concedido,
                otorgado_por_id=otorgado_por_id,
                motivo=motivo
            )
            self.db.add(override)

        self.db.commit()
        return override

    def eliminar_override(self, usuario_id: int, permiso_codigo: str) -> bool:
        """
        Elimina un override de permiso, volviendo al permiso base del rol.

        Returns:
            True si se eliminó, False si no existía
        """
        permiso = self.db.query(Permiso).filter(Permiso.codigo == permiso_codigo).first()
        if not permiso:
            return False

        resultado = self.db.query(UsuarioPermisoOverride).filter(
            and_(
                UsuarioPermisoOverride.usuario_id == usuario_id,
                UsuarioPermisoOverride.permiso_id == permiso.id
            )
        ).delete()

        self.db.commit()
        return resultado > 0

    def obtener_overrides_usuario(self, usuario_id: int) -> List[dict]:
        """Obtiene todos los overrides de un usuario con detalle"""
        overrides = self.db.query(
            UsuarioPermisoOverride,
            Permiso
        ).join(
            Permiso, UsuarioPermisoOverride.permiso_id == Permiso.id
        ).filter(
            UsuarioPermisoOverride.usuario_id == usuario_id
        ).all()

        return [{
            'permiso_codigo': permiso.codigo,
            'permiso_nombre': permiso.nombre,
            'concedido': override.concedido,
            'motivo': override.motivo,
            'created_at': override.created_at.isoformat() if override.created_at else None
        } for override, permiso in overrides]

    def obtener_catalogo_permisos(self) -> List[dict]:
        """Obtiene el catálogo completo de permisos agrupado por categoría"""
        permisos = self.db.query(Permiso).order_by(Permiso.orden).all()

        resultado = {}
        for p in permisos:
            categoria = p.categoria.value if hasattr(p.categoria, 'value') else p.categoria
            if categoria not in resultado:
                resultado[categoria] = []
            resultado[categoria].append({
                'codigo': p.codigo,
                'nombre': p.nombre,
                'descripcion': p.descripcion,
                'es_critico': p.es_critico
            })

        return resultado

    def obtener_permisos_detallados_usuario(self, usuario: Usuario) -> dict:
        """
        Obtiene información detallada de permisos de un usuario.
        Incluye qué permisos vienen del rol y cuáles son overrides.
        """
        es_superadmin = usuario.es_superadmin

        if usuario.rol_id:
            permisos_rol = set(self._obtener_permisos_rol_por_id(usuario.rol_id))
        else:
            permisos_rol = set(self._obtener_permisos_rol_por_codigo(usuario.rol.value if usuario.rol else "VENTAS"))

        overrides = {o.permiso.codigo: o.concedido
                     for o in self.db.query(UsuarioPermisoOverride).join(Permiso).filter(
                         UsuarioPermisoOverride.usuario_id == usuario.id
                     ).all()}

        catalogo = self.db.query(Permiso).order_by(Permiso.orden).all()

        resultado = {}
        for p in catalogo:
            categoria = p.categoria.value if hasattr(p.categoria, 'value') else p.categoria
            if categoria not in resultado:
                resultado[categoria] = []

            # SUPERADMIN tiene todos los permisos por rol por definición
            tiene_por_rol = True if es_superadmin else p.codigo in permisos_rol
            override = overrides.get(p.codigo)

            # Calcular estado efectivo
            # SUPERADMIN siempre tiene todos los permisos efectivos
            if es_superadmin:
                efectivo = True
                origen = 'superadmin'
            elif override is not None:
                efectivo = override
                origen = 'override_agregado' if override else 'override_quitado'
            else:
                efectivo = tiene_por_rol
                origen = 'rol' if tiene_por_rol else 'sin_permiso'

            resultado[categoria].append({
                'codigo': p.codigo,
                'nombre': p.nombre,
                'descripcion': p.descripcion,
                'es_critico': p.es_critico,
                'tiene_por_rol': tiene_por_rol,
                'override': override,
                'efectivo': efectivo,
                'origen': origen
            })

        return resultado


def verificar_permiso(db: Session, usuario: Usuario, permiso: str) -> bool:
    """Helper function para verificar permisos de forma rápida"""
    service = PermisosService(db)
    return service.tiene_permiso(usuario, permiso)


def obtener_permisos(db: Session, usuario: Usuario) -> Set[str]:
    """Helper function para obtener todos los permisos de un usuario"""
    service = PermisosService(db)
    return service.obtener_permisos_usuario(usuario)
