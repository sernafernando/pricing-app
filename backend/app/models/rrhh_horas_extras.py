"""
Horas Extras (HE) — detección, aprobación y liquidación.

Bloque de HE detectado/aprobado/liquidado para un empleado en una fecha y tipo_dia.

Granularidad: un registro por (empleado, fecha, tipo_dia). Si las HE de un día
cruzan el corte de sábado, se generan 2 filas distintas (habil_50 + sabado_100).

Lifecycle:
  detectada → aprobada → liquidada
  detectada → rechazada
  detectada → error_fichadas → detectada (al completar fichada)
  aprobada → detectada (al reabrir, requiere permiso aprobar + auditoría)
  pendiente_asignacion_turno → detectada (al asignar turno y recalcular)

Fix riesgo 1 (revisión 1): bloques aprobada/rechazada/liquidada son inmutables ante
el cron. Modificaciones de fichadas vinculadas generan filas en `rrhh_horas_extras_alertas`.
Cada transición de estado se persiste como fila append-only en
`rrhh_horas_extras_historial`.

Fix revisión 2: `RRHHHorasExtrasConfig` incluye `dias_retencion_alertas` (Q4) y
`cap_dias_recalculo_manual` (Q2) para purga de alertas leídas viejas y caps en el
endpoint de recálculo manual respectivamente.
"""

import enum
from datetime import time

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


# ─── Enums ────────────────────────────────────────────────────────────────


class TipoDiaHE(str, enum.Enum):
    """Clasificación del tipo de día de un bloque de HE."""

    HABIL_50 = "habil_50"
    SABADO_100 = "sabado_100"
    DOMINGO_100 = "domingo_100"
    FERIADO_100 = "feriado_100"
    MANUAL = "manual"


class EstadoHE(str, enum.Enum):
    """Estados del workflow de un bloque de HE."""

    PENDIENTE_ASIGNACION_TURNO = "pendiente_asignacion_turno"
    DETECTADA = "detectada"
    ERROR_FICHADAS = "error_fichadas"
    APROBADA = "aprobada"
    RECHAZADA = "rechazada"
    LIQUIDADA = "liquidada"


class GeneradaPorHE(str, enum.Enum):
    """Origen del bloque (cron o manual)."""

    SISTEMA = "sistema"
    MANUAL = "manual"


class ErrorTipoHE(str, enum.Enum):
    """
    Sub-clasificación del estado `error_fichadas`.

    Solo válido cuando `estado='error_fichadas'`. NULL en cualquier otro estado.

    Activo:
        FICHADA_UNICA — única causa real de error con la lógica simple
        (primera fichada = entrada, última = salida). Si solo hay 1
        fichada en el día, es ambigua: el operador completa con
        "Completar fichada".

    Legacy (mantenidos para compat con bloques en DB creados antes del
    cambio de lógica que parea por orden ignorando `tipo`):
        FICHADAS_DESBALANCEADAS, SIN_FICHADA_ENTRADA, SIN_FICHADA_SALIDA,
        SOLAPAMIENTO. No se generan nuevos.
    """

    FICHADA_UNICA = "fichada_unica"
    FICHADAS_DESBALANCEADAS = "fichadas_desbalanceadas"
    SIN_FICHADA_ENTRADA = "sin_fichada_entrada"
    SIN_FICHADA_SALIDA = "sin_fichada_salida"
    SOLAPAMIENTO = "solapamiento"
    OTRO = "otro"


# Tipos de alerta — string constants (no enum, según design §2.4).
# Documentados aquí para referencia del service layer.
TIPO_ALERTA_FICHADA_MODIFICADA = "fichada_modificada"
TIPO_ALERTA_FICHADA_ELIMINADA = "fichada_eliminada"
TIPO_ALERTA_RECALCULO_DIVERGENTE = "recalculo_divergente"
TIPO_ALERTA_TURNO_MODIFICADO_POST_APROBACION = "turno_modificado_post_aprobacion"
TIPO_ALERTA_LIQUIDACION_AFECTADA_POR_CAMBIO_TURNO = "liquidacion_afectada_por_cambio_turno"


