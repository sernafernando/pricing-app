"""
Sistema de Permisos Híbrido
- Roles base con permisos por defecto
- Overrides por usuario (agregar o quitar permisos específicos)
"""
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Enum as SQLEnum, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base
import enum


class CategoriaPermiso(str, enum.Enum):
    """Categorías de permisos para organización en el panel"""
    PRODUCTOS = "productos"
    VENTAS_ML = "ventas_ml"
    VENTAS_FUERA = "ventas_fuera"
    VENTAS_TN = "ventas_tn"
    ADMINISTRACION = "administracion"
    REPORTES = "reportes"
    CONFIGURACION = "configuracion"


class Permiso(Base):
    """
    Catálogo de permisos disponibles en el sistema.
    Cada permiso representa una acción o acceso específico.
    """
    __tablename__ = "permisos"

    id = Column(Integer, primary_key=True, index=True)
    codigo = Column(String(100), unique=True, nullable=False, index=True)
    nombre = Column(String(255), nullable=False)
    descripcion = Column(Text, nullable=True)
    # Usar String en vez de Enum para evitar problemas de caching de SQLAlchemy
    categoria = Column(String(50), nullable=False)

    # Orden para mostrar en el panel
    orden = Column(Integer, default=0)

    # Si es un permiso crítico (requiere confirmación adicional)
    es_critico = Column(Boolean, default=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self):
        return f"<Permiso({self.codigo})>"


class RolPermisoBase(Base):
    """
    Permisos por defecto de cada rol.
    Define qué permisos tiene un rol de forma predeterminada.
    """
    __tablename__ = "roles_permisos_base"

    id = Column(Integer, primary_key=True, index=True)
    rol = Column(String(50), nullable=False, index=True)  # SUPERADMIN, ADMIN, GERENTE, PRICING, VENTAS
    permiso_id = Column(Integer, ForeignKey('permisos.id', ondelete='CASCADE'), nullable=False)

    # Relación
    permiso = relationship("Permiso")

    class Meta:
        unique_together = ('rol', 'permiso_id')

    def __repr__(self):
        return f"<RolPermisoBase(rol={self.rol}, permiso_id={self.permiso_id})>"


class UsuarioPermisoOverride(Base):
    """
    Overrides de permisos por usuario.
    Permite agregar o quitar permisos específicos a un usuario,
    independientemente de su rol base.
    """
    __tablename__ = "usuarios_permisos_override"

    id = Column(Integer, primary_key=True, index=True)
    usuario_id = Column(Integer, ForeignKey('usuarios.id', ondelete='CASCADE'), nullable=False, index=True)
    permiso_id = Column(Integer, ForeignKey('permisos.id', ondelete='CASCADE'), nullable=False)

    # True = agregar permiso, False = quitar permiso
    concedido = Column(Boolean, nullable=False)

    # Auditoría
    otorgado_por_id = Column(Integer, ForeignKey('usuarios.id'), nullable=True)
    motivo = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relaciones
    usuario = relationship("Usuario", foreign_keys=[usuario_id], backref="permisos_override")
    permiso = relationship("Permiso")
    otorgado_por = relationship("Usuario", foreign_keys=[otorgado_por_id])

    class Meta:
        unique_together = ('usuario_id', 'permiso_id')

    def __repr__(self):
        accion = "+" if self.concedido else "-"
        return f"<UsuarioPermisoOverride(usuario={self.usuario_id}, {accion}{self.permiso_id})>"


# =============================================================================
# CATÁLOGO DE PERMISOS DEL SISTEMA
# =============================================================================

