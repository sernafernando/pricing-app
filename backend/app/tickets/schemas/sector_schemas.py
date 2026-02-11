from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Optional, List


class SectorConfiguracionAsignacion(BaseModel):
    """Configuración de asignación para un sector"""

    tipo: str = Field(
        default="round_robin", description="Tipo de estrategia: round_robin, basado_en_carga, basado_en_skills, manual"
    )
    auto_assign: bool = Field(default=True, description="Si debe auto-asignar tickets nuevos")
    solo_con_permiso: Optional[str] = Field(default=None, description="Código de permiso requerido para asignación")
    skill_field: Optional[str] = Field(default=None, description="Campo en metadata para skill-based (ej: marca_id)")
    fallback: Optional[str] = Field(default="basado_en_carga", description="Estrategia fallback si falla la principal")


class SectorConfiguracionNotificaciones(BaseModel):
    """Configuración de notificaciones para un sector"""

    on_create: List[str] = Field(default_factory=lambda: ["in_app"], description="Canales al crear ticket")
    on_assign: List[str] = Field(default_factory=lambda: ["in_app"], description="Canales al asignar")
    on_estado_changed: List[str] = Field(default_factory=lambda: ["in_app"], description="Canales al cambiar estado")
    on_comentario: List[str] = Field(default_factory=lambda: ["in_app"], description="Canales al comentar")
    on_close: List[str] = Field(default_factory=lambda: ["email"], description="Canales al cerrar")
    webhook_url: Optional[str] = Field(default=None, description="URL para webhooks externos")
    destinatarios_default: List[int] = Field(
        default_factory=list, description="IDs de usuarios que siempre reciben notificaciones"
    )


class SectorConfiguracionSLA(BaseModel):
    """Configuración de SLA (Service Level Agreement) para un sector"""

    respuesta_horas: Optional[int] = Field(default=None, description="Horas máximas para primera respuesta")
    resolucion_horas: Optional[int] = Field(default=None, description="Horas máximas para resolución")
    escalamiento_auto_horas: Optional[int] = Field(default=None, description="Horas para escalamiento automático")


class SectorConfiguracion(BaseModel):
    """Configuración completa de un sector"""

    asignacion: SectorConfiguracionAsignacion = Field(default_factory=SectorConfiguracionAsignacion)
    notificaciones: SectorConfiguracionNotificaciones = Field(default_factory=SectorConfiguracionNotificaciones)
    sla: SectorConfiguracionSLA = Field(default_factory=SectorConfiguracionSLA)
    campos_requeridos: List[str] = Field(default_factory=list, description="Campos requeridos en metadata")
    workflow_default_id: Optional[int] = Field(default=None, description="ID del workflow por defecto")


class SectorBase(BaseModel):
    """Schema base para Sector"""

    codigo: str = Field(..., min_length=2, max_length=50, description="Código único del sector (ej: pricing, soporte)")
    nombre: str = Field(..., min_length=3, max_length=100, description="Nombre descriptivo del sector")
    descripcion: Optional[str] = Field(default=None, description="Descripción detallada del sector")
    icono: Optional[str] = Field(default=None, max_length=50, description="Icono para UI")
    color: Optional[str] = Field(default=None, max_length=20, description="Color hex para UI")
    activo: bool = Field(default=True, description="Si el sector está activo")
    configuracion: SectorConfiguracion = Field(
        default_factory=SectorConfiguracion, description="Configuración del sector"
    )

    @field_validator("codigo")
    @classmethod
    def validar_codigo(cls, v: str) -> str:
        """El código debe ser lowercase y sin espacios"""
        return v.lower().strip().replace(" ", "_")

    @field_validator("color")
    @classmethod
    def validar_color(cls, v: Optional[str]) -> Optional[str]:
        """Validar formato de color hex"""
        if v is None:
            return v
        if not v.startswith("#"):
            v = f"#{v}"
        if len(v) not in [4, 7]:  # #FFF o #FFFFFF
            raise ValueError("Color debe ser formato hex válido (#FFF o #FFFFFF)")
        return v


class SectorCreate(SectorBase):
    """Schema para crear un Sector"""

    pass


class SectorUpdate(BaseModel):
    """Schema para actualizar un Sector (todos los campos opcionales)"""

    nombre: Optional[str] = Field(default=None, min_length=3, max_length=100)
    descripcion: Optional[str] = None
    icono: Optional[str] = None
    color: Optional[str] = None
    activo: Optional[bool] = None
    configuracion: Optional[SectorConfiguracion] = None


class SectorResponse(SectorBase):
    """Schema de respuesta para Sector"""

    model_config = ConfigDict(from_attributes=True)

    id: int