# ─── Modelos ──────────────────────────────────────────────────────────────


class RRHHHorasExtras(Base):
    """Bloque de horas extras por empleado/día/tipo."""

    __tablename__ = "rrhh_horas_extras"

    id = Column(Integer, primary_key=True, index=True)
    empleado_id = Column(
        Integer,
        ForeignKey("rrhh_empleados.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    fecha = Column(Date, nullable=False, index=True)

    # --- Cálculo ---
    fichada_entrada_id = Column(
        Integer,
        ForeignKey("rrhh_fichadas.id", ondelete="SET NULL"),
        nullable=True,
    )
    fichada_salida_id = Column(
        Integer,
        ForeignKey("rrhh_fichadas.id", ondelete="SET NULL"),
        nullable=True,
    )
    turno_esperado_minutos = Column(Integer, nullable=False, default=0)
    trabajado_minutos = Column(Integer, nullable=True)  # NULL si fichadas inválidas
    extras_minutos = Column(Integer, nullable=True)  # NULL si error_fichadas / pendiente

    # --- Clasificación ---
    tipo_dia = Column(String(20), nullable=False)  # TipoDiaHE
    porcentaje_recargo = Column(Numeric(5, 2), nullable=False)

    # --- Estado / workflow ---
    estado = Column(
        String(30),
        nullable=False,
        default=EstadoHE.DETECTADA.value,
        index=True,
    )
    error_tipo = Column(String(40), nullable=True)  # ErrorTipoHE — solo si estado='error_fichadas'

    # --- Auditoría aprobación / rechazo ---
    aprobado_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    aprobado_at = Column(DateTime(timezone=True), nullable=True)
    motivo_rechazo = Column(Text, nullable=True)

    # --- Auditoría reapertura (Fix revisión 1) ---
    reabierto_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    reabierto_at = Column(DateTime(timezone=True), nullable=True)
    motivo_reapertura = Column(Text, nullable=True)

    # --- Auditoría liquidación ---
    liquidacion_periodo = Column(String(6), nullable=True, index=True)  # YYYYMM
    liquidado_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    liquidado_at = Column(DateTime(timezone=True), nullable=True)

    # --- Origen ---
    generada_por = Column(
        String(10),
        nullable=False,
        default=GeneradaPorHE.SISTEMA.value,
    )
    generada_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)

    observaciones = Column(Text, nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # --- Relaciones ---
    empleado = relationship("RRHHEmpleado")
    fichada_entrada = relationship("RRHHFichada", foreign_keys=[fichada_entrada_id])
    fichada_salida = relationship("RRHHFichada", foreign_keys=[fichada_salida_id])
    aprobado_por = relationship("Usuario", foreign_keys=[aprobado_por_id])
    reabierto_por = relationship("Usuario", foreign_keys=[reabierto_por_id])
    liquidado_por = relationship("Usuario", foreign_keys=[liquidado_por_id])
    generada_por_usuario = relationship("Usuario", foreign_keys=[generada_por_id])
    historial = relationship(
        "RRHHHorasExtrasHistorial",
        back_populates="he",
        cascade="all, delete-orphan",
        order_by="RRHHHorasExtrasHistorial.created_at",
    )
    alertas = relationship(
        "RRHHHorasExtrasAlerta",
        back_populates="he",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint(
            "empleado_id",
            "fecha",
            "tipo_dia",
            name="uq_rrhh_he_emp_fecha_tipo",
        ),
        CheckConstraint(
            "estado IN ('pendiente_asignacion_turno','detectada','error_fichadas','aprobada','rechazada','liquidada')",
            name="ck_rrhh_he_estado_valido",
        ),
        CheckConstraint(
            "tipo_dia IN ('habil_50','sabado_100','domingo_100','feriado_100','manual')",
            name="ck_rrhh_he_tipo_dia_valido",
        ),
        CheckConstraint(
            "generada_por IN ('sistema','manual')",
            name="ck_rrhh_he_generada_por_valido",
        ),
        CheckConstraint(
            "porcentaje_recargo >= 0 AND porcentaje_recargo <= 500",
            name="ck_rrhh_he_porcentaje_rango",
        ),
        CheckConstraint(
            "(estado = 'error_fichadas' AND error_tipo IS NOT NULL) OR "
            "(estado <> 'error_fichadas' AND error_tipo IS NULL)",
            name="ck_rrhh_he_error_tipo_consistencia",
        ),
        CheckConstraint(
            "(estado = 'liquidada' AND liquidacion_periodo IS NOT NULL "
            "AND liquidado_por_id IS NOT NULL AND liquidado_at IS NOT NULL) "
            "OR (estado <> 'liquidada')",
            name="ck_rrhh_he_liquidacion_consistencia",
        ),
        Index("idx_rrhh_he_empleado_fecha", "empleado_id", "fecha"),
        Index("idx_rrhh_he_fecha_estado", "fecha", "estado"),
        Index("idx_rrhh_he_emp_fecha_estado", "empleado_id", "fecha", "estado"),
        Index(
            "idx_rrhh_he_liquidacion",
            "liquidacion_periodo",
            postgresql_where="liquidacion_periodo IS NOT NULL",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<RRHHHorasExtras(id={self.id}, emp={self.empleado_id}, "
            f"fecha='{self.fecha}', tipo='{self.tipo_dia}', "
            f"min={self.extras_minutos}, estado='{self.estado}')>"
        )


class RRHHHorasExtrasConfig(Base):
    """
    Configuración global del módulo HE (singleton, id=1).

    Revisión 2:
    - `dias_retencion_alertas` (Q4): cuántos días retener alertas leídas antes de
      purgarlas. Default 15.
    - `cap_dias_recalculo_manual` (Q2): tope máximo de días que puede abarcar el
      endpoint de recálculo manual. Default 90.
    """

    __tablename__ = "rrhh_horas_extras_config"

    id = Column(Integer, primary_key=True)  # siempre 1 (singleton)
    porcentaje_dia_habil = Column(Numeric(5, 2), nullable=False, default=50.00)
    porcentaje_sabado_pm = Column(Numeric(5, 2), nullable=False, default=100.00)
    porcentaje_domingo = Column(Numeric(5, 2), nullable=False, default=100.00)
    porcentaje_feriado = Column(Numeric(5, 2), nullable=False, default=100.00)
    hora_corte_sabado = Column(Time, nullable=False, default=time(13, 0))
    tolerancia_extras_minutos = Column(Integer, nullable=False, default=15)
    requiere_aprobacion = Column(Boolean, nullable=False, default=True)
    cron_activo = Column(Boolean, nullable=False, default=True)

    # --- Revisión 2 ---
    dias_retencion_alertas = Column(Integer, nullable=False, default=15)
    cap_dias_recalculo_manual = Column(Integer, nullable=False, default=90)

    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    actualizado_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)

    # --- Relaciones ---
    actualizado_por = relationship("Usuario")

    __table_args__ = (
        CheckConstraint("id = 1", name="ck_rrhh_he_config_singleton"),
        CheckConstraint(
            "porcentaje_dia_habil >= 0 AND porcentaje_sabado_pm >= 0 "
            "AND porcentaje_domingo >= 0 AND porcentaje_feriado >= 0",
            name="ck_rrhh_he_config_pct_no_neg",
        ),
        CheckConstraint(
            "tolerancia_extras_minutos >= 0 AND tolerancia_extras_minutos <= 240",
            name="ck_rrhh_he_config_tolerancia_rango",
        ),
        CheckConstraint(
            "dias_retencion_alertas >= 1",
            name="ck_rrhh_he_config_retencion_alertas",
        ),
        CheckConstraint(
            "cap_dias_recalculo_manual >= 1 AND cap_dias_recalculo_manual <= 366",
            name="ck_rrhh_he_config_cap_recalculo",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<RRHHHorasExtrasConfig(habil={self.porcentaje_dia_habil}%, "
            f"sab_pm={self.porcentaje_sabado_pm}%, "
            f"corte={self.hora_corte_sabado}, "
            f"tol={self.tolerancia_extras_minutos}min)>"
        )


class RRHHHorasExtrasHistorial(Base):
    """
    Audit trail append-only de cambios en un bloque de HE.

    Cada transición de estado o edición material persiste una fila con snapshot.
    NUNCA UPDATE/DELETE: solo INSERT. Sirve para reconstruir el bloque en cualquier
    momento del tiempo y para diagnóstico de divergencias post-aprobación.

    Acciones documentadas (campo `accion`):
      - detectada
      - recalculada
      - aprobada
      - rechazada
      - reabierta
      - liquidada
      - completada_fichada
      - descartada
      - edicion_porcentaje
      - edicion_observaciones
      - fichada_modificada_post_aprobacion
      - recalculo_por_cambio_turno
      - purga_alerta
    """

    __tablename__ = "rrhh_horas_extras_historial"

    id = Column(Integer, primary_key=True, index=True)
    he_id = Column(
        Integer,
        ForeignKey("rrhh_horas_extras.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    accion = Column(String(40), nullable=False)
    estado_anterior = Column(String(30), nullable=True)
    estado_nuevo = Column(String(30), nullable=False)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)  # NULL si cron
    motivo = Column(Text, nullable=True)
    snapshot = Column(JSONB, nullable=False)
    # snapshot JSON: { extras_minutos, trabajado_minutos, turno_esperado_minutos,
    #                  tipo_dia, porcentaje_recargo, estado, observaciones,
    #                  fichada_entrada_id, fichada_salida_id }
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # --- Relaciones ---
    he = relationship("RRHHHorasExtras", back_populates="historial")
    usuario = relationship("Usuario")

    __table_args__ = (
        Index("idx_rrhh_he_hist_he_created", "he_id", "created_at"),
        Index("idx_rrhh_he_hist_accion", "accion"),
    )

    def __repr__(self) -> str:
        return (
            f"<RRHHHorasExtrasHistorial(he_id={self.he_id}, "
            f"accion='{self.accion}', "
            f"{self.estado_anterior}→{self.estado_nuevo})>"
        )


class RRHHHorasExtrasAlerta(Base):
    """
    Alerta generada cuando una fichada (o turno) asociada a un bloque ya
    aprobado/liquidado es modificada o eliminada (potencial divergencia).

    El bloque congelado NO se recalcula automáticamente — la alerta queda como
    pendiente y un usuario con permiso debe decidir reabrir o ignorar.

    Tipos válidos (campo `tipo`, ver constantes módulo):
      - fichada_modificada
      - fichada_eliminada
      - recalculo_divergente
      - turno_modificado_post_aprobacion
      - liquidacion_afectada_por_cambio_turno  (revisión 2)
    """

    __tablename__ = "rrhh_horas_extras_alertas"

    id = Column(Integer, primary_key=True, index=True)
    he_id = Column(
        Integer,
        ForeignKey("rrhh_horas_extras.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tipo = Column(String(40), nullable=False)
    severidad = Column(String(10), nullable=False, default="warning")  # info|warning|critical
    mensaje = Column(Text, nullable=False)
    contexto = Column(JSONB, nullable=True)
    # contexto: { fichada_id, fichada_anterior_ts, fichada_nueva_ts,
    #             extras_minutos_actual, extras_minutos_recalculado, ... }
    leida_at = Column(DateTime(timezone=True), nullable=True)
    leida_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # --- Relaciones ---
    he = relationship("RRHHHorasExtras", back_populates="alertas")
    leida_por = relationship("Usuario")

    __table_args__ = (
        CheckConstraint(
            "severidad IN ('info','warning','critical')",
            name="ck_rrhh_he_alerta_severidad",
        ),
        Index(
            "idx_rrhh_he_alerta_no_leida",
            "he_id",
            postgresql_where="leida_at IS NULL",
        ),
        Index("idx_rrhh_he_alerta_created", "created_at"),
    )

    def __repr__(self) -> str:
        leida = "sí" if self.leida_at else "no"
        return f"<RRHHHorasExtrasAlerta(id={self.id}, he_id={self.he_id}, tipo='{self.tipo}', leida={leida})>"