PERMISOS_SISTEMA = [
    # =========================================================================
    # PRODUCTOS
    # =========================================================================
    {
        "codigo": "productos.ver",
        "nombre": "Ver productos",
        "descripcion": "Acceso a la lista de productos y sus detalles",
        "categoria": CategoriaPermiso.PRODUCTOS,
        "orden": 1
    },
    {
        "codigo": "productos.editar_precios",
        "nombre": "Editar precios",
        "descripcion": "Modificar precios clásica, cuotas y web transferencia",
        "categoria": CategoriaPermiso.PRODUCTOS,
        "orden": 2
    },
    {
        "codigo": "productos.editar_rebate",
        "nombre": "Gestionar Rebate",
        "descripcion": "Activar/desactivar rebate y modificar porcentaje",
        "categoria": CategoriaPermiso.PRODUCTOS,
        "orden": 3
    },
    {
        "codigo": "productos.editar_web_transferencia",
        "nombre": "Gestionar Web Transferencia",
        "descripcion": "Activar/desactivar web transferencia y modificar porcentaje",
        "categoria": CategoriaPermiso.PRODUCTOS,
        "orden": 4
    },
    {
        "codigo": "productos.editar_out_of_cards",
        "nombre": "Marcar Out of Cards",
        "descripcion": "Marcar/desmarcar productos como out of cards",
        "categoria": CategoriaPermiso.PRODUCTOS,
        "orden": 5
    },
    {
        "codigo": "productos.banear",
        "nombre": "Banear productos",
        "descripcion": "Agregar productos a la banlist",
        "categoria": CategoriaPermiso.PRODUCTOS,
        "orden": 6,
        "es_critico": True
    },
    {
        "codigo": "productos.exportar",
        "nombre": "Exportar productos",
        "descripcion": "Exportar listado de productos a Excel",
        "categoria": CategoriaPermiso.PRODUCTOS,
        "orden": 7
    },
    {
        "codigo": "productos.ver_costos",
        "nombre": "Ver costos",
        "descripcion": "Ver columnas de costo en productos",
        "categoria": CategoriaPermiso.PRODUCTOS,
        "orden": 8
    },
    {
        "codigo": "productos.ver_auditoria",
        "nombre": "Ver auditoría de productos",
        "descripcion": "Ver historial de cambios por producto",
        "categoria": CategoriaPermiso.PRODUCTOS,
        "orden": 9
    },

    # =========================================================================
    # VENTAS ML
    # =========================================================================
    {
        "codigo": "ventas_ml.ver_dashboard",
        "nombre": "Ver dashboard ML",
        "descripcion": "Acceso al dashboard de métricas de MercadoLibre",
        "categoria": CategoriaPermiso.VENTAS_ML,
        "orden": 10
    },
    {
        "codigo": "ventas_ml.ver_operaciones",
        "nombre": "Ver operaciones ML",
        "descripcion": "Ver detalle de operaciones de venta ML",
        "categoria": CategoriaPermiso.VENTAS_ML,
        "orden": 11
    },
    {
        "codigo": "ventas_ml.ver_rentabilidad",
        "nombre": "Ver rentabilidad ML",
        "descripcion": "Acceso a la pestaña de rentabilidad ML",
        "categoria": CategoriaPermiso.VENTAS_ML,
        "orden": 12
    },
    {
        "codigo": "ventas_ml.ver_todas_marcas",
        "nombre": "Ver todas las marcas ML",
        "descripcion": "Ver datos de todas las marcas (no solo las asignadas)",
        "categoria": CategoriaPermiso.VENTAS_ML,
        "orden": 13
    },

    # =========================================================================
    # VENTAS FUERA ML
    # =========================================================================
    {
        "codigo": "ventas_fuera.ver_dashboard",
        "nombre": "Ver dashboard Fuera ML",
        "descripcion": "Acceso al dashboard de ventas por fuera de ML",
        "categoria": CategoriaPermiso.VENTAS_FUERA,
        "orden": 20
    },
    {
        "codigo": "ventas_fuera.ver_operaciones",
        "nombre": "Ver operaciones Fuera ML",
        "descripcion": "Ver detalle de operaciones fuera de ML",
        "categoria": CategoriaPermiso.VENTAS_FUERA,
        "orden": 21
    },
    {
        "codigo": "ventas_fuera.ver_rentabilidad",
        "nombre": "Ver rentabilidad Fuera ML",
        "descripcion": "Acceso a la pestaña de rentabilidad fuera de ML",
        "categoria": CategoriaPermiso.VENTAS_FUERA,
        "orden": 22
    },
    {
        "codigo": "ventas_fuera.editar_overrides",
        "nombre": "Editar datos de ventas Fuera ML",
        "descripcion": "Modificar cliente, marca, categoría y otros campos de operaciones",
        "categoria": CategoriaPermiso.VENTAS_FUERA,
        "orden": 23
    },
    {
        "codigo": "ventas_fuera.editar_costos",
        "nombre": "Editar costos Fuera ML",
        "descripcion": "Modificar costos de operaciones fuera de ML",
        "categoria": CategoriaPermiso.VENTAS_FUERA,
        "orden": 24
    },
    {
        "codigo": "ventas_fuera.ver_admin",
        "nombre": "Acceso admin Fuera ML",
        "descripcion": "Acceso a la pestaña de administración fuera de ML",
        "categoria": CategoriaPermiso.VENTAS_FUERA,
        "orden": 25
    },

    # =========================================================================
    # VENTAS TIENDA NUBE
    # =========================================================================
    {
        "codigo": "ventas_tn.ver_dashboard",
        "nombre": "Ver dashboard Tienda Nube",
        "descripcion": "Acceso al dashboard de ventas Tienda Nube",
        "categoria": CategoriaPermiso.VENTAS_TN,
        "orden": 30
    },
    {
        "codigo": "ventas_tn.ver_operaciones",
        "nombre": "Ver operaciones Tienda Nube",
        "descripcion": "Ver detalle de operaciones Tienda Nube",
        "categoria": CategoriaPermiso.VENTAS_TN,
        "orden": 31
    },
    {
        "codigo": "ventas_tn.ver_rentabilidad",
        "nombre": "Ver rentabilidad Tienda Nube",
        "descripcion": "Acceso a la pestaña de rentabilidad Tienda Nube",
        "categoria": CategoriaPermiso.VENTAS_TN,
        "orden": 32
    },
    {
        "codigo": "ventas_tn.editar_overrides",
        "nombre": "Editar datos de ventas TN",
        "descripcion": "Modificar cliente, marca, categoría y otros campos de operaciones TN",
        "categoria": CategoriaPermiso.VENTAS_TN,
        "orden": 33
    },
    {
        "codigo": "ventas_tn.ver_admin",
        "nombre": "Acceso admin Tienda Nube",
        "descripcion": "Acceso a la pestaña de administración Tienda Nube",
        "categoria": CategoriaPermiso.VENTAS_TN,
        "orden": 34
    },

    # =========================================================================
    # REPORTES
    # =========================================================================
    {
        "codigo": "reportes.ver_auditoria",
        "nombre": "Ver auditoría general",
        "descripcion": "Acceso a /ultimos-cambios con historial de modificaciones",
        "categoria": CategoriaPermiso.REPORTES,
        "orden": 40
    },
    {
        "codigo": "reportes.ver_notificaciones",
        "nombre": "Ver notificaciones",
        "descripcion": "Acceso a las notificaciones del sistema",
        "categoria": CategoriaPermiso.REPORTES,
        "orden": 41
    },
    {
        "codigo": "reportes.ver_calculadora",
        "nombre": "Usar calculadora",
        "descripcion": "Acceso a la calculadora de pricing",
        "categoria": CategoriaPermiso.REPORTES,
        "orden": 42
    },
    {
        "codigo": "reportes.exportar",
        "nombre": "Exportar reportes",
        "descripcion": "Exportar datos de reportes a Excel",
        "categoria": CategoriaPermiso.REPORTES,
        "orden": 43
    },

    # =========================================================================
    # ADMINISTRACIÓN
    # =========================================================================
    {
        "codigo": "admin.ver_panel",
        "nombre": "Ver panel de administración",
        "descripcion": "Acceso al panel de administración",
        "categoria": CategoriaPermiso.ADMINISTRACION,
        "orden": 50
    },
    {
        "codigo": "admin.gestionar_usuarios",
        "nombre": "Gestionar usuarios",
        "descripcion": "Crear, editar y desactivar usuarios",
        "categoria": CategoriaPermiso.ADMINISTRACION,
        "orden": 51,
        "es_critico": True
    },
    {
        "codigo": "admin.gestionar_permisos",
        "nombre": "Gestionar permisos",
        "descripcion": "Modificar permisos de usuarios",
        "categoria": CategoriaPermiso.ADMINISTRACION,
        "orden": 52,
        "es_critico": True
    },
    {
        "codigo": "admin.gestionar_pms",
        "nombre": "Gestionar Product Managers",
        "descripcion": "Asignar marcas a Product Managers",
        "categoria": CategoriaPermiso.ADMINISTRACION,
        "orden": 53
    },
    {
        "codigo": "admin.sincronizar",
        "nombre": "Ejecutar sincronizaciones",
        "descripcion": "Ejecutar sincronización de datos externos",
        "categoria": CategoriaPermiso.ADMINISTRACION,
        "orden": 54
    },
    {
        "codigo": "admin.limpieza_masiva",
        "nombre": "Limpieza masiva de datos",
        "descripcion": "Ejecutar limpieza masiva de rebate/web transferencia",
        "categoria": CategoriaPermiso.ADMINISTRACION,
        "orden": 55,
        "es_critico": True
    },
    {
        "codigo": "admin.gestionar_banlist",
        "nombre": "Gestionar banlist",
        "descripcion": "Agregar y quitar items de la banlist",
        "categoria": CategoriaPermiso.ADMINISTRACION,
        "orden": 56
    },
    {
        "codigo": "admin.gestionar_mla_banlist",
        "nombre": "Gestionar MLA banlist",
        "descripcion": "Agregar y quitar MLAs de la banlist",
        "categoria": CategoriaPermiso.ADMINISTRACION,
        "orden": 57
    },

    # =========================================================================
    # CONFIGURACIÓN
    # =========================================================================
    {
        "codigo": "config.ver_comisiones",
        "nombre": "Ver comisiones",
        "descripcion": "Ver configuración de comisiones ML",
        "categoria": CategoriaPermiso.CONFIGURACION,
        "orden": 60
    },
    {
        "codigo": "config.editar_comisiones",
        "nombre": "Editar comisiones",
        "descripcion": "Crear nuevas versiones de comisiones",
        "categoria": CategoriaPermiso.CONFIGURACION,
        "orden": 61,
        "es_critico": True
    },
    {
        "codigo": "config.ver_constantes",
        "nombre": "Ver constantes de pricing",
        "descripcion": "Ver configuración de constantes (tiers, varios, etc.)",
        "categoria": CategoriaPermiso.CONFIGURACION,
        "orden": 62
    },
    {
        "codigo": "config.editar_constantes",
        "nombre": "Editar constantes de pricing",
        "descripcion": "Crear nuevas versiones de constantes",
        "categoria": CategoriaPermiso.CONFIGURACION,
        "orden": 63,
        "es_critico": True
    },
    {
        "codigo": "config.ver_tipo_cambio",
        "nombre": "Ver tipo de cambio",
        "descripcion": "Ver cotización actual del dólar",
        "categoria": CategoriaPermiso.CONFIGURACION,
        "orden": 64
    },
]


