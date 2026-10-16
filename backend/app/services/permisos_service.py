"""
Servicio de verificación de permisos.
Implementa el sistema híbrido: rol base + overrides por usuario.
"""

from typing import Dict, List, Optional, Set
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_
from app.models.permiso import Permiso, RolPermisoBase, UsuarioPermisoOverride
from app.models.rol import Rol
from app.models.usuario import Usuario
from app.models.usuario_rol_adicional import UsuarioRolAdicional

# Opt-in permission codes: SUPERADMIN does NOT get these implicitly. They change
# how the app looks or which data it shows (TP-Link theme, TP-only data lock), so
# a SUPERADMIN gets one only through an explicit per-user override. Everyone else
# gets them through roles/overrides as usual. Mirrored in
# frontend/src/constants/permisosOptIn.js (a test keeps both lists equal).
OPT_IN_PERMISSION_CODES = frozenset({"tplink.tema", "tplink.solo"})


class PermisosService:
    """Servicio para verificar y gestionar permisos de usuarios"""

    def __init__(self, db: Session):
        self.db = db
        self._cache_permisos_rol = {}

    def obtener_permisos_usuario(self, usuario: Usuario) -> Set[str]:
        """
        Obtiene todos los permisos efectivos de un usuario.
        Une los permisos del rol principal con los de sus roles adicionales y después
        aplica los overrides personalizados. Solo el rol principal decide SUPERADMIN.

        Returns:
            Set de códigos de permisos que el usuario tiene
        """
        # SUPERADMIN tiene TODOS los permisos salvo los opt-in, que solo recibe
        # por override explícito.
        if usuario.es_superadmin:
            todos_permisos = {p.codigo for p in self.db.query(Permiso.codigo).all()}
            return (todos_permisos - OPT_IN_PERMISSION_CODES) | self._opt_in_concedidos(usuario)

        # Obtener permisos base del rol (usando rol_id si existe, sino fallback a rol enum)
        if usuario.rol_id:
            permisos_rol = self._obtener_permisos_rol_por_id(usuario.rol_id)
        else:
            permisos_rol = self._obtener_permisos_rol_por_codigo(usuario.rol.value if usuario.rol else "VENTAS")

        permisos_rol = set(permisos_rol) | set(self._obtener_permisos_roles_adicionales(usuario))

        # Obtener overrides del usuario (con permiso eager-loaded para evitar N+1)
        overrides = (
            self.db.query(UsuarioPermisoOverride)
            .options(joinedload(UsuarioPermisoOverride.permiso))
            .filter(UsuarioPermisoOverride.usuario_id == usuario.id)
            .all()
        )

        # Aplicar overrides
        permisos_finales = set(permisos_rol)

        for override in overrides:
            permiso = override.permiso  # Already loaded via joinedload
            if permiso:
                if override.concedido:
                    permisos_finales.add(permiso.codigo)
                else:
                    permisos_finales.discard(permiso.codigo)

        return permisos_finales

    def _opt_in_concedidos(self, usuario: Usuario) -> Set[str]:
        """Códigos opt-in otorgados al usuario por override (`concedido=True`)."""
        filas = (
            self.db.query(Permiso.codigo)
            .join(UsuarioPermisoOverride, UsuarioPermisoOverride.permiso_id == Permiso.id)
            .filter(
                UsuarioPermisoOverride.usuario_id == usuario.id,
                UsuarioPermisoOverride.concedido.is_(True),
                Permiso.codigo.in_(OPT_IN_PERMISSION_CODES),
            )
            .all()
        )
        return {f.codigo for f in filas}

    def _permisos_efectivos(self, usuario: Usuario) -> Set[str]:
        """Permisos del usuario: el cache del request si existe, si no se calculan."""
        if hasattr(usuario, "_permisos_cache"):
            return usuario._permisos_cache
        return self.obtener_permisos_usuario(usuario)

    def _obtener_permisos_rol_por_id(self, rol_id: int) -> List[str]:
        """Obtiene los permisos base de un rol por ID"""
        cache_key = f"id_{rol_id}"
        if cache_key in self._cache_permisos_rol:
            return self._cache_permisos_rol[cache_key]

        permisos = (
            self.db.query(Permiso.codigo)
            .join(RolPermisoBase, RolPermisoBase.permiso_id == Permiso.id)
            .filter(RolPermisoBase.rol_id == rol_id)
            .all()
        )

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

    def _obtener_permisos_roles_adicionales(self, usuario: Usuario) -> Dict[str, List[str]]:
        """
        Permisos base de los roles adicionales del usuario: {permiso_codigo: [rol_codigo, ...]}.

        Una sola query sobre la tabla (no la relación: `get_current_user` carga al usuario con
        `raiseload("*")`). Ignora SUPERADMIN y el propio rol principal: un rol adicional nunca
        cambia la identidad del usuario, solo suma permisos.
        """
        filas = (
            self.db.query(Permiso.codigo, Rol.codigo, Rol.id)
            .join(RolPermisoBase, RolPermisoBase.permiso_id == Permiso.id)
            .join(Rol, Rol.id == RolPermisoBase.rol_id)
            .join(UsuarioRolAdicional, UsuarioRolAdicional.rol_id == Rol.id)
            .filter(UsuarioRolAdicional.usuario_id == usuario.id, Rol.codigo != "SUPERADMIN")
            .all()
        )

        resultado: Dict[str, List[str]] = {}
        for permiso_codigo, rol_codigo, rol_id in filas:
            if rol_id == usuario.rol_id:
                continue
            resultado.setdefault(permiso_codigo, []).append(rol_codigo)
        return {codigo: sorted(set(roles)) for codigo, roles in resultado.items()}

    def tiene_permiso(self, usuario: Usuario, permiso_codigo: str) -> bool:
        """
        Verifica si un usuario tiene un permiso específico.

        Args:
            usuario: Usuario a verificar
            permiso_codigo: Código del permiso (ej: 'productos.editar_precios')

        Returns:
            True si el usuario tiene el permiso
        """
        # SUPERADMIN tiene todos los permisos salvo los opt-in (ver OPT_IN_PERMISSION_CODES)
        if usuario.es_superadmin and permiso_codigo not in OPT_IN_PERMISSION_CODES:
            return True

        # Fast path: use pre-loaded cache from get_current_user
        if hasattr(usuario, "_permisos_cache"):
            return permiso_codigo in usuario._permisos_cache

        # Fallback for scripts/detached users without cache
        permisos = self.obtener_permisos_usuario(usuario)
        return permiso_codigo in permisos

    def tiene_algun_permiso(self, usuario: Usuario, permisos: List[str]) -> bool:
        """Verifica si el usuario tiene al menos uno de los permisos listados"""
        if usuario.es_superadmin and any(p not in OPT_IN_PERMISSION_CODES for p in permisos):
            return True

        # Fast path: use pre-loaded cache from get_current_user
        if hasattr(usuario, "_permisos_cache"):
            return bool(usuario._permisos_cache.intersection(permisos))

        # Fallback for scripts/detached users without cache
        permisos_usuario = self.obtener_permisos_usuario(usuario)
        return bool(permisos_usuario.intersection(permisos))

    def tiene_todos_los_permisos(self, usuario: Usuario, permisos: List[str]) -> bool:
        """Verifica si el usuario tiene todos los permisos listados"""
        if usuario.es_superadmin:
            opt_in = [p for p in permisos if p in OPT_IN_PERMISSION_CODES]
            return not opt_in or all(p in self._permisos_efectivos(usuario) for p in opt_in)

        # Fast path: use pre-loaded cache from get_current_user
        if hasattr(usuario, "_permisos_cache"):
            return all(p in usuario._permisos_cache for p in permisos)

        # Fallback for scripts/detached users without cache
        permisos_usuario = self.obtener_permisos_usuario(usuario)
        return all(p in permisos_usuario for p in permisos)

    def agregar_override(
        self,
        usuario_id: int,
        permiso_codigo: str,
        concedido: bool,
        otorgado_por_id: Optional[int] = None,
        motivo: Optional[str] = None,
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
        override = (
            self.db.query(UsuarioPermisoOverride)
            .filter(
                and_(UsuarioPermisoOverride.usuario_id == usuario_id, UsuarioPermisoOverride.permiso_id == permiso.id)
            )
            .first()
        )

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
                motivo=motivo,
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

        resultado = (
            self.db.query(UsuarioPermisoOverride)
            .filter(
                and_(UsuarioPermisoOverride.usuario_id == usuario_id, UsuarioPermisoOverride.permiso_id == permiso.id)
            )
            .delete()
        )

        self.db.commit()
        return resultado > 0

    def obtener_overrides_usuario(self, usuario_id: int) -> List[dict]:
        """Obtiene todos los overrides de un usuario con detalle"""
        overrides = (
            self.db.query(UsuarioPermisoOverride, Permiso)
            .join(Permiso, UsuarioPermisoOverride.permiso_id == Permiso.id)
            .filter(UsuarioPermisoOverride.usuario_id == usuario_id)
            .all()
        )

        return [
            {
                "permiso_codigo": permiso.codigo,
                "permiso_nombre": permiso.nombre,
                "concedido": override.concedido,
                "motivo": override.motivo,
                "created_at": override.created_at.isoformat() if override.created_at else None,
            }
            for override, permiso in overrides
        ]

    def obtener_catalogo_permisos(self) -> List[dict]:
        """Obtiene el catálogo completo de permisos agrupado por categoría"""
        permisos = self.db.query(Permiso).order_by(Permiso.orden).all()

        resultado = {}
        for p in permisos:
            categoria = p.categoria.value if hasattr(p.categoria, "value") else p.categoria
            if categoria not in resultado:
                resultado[categoria] = []
            resultado[categoria].append(
                {"codigo": p.codigo, "nombre": p.nombre, "descripcion": p.descripcion, "es_critico": p.es_critico}
            )

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

        permisos_adicionales = {} if es_superadmin else self._obtener_permisos_roles_adicionales(usuario)

        # `joinedload` (not a bare `join`): reading `o.permiso.codigo` below would otherwise
        # emit one extra SELECT per override. Same pattern as `obtener_permisos_usuario`.
        overrides = {
            o.permiso.codigo: o.concedido
            for o in self.db.query(UsuarioPermisoOverride)
            .options(joinedload(UsuarioPermisoOverride.permiso))
            .filter(UsuarioPermisoOverride.usuario_id == usuario.id)
            .all()
        }

        catalogo = self.db.query(Permiso).order_by(Permiso.orden).all()

        resultado = {}
        for p in catalogo:
            categoria = p.categoria.value if hasattr(p.categoria, "value") else p.categoria
            if categoria not in resultado:
                resultado[categoria] = []

            # SUPERADMIN tiene todos los permisos por rol por definición, salvo los
            # opt-in: esos solo los tiene por override, como cualquier otro usuario.
            roles_adicionales = permisos_adicionales.get(p.codigo, [])
            tiene_por_rol_principal = p.codigo in permisos_rol
            es_opt_in = p.codigo in OPT_IN_PERMISSION_CODES
            if es_superadmin:
                tiene_por_rol = not es_opt_in
                tiene_por_rol_principal = False
            else:
                tiene_por_rol = tiene_por_rol_principal or bool(roles_adicionales)
            override = overrides.get(p.codigo)

            # Calcular estado efectivo
            # SUPERADMIN siempre tiene todos los permisos efectivos (salvo opt-in)
            if es_superadmin and not es_opt_in:
                efectivo = True
                origen = "superadmin"
            elif override is not None:
                efectivo = override
                origen = "override_agregado" if override else "override_quitado"
            else:
                efectivo = tiene_por_rol
                if tiene_por_rol_principal:
                    origen = "rol"
                elif roles_adicionales:
                    origen = "rol_adicional"
                else:
                    origen = "sin_permiso"

            resultado[categoria].append(
                {
                    "codigo": p.codigo,
                    "nombre": p.nombre,
                    "descripcion": p.descripcion,
                    "es_critico": p.es_critico,
                    "tiene_por_rol": tiene_por_rol,
                    "override": override,
                    "efectivo": efectivo,
                    "origen": origen,
                    # Roles adicionales que otorgan el permiso ("rol adicional <codigo>" en la UI)
                    "roles_adicionales": roles_adicionales,
                }
            )

        return resultado


def verificar_permiso(db: Session, usuario: Usuario, permiso: str) -> bool:
    """Helper function para verificar permisos de forma rápida"""
    # Fast path: use pre-loaded cache from get_current_user
    if hasattr(usuario, "_permisos_cache"):
        if usuario.es_superadmin and permiso not in OPT_IN_PERMISSION_CODES:
            return True
        return permiso in usuario._permisos_cache

    # Fallback for scripts/detached users without cache
    service = PermisosService(db)
    return service.tiene_permiso(usuario, permiso)


def obtener_permisos(db: Session, usuario: Usuario) -> Set[str]:
    """Helper function para obtener todos los permisos de un usuario"""
    service = PermisosService(db)
    return service.obtener_permisos_usuario(usuario)