# =============================================================================
# PERMISOS POR DEFECTO DE CADA ROL
# =============================================================================

PERMISOS_POR_ROL = {
    "SUPERADMIN": [
        # Todos los permisos
        "*"
    ],
    "ADMIN": [
        # Casi todos los permisos (excepto gestionar SUPERADMIN)
        "productos.*",
        "ventas_ml.*",
        "ventas_fuera.*",
        "ventas_tn.*",
        "reportes.*",
        "admin.ver_panel",
        "admin.gestionar_usuarios",
        "admin.gestionar_permisos",
        "admin.gestionar_pms",
        "admin.sincronizar",
        "admin.limpieza_masiva",
        "admin.gestionar_banlist",
        "admin.gestionar_mla_banlist",
        "config.*",
    ],
    "GERENTE": [
        "productos.ver",
        "productos.ver_costos",
        "productos.ver_auditoria",
        "productos.exportar",
        "ventas_ml.ver_dashboard",
        "ventas_ml.ver_operaciones",
        "ventas_ml.ver_rentabilidad",
        "ventas_ml.ver_todas_marcas",
        "ventas_fuera.ver_dashboard",
        "ventas_fuera.ver_operaciones",
        "ventas_fuera.ver_rentabilidad",
        "ventas_tn.ver_dashboard",
        "ventas_tn.ver_operaciones",
        "ventas_tn.ver_rentabilidad",
        "reportes.ver_auditoria",
        "reportes.ver_notificaciones",
        "reportes.ver_calculadora",
        "reportes.exportar",
        "config.ver_comisiones",
        "config.ver_constantes",
        "config.ver_tipo_cambio",
    ],
    "PRICING": [
        "productos.ver",
        "productos.editar_precios",
        "productos.editar_rebate",
        "productos.editar_web_transferencia",
        "productos.editar_out_of_cards",
        "productos.banear",
        "productos.exportar",
        "productos.ver_costos",
        "productos.ver_auditoria",
        "ventas_ml.ver_dashboard",
        "ventas_ml.ver_operaciones",
        "ventas_ml.ver_rentabilidad",
        "ventas_fuera.ver_dashboard",
        "ventas_fuera.ver_operaciones",
        "ventas_tn.ver_dashboard",
        "ventas_tn.ver_operaciones",
        "reportes.ver_notificaciones",
        "reportes.ver_calculadora",
        "reportes.exportar",
        "config.ver_comisiones",
        "config.ver_constantes",
        "config.ver_tipo_cambio",
    ],
    "VENTAS": [
        "productos.ver",
        "ventas_ml.ver_dashboard",
        "ventas_ml.ver_operaciones",
        "ventas_fuera.ver_dashboard",
        "ventas_fuera.ver_operaciones",
        "ventas_tn.ver_dashboard",
        "ventas_tn.ver_operaciones",
        "reportes.ver_notificaciones",
        "reportes.ver_calculadora",
        "config.ver_tipo_cambio",
    ],
}
