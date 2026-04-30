# Design: RRHH — Horas Extras (detección, aprobación y liquidación)

**Change**: `rrhh-horas-extras`
**Status**: Design
**Date**: 2026-04-30
**Mode**: hybrid (Engram + openspec/)
**Depends on**: proposal (Engram #188 + `openspec/changes/rrhh-horas-extras/proposal.md`) + revision-1 fixes

---

## 1. Architecture overview

### 1.1 Capa funcional

El módulo se ubica como **capa de detección + workflow** sobre el módulo RRHH ya existente:

```
┌─────────────────────────────────────────────────────────────────┐
│ Frontend (RRHHHorasExtras.jsx + RRHHSueldos.jsx)                │
└─────────────────────────────────────────────────────────────────┘
                            │ axios
┌─────────────────────────────────────────────────────────────────┐
│ Router rrhh_horas_extras.py  (CRUD + workflow + export)         │
└─────────────────────────────────────────────────────────────────┘
                            │
┌─────────────────────────────────────────────────────────────────┐
│ Service rrhh_horas_extras_service.py                            │
│  ├─ detectar_he_periodo / _calcular_he_dia                      │
│  ├─ aprobar / rechazar / reabrir / liquidar                     │
│  ├─ completar_fichada_faltante / descartar_dia                  │
│  ├─ notificar_fichada_modificada (hook)                         │
│  └─ _log_historial (append-only audit)                          │
└─────────────────────────────────────────────────────────────────┘
                  │                      │
       ┌──────────▼──────────┐  ┌────────▼─────────────────┐
       │ Modelos NUEVOS      │  │ Modelos EXISTENTES (read)│
       │ rrhh_horas_extras   │  │ rrhh_fichadas            │
       │ rrhh_horas_extras_  │  │ rrhh_empleado_horarios   │
       │   config            │  │ rrhh_horarios_config     │
       │ rrhh_horas_extras_  │  │ rrhh_horarios_excepciones│
       │   alertas           │  │ rrhh_presentismo_diario  │
       │ rrhh_horas_extras_  │  └──────────────────────────┘
       │   historial         │
       └─────────────────────┘
                  ▲
       ┌──────────┴──────────────────────────┐
       │ Cron 30 3 * * *                     │
       │ cron_rrhh_horas_extras.py           │
       │ + lockfile /var/run/pricing-app/    │
       └─────────────────────────────────────┘
```

### 1.2 Garantías de idempotencia

1. **Re-detección sobre bloque congelado** (`aprobada` / `rechazada` / `liquidada`): NO se sobreescribe. Si el cron detecta diferencias, persiste alerta en `rrhh_horas_extras_alertas` (Fix riesgo 1).
2. **Re-detección sobre bloque editable** (`detectada`, `pendiente_asignacion_turno`, `error_fichadas`): se reescribe `extras_minutos`, `trabajado_minutos`, `tipo_dia`, `porcentaje_recargo` con valores nuevos. La fila NO se borra (mantiene `id` para evitar romper FKs en historial).
3. **Constraint UNIQUE** `(empleado_id, fecha, tipo_dia)` permite que el cron use `INSERT ... ON CONFLICT DO UPDATE` (PostgreSQL upsert) cuando el estado lo permite.
4. **Cron lock**: lockfile en `/var/run/pricing-app/rrhh_he_cron.lock` (fallback `/tmp/rrhh_he_cron.lock`) garantiza una sola corrida simultánea (Fix riesgo 3).
5. **Hora de corrida**: `30 3 * * *` (decisión locked). 3:30 corre DESPUÉS de:
   - Hikvision sync `0 */2 * * *` (último slot del día anterior: 22:00).
   - Reconciliación CC `0 3 * * *` (03:00, ventana de ~30 min antes del HE).

### 1.3 Invariantes append-only de auditoría

- `rrhh_horas_extras_historial`: NUNCA se hace UPDATE/DELETE. Solo INSERT. Cada transición de estado y cada edición material genera una fila con snapshot.
- `rrhh_horas_extras_alertas`: solo el campo `leida_at` y `leida_por_id` se actualizan; el resto es inmutable.
- `rrhh_horas_extras.created_at`: server default + nunca se toca después.
- Permisos `aprobar` y `liquidar` marcados `es_critico=True`.

---

## 2. Data models

> Estilo: matching `backend/app/models/rrhh_fichada.py`. Tipos explícitos `String(N)`, índices nombrados, `__table_args__` con índices y constraints, `relationship()` al final, `__repr__` corto.

### 2.1 `rrhh_horas_extras` (bloque principal)

```python
"""
Bloque de horas extras detectado/aprobado/liquidado para un empleado en una fecha.

Granularidad: un registro por (empleado, fecha, tipo_dia). Si las HE de un día
cruzan el corte de sábado, se generan 2 filas distintas (habil_50 + sabado_100).

Lifecycle:
  detectada → aprobada → liquidada
  detectada → rechazada
  detectada → error_fichadas → detectada (al completar fichada)
  aprobada → detectada (al reabrir, requiere permiso aprobar + auditoría)
  pendiente_asignacion_turno → detectada (al asignar turno y recalcular)
"""

import enum

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
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


class TipoDiaHE(str, enum.Enum):
    HABIL_50 = "habil_50"
    SABADO_100 = "sabado_100"
    DOMINGO_100 = "domingo_100"
    FERIADO_100 = "feriado_100"
    MANUAL = "manual"


class EstadoHE(str, enum.Enum):
    PENDIENTE_ASIGNACION_TURNO = "pendiente_asignacion_turno"
    DETECTADA = "detectada"
    ERROR_FICHADAS = "error_fichadas"
    APROBADA = "aprobada"
    RECHAZADA = "rechazada"
    LIQUIDADA = "liquidada"


class GeneradaPorHE(str, enum.Enum):
    SISTEMA = "sistema"
    MANUAL = "manual"


class ErrorTipoHE(str, enum.Enum):
    FICHADAS_DESBALANCEADAS = "fichadas_desbalanceadas"
    SIN_FICHADA_ENTRADA = "sin_fichada_entrada"
    SIN_FICHADA_SALIDA = "sin_fichada_salida"
    SOLAPAMIENTO = "solapamiento"
    OTRO = "otro"


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
        Integer, ForeignKey("rrhh_fichadas.id", ondelete="SET NULL"), nullable=True
    )
    fichada_salida_id = Column(
        Integer, ForeignKey("rrhh_fichadas.id", ondelete="SET NULL"), nullable=True
    )
    turno_esperado_minutos = Column(Integer, nullable=False, default=0)
    trabajado_minutos = Column(Integer, nullable=True)  # NULL si fichadas inválidas
    extras_minutos = Column(Integer, nullable=True)  # NULL si error_fichadas / pendiente

    # --- Clasificación ---
    tipo_dia = Column(String(20), nullable=False)  # TipoDiaHE
    porcentaje_recargo = Column(Numeric(5, 2), nullable=False)

    # --- Estado/workflow ---
    estado = Column(String(30), nullable=False, default=EstadoHE.DETECTADA.value, index=True)
    error_tipo = Column(String(40), nullable=True)  # ErrorTipoHE — solo si estado='error_fichadas'

    # --- Auditoría aprobación/rechazo ---
    aprobado_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    aprobado_at = Column(DateTime(timezone=True), nullable=True)
    motivo_rechazo = Column(Text, nullable=True)

    # --- Auditoría reapertura (Fix revision-1) ---
    reabierto_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    reabierto_at = Column(DateTime(timezone=True), nullable=True)
    motivo_reapertura = Column(Text, nullable=True)

    # --- Auditoría liquidación ---
    liquidacion_periodo = Column(String(6), nullable=True, index=True)  # YYYYMM
    liquidado_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    liquidado_at = Column(DateTime(timezone=True), nullable=True)

    # --- Origen ---
    generada_por = Column(
        String(10), nullable=False, default=GeneradaPorHE.SISTEMA.value
    )
    generada_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)

    observaciones = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
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
            "empleado_id", "fecha", "tipo_dia", name="uq_rrhh_he_emp_fecha_tipo"
        ),
        CheckConstraint(
            "estado IN ('pendiente_asignacion_turno','detectada','error_fichadas',"
            "'aprobada','rechazada','liquidada')",
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
```

### 2.2 `rrhh_horas_extras_config` (singleton)

```python
class RRHHHorasExtrasConfig(Base):
    """Configuración global de horas extras (singleton, id=1)."""

    __tablename__ = "rrhh_horas_extras_config"

    id = Column(Integer, primary_key=True)  # siempre 1
    porcentaje_dia_habil = Column(Numeric(5, 2), nullable=False, default=50.00)
    porcentaje_sabado_pm = Column(Numeric(5, 2), nullable=False, default=100.00)
    porcentaje_domingo = Column(Numeric(5, 2), nullable=False, default=100.00)
    porcentaje_feriado = Column(Numeric(5, 2), nullable=False, default=100.00)
    hora_corte_sabado = Column(Time, nullable=False, default=time(13, 0))
    tolerancia_extras_minutos = Column(Integer, nullable=False, default=15)
    requiere_aprobacion = Column(Boolean, nullable=False, default=True)
    cron_activo = Column(Boolean, nullable=False, default=True)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    actualizado_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)

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
    )

    def __repr__(self) -> str:
        return (
            f"<RRHHHorasExtrasConfig(habil={self.porcentaje_dia_habil}%, "
            f"sab_pm={self.porcentaje_sabado_pm}%, "
            f"corte={self.hora_corte_sabado}, tol={self.tolerancia_extras_minutos}min)>"
        )
```

### 2.3 `rrhh_horas_extras_historial` (append-only, Fix riesgo 1)

```python
class RRHHHorasExtrasHistorial(Base):
    """
    Audit trail append-only de cambios en un bloque de HE.

    Cada transición de estado o edición material persiste una fila con snapshot.
    NUNCA UPDATE/DELETE: solo INSERT. Sirve para reconstruir el bloque en cualquier
    momento del tiempo y para diagnóstico de divergencias post-aprobación.
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
    # acciones: detectada, recalculada, aprobada, rechazada, reabierta,
    # liquidada, completada_fichada, descartada, edicion_porcentaje,
    # edicion_observaciones, fichada_modificada_post_aprobacion
    estado_anterior = Column(String(30), nullable=True)
    estado_nuevo = Column(String(30), nullable=False)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)  # NULL si cron
    motivo = Column(Text, nullable=True)
    snapshot = Column(JSONB, nullable=False)
    # snapshot JSON: { extras_minutos, trabajado_minutos, turno_esperado_minutos,
    #                  tipo_dia, porcentaje_recargo, estado, observaciones,
    #                  fichada_entrada_id, fichada_salida_id }
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    he = relationship("RRHHHorasExtras", back_populates="historial")
    usuario = relationship("Usuario")

    __table_args__ = (
        Index("idx_rrhh_he_hist_he_created", "he_id", "created_at"),
        Index("idx_rrhh_he_hist_accion", "accion"),
    )

    def __repr__(self) -> str:
        return (
            f"<RRHHHorasExtrasHistorial(he_id={self.he_id}, "
            f"accion='{self.accion}', {self.estado_anterior}→{self.estado_nuevo})>"
        )
```

### 2.4 `rrhh_horas_extras_alertas` (Fix riesgo 1)

```python
class RRHHHorasExtrasAlerta(Base):
    """
    Alerta generada cuando una fichada asociada a un bloque ya aprobado/liquidado
    es modificada o eliminada (potencial divergencia).

    El bloque congelado NO se recalcula automáticamente — el alerta queda como
    pendiente y un usuario con permiso debe decidir reabrir o ignorar.
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
    # tipo: fichada_modificada, fichada_eliminada, recalculo_divergente,
    #       turno_modificado_post_aprobacion
    severidad = Column(String(10), nullable=False, default="warning")  # info|warning|critical
    mensaje = Column(Text, nullable=False)
    contexto = Column(JSONB, nullable=True)
    # contexto: { fichada_id, fichada_anterior_ts, fichada_nueva_ts,
    #             extras_minutos_actual, extras_minutos_recalculado, ... }
    leida_at = Column(DateTime(timezone=True), nullable=True)
    leida_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

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
        return (
            f"<RRHHHorasExtrasAlerta(id={self.id}, he_id={self.he_id}, "
            f"tipo='{self.tipo}', leida={'sí' if self.leida_at else 'no'})>"
        )
```

> Imports adicionales requeridos: `from sqlalchemy.dialects.postgresql import JSONB` y `from datetime import time`.

---

## 3. Estados — máquina de estados

```
                    ┌──────────────────────────────────────────┐
                    │                                          │
                    │ pendiente_asignacion_turno               │
                    │ (empleado sin turno + fichadas)          │
                    └──────────────┬───────────────────────────┘
                                   │ asignar turno + recalcular
                                   ▼
                    ┌──────────────────────────┐
                    │      detectada           │◀──────┐
                    │  (cron o manual)         │       │
                    └─┬───────┬────────┬───────┘       │
                      │       │        │               │ completar
            aprobar   │       │        │ fichadas mal  │ fichada
                      ▼       │        ▼               │
              ┌──────────┐    │   ┌──────────────┐    │
              │ aprobada │    │   │error_fichadas├────┘
              └─┬─────┬──┘    │   └──────┬───────┘
                │     │       │          │ descartar
       liquidar │     │       │          │ día
                │     │       │          ▼
                ▼     │       │   ┌────────────┐
         ┌───────────┐│       │   │ rechazada  │
         │ liquidada ││reabrir│   └────────────┘
         └─────┬─────┘│       │          ▲
               │      ▼       │          │
               │  detectada◀──┘          │
               │  (sólo con permiso      │
               │   crítico .reabrir)     │
               │                         │
               └─────────────────────────┘
                rechazar (también desde aprobada con auditoría)
```

### 3.1 Reglas de transición

| Desde | Hacia | Permiso | Side effects |
|-------|-------|---------|--------------|
| (none) | `pendiente_asignacion_turno` | cron o `gestionar_horas_extras` | INSERT histórico `accion=detectada` |
| (none) | `detectada` | cron o `gestionar_horas_extras` | INSERT histórico |
| (none) | `error_fichadas` | cron | INSERT histórico + `error_tipo` requerido |
| `pendiente_asignacion_turno` | `detectada` | sistema (al asignar turno) o `gestionar_horas_extras` | recalcular |
| `detectada` | `aprobada` | `aprobar_horas_extras` (crítico) | setea `aprobado_por_id`, `aprobado_at` |
| `detectada` | `rechazada` | `aprobar_horas_extras` | requiere `motivo_rechazo` no vacío |
| `detectada` | `error_fichadas` | sistema (al editar fichada que rompe pares) | si re-cálculo lo detecta |
| `error_fichadas` | `detectada` | `gestionar_horas_extras` | tras `completar-fichada` válida |
| `error_fichadas` | `rechazada` | `aprobar_horas_extras` | tras `descartar-dia` |
| `aprobada` | `liquidada` | `liquidar_horas_extras` (crítico) | setea `liquidacion_periodo`, `liquidado_*` |
| `aprobada` | `detectada` (reabrir) | `aprobar_horas_extras` (crítico) | setea `reabierto_*`, **borra** `aprobado_*` |
| `aprobada` | `rechazada` | `aprobar_horas_extras` | requiere motivo |
| `liquidada` | `aprobada` (reapertura post-liquidación) | `liquidar_horas_extras` (crítico) | setea `reabierto_*`, **borra** `liquidacion_*` y `liquidado_*`. Solo si el período aún no fue cerrado contablemente — la UI muestra warning. |
| `rechazada` | `detectada` | `aprobar_horas_extras` | reabrir con motivo |

### 3.2 Reapertura post-liquidación

**Decisión**: SÍ se permite, pero solo con permiso `rrhh.liquidar_horas_extras` (que ya es crítico) + auditoría obligatoria. La razón: si la liquidación de sueldos se canceló o ajustó manualmente fuera del sistema, RRHH necesita corregir el bloque. La UI muestra warning explícito "Esta acción afecta una liquidación cerrada" antes de confirmar.

---

## 4. Migración Alembic

**Filename**: `backend/alembic/versions/20260430_create_rrhh_horas_extras.py`
**Revision ID**: `20260430_rrhh_horas_extras`
**Down revision**: última revisión activa (a verificar con `alembic heads` al implementar — al momento del design la más reciente RRHH es `20260316_create_rrhh_hikvision_users_cache`, pero la rama puede haber avanzado).

### 4.1 Operaciones (orden por FK)

```python
def upgrade():
    # 1. rrhh_horas_extras_config (singleton, sin FKs externas excepto usuarios)
    op.create_table(
        "rrhh_horas_extras_config",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("porcentaje_dia_habil", sa.Numeric(5, 2),
                  nullable=False, server_default="50.00"),
        sa.Column("porcentaje_sabado_pm", sa.Numeric(5, 2),
                  nullable=False, server_default="100.00"),
        sa.Column("porcentaje_domingo", sa.Numeric(5, 2),
                  nullable=False, server_default="100.00"),
        sa.Column("porcentaje_feriado", sa.Numeric(5, 2),
                  nullable=False, server_default="100.00"),
        sa.Column("hora_corte_sabado", sa.Time, nullable=False,
                  server_default="13:00:00"),
        sa.Column("tolerancia_extras_minutos", sa.Integer, nullable=False,
                  server_default="15"),
        sa.Column("requiere_aprobacion", sa.Boolean, nullable=False,
                  server_default="true"),
        sa.Column("cron_activo", sa.Boolean, nullable=False,
                  server_default="true"),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("actualizado_por_id", sa.Integer,
                  sa.ForeignKey("usuarios.id"), nullable=True),
        sa.CheckConstraint("id = 1", name="ck_rrhh_he_config_singleton"),
        # ... otros checks
    )
    # Seed singleton
    op.execute("""
        INSERT INTO rrhh_horas_extras_config (id) VALUES (1)
        ON CONFLICT (id) DO NOTHING;
    """)

    # 2. rrhh_horas_extras (tabla principal)
    op.create_table(
        "rrhh_horas_extras",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("empleado_id", sa.Integer,
                  sa.ForeignKey("rrhh_empleados.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("fecha", sa.Date, nullable=False, index=True),
        sa.Column("fichada_entrada_id", sa.Integer,
                  sa.ForeignKey("rrhh_fichadas.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("fichada_salida_id", sa.Integer,
                  sa.ForeignKey("rrhh_fichadas.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("turno_esperado_minutos", sa.Integer, nullable=False,
                  server_default="0"),
        sa.Column("trabajado_minutos", sa.Integer, nullable=True),
        sa.Column("extras_minutos", sa.Integer, nullable=True),
        sa.Column("tipo_dia", sa.String(20), nullable=False),
        sa.Column("porcentaje_recargo", sa.Numeric(5, 2), nullable=False),
        sa.Column("estado", sa.String(30), nullable=False,
                  server_default="detectada", index=True),
        sa.Column("error_tipo", sa.String(40), nullable=True),
        sa.Column("aprobado_por_id", sa.Integer,
                  sa.ForeignKey("usuarios.id"), nullable=True),
        sa.Column("aprobado_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("motivo_rechazo", sa.Text, nullable=True),
        sa.Column("reabierto_por_id", sa.Integer,
                  sa.ForeignKey("usuarios.id"), nullable=True),
        sa.Column("reabierto_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("motivo_reapertura", sa.Text, nullable=True),
        sa.Column("liquidacion_periodo", sa.String(6), nullable=True, index=True),
        sa.Column("liquidado_por_id", sa.Integer,
                  sa.ForeignKey("usuarios.id"), nullable=True),
        sa.Column("liquidado_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("generada_por", sa.String(10), nullable=False,
                  server_default="sistema"),
        sa.Column("generada_por_id", sa.Integer,
                  sa.ForeignKey("usuarios.id"), nullable=True),
        sa.Column("observaciones", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("empleado_id", "fecha", "tipo_dia",
                            name="uq_rrhh_he_emp_fecha_tipo"),
        # ... checks
    )
    op.create_index("idx_rrhh_he_empleado_fecha", "rrhh_horas_extras",
                    ["empleado_id", "fecha"])
    op.create_index("idx_rrhh_he_fecha_estado", "rrhh_horas_extras",
                    ["fecha", "estado"])
    op.create_index("idx_rrhh_he_emp_fecha_estado", "rrhh_horas_extras",
                    ["empleado_id", "fecha", "estado"])
    op.create_index("idx_rrhh_he_liquidacion", "rrhh_horas_extras",
                    ["liquidacion_periodo"],
                    postgresql_where=sa.text("liquidacion_periodo IS NOT NULL"))

    # 3. rrhh_horas_extras_historial
    op.create_table(
        "rrhh_horas_extras_historial",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("he_id", sa.Integer,
                  sa.ForeignKey("rrhh_horas_extras.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("accion", sa.String(40), nullable=False),
        sa.Column("estado_anterior", sa.String(30), nullable=True),
        sa.Column("estado_nuevo", sa.String(30), nullable=False),
        sa.Column("usuario_id", sa.Integer,
                  sa.ForeignKey("usuarios.id"), nullable=True),
        sa.Column("motivo", sa.Text, nullable=True),
        sa.Column("snapshot", postgresql.JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_rrhh_he_hist_he_created", "rrhh_horas_extras_historial",
                    ["he_id", "created_at"])
    op.create_index("idx_rrhh_he_hist_accion", "rrhh_horas_extras_historial",
                    ["accion"])

    # 4. rrhh_horas_extras_alertas
    op.create_table(
        "rrhh_horas_extras_alertas",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("he_id", sa.Integer,
                  sa.ForeignKey("rrhh_horas_extras.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("tipo", sa.String(40), nullable=False),
        sa.Column("severidad", sa.String(10), nullable=False,
                  server_default="warning"),
        sa.Column("mensaje", sa.Text, nullable=False),
        sa.Column("contexto", postgresql.JSONB, nullable=True),
        sa.Column("leida_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("leida_por_id", sa.Integer,
                  sa.ForeignKey("usuarios.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "idx_rrhh_he_alerta_no_leida", "rrhh_horas_extras_alertas",
        ["he_id"], postgresql_where=sa.text("leida_at IS NULL"),
    )
    op.create_index("idx_rrhh_he_alerta_created", "rrhh_horas_extras_alertas",
                    ["created_at"])

    # 5. Permisos (patrón 20260312_rrhh_permisos.py)
    PERMISOS_HE = [
        ("rrhh.ver_horas_extras", "Ver horas extras",
         "Acceso de lectura a bloques de horas extras y su historial",
         "rrhh", 130, False),
        ("rrhh.gestionar_horas_extras", "Gestionar horas extras",
         "Disparar detección manual, editar % recargo, completar fichadas, "
         "agregar bloques manuales", "rrhh", 131, False),
        ("rrhh.aprobar_horas_extras", "Aprobar horas extras",
         "Aprobar/rechazar/reabrir bloques de HE", "rrhh", 132, True),
        ("rrhh.liquidar_horas_extras", "Liquidar horas extras",
         "Marcar período como liquidado y reabrir post-liquidación",
         "rrhh", 133, True),
    ]
    for codigo, nombre, desc, cat, orden, critico in PERMISOS_HE:
        critico_str = "true" if critico else "false"
        op.execute(f"""
            INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden,
                                  es_critico, created_at)
            VALUES ('{codigo}', '{nombre}', '{desc}', '{cat}', {orden},
                    {critico_str}, NOW())
            ON CONFLICT (codigo) DO NOTHING;
        """)
    # ADMIN: todos. GERENTE: solo ver.
    ROL_PERMISOS = {
        "ADMIN": [c for c, *_ in PERMISOS_HE],
        "GERENTE": ["rrhh.ver_horas_extras"],
    }
    for rol, codigos in ROL_PERMISOS.items():
        for codigo in codigos:
            op.execute(f"""
                INSERT INTO roles_permisos_base (rol_id, permiso_id)
                SELECT r.id, p.id FROM roles r CROSS JOIN permisos p
                WHERE r.codigo = '{rol}' AND p.codigo = '{codigo}'
                ON CONFLICT DO NOTHING;
            """)


def downgrade():
    # Limpiar permisos asignados + catálogo
    codigos = "', '".join([
        "rrhh.ver_horas_extras", "rrhh.gestionar_horas_extras",
        "rrhh.aprobar_horas_extras", "rrhh.liquidar_horas_extras",
    ])
    op.execute(f"""
        DELETE FROM roles_permisos_base WHERE permiso_id IN (
            SELECT id FROM permisos WHERE codigo IN ('{codigos}')
        );
    """)
    op.execute(f"""
        DELETE FROM usuarios_permisos_override WHERE permiso_id IN (
            SELECT id FROM permisos WHERE codigo IN ('{codigos}')
        );
    """)
    op.execute(f"DELETE FROM permisos WHERE codigo IN ('{codigos}');")

    # Drop tablas en orden inverso
    op.drop_table("rrhh_horas_extras_alertas")
    op.drop_table("rrhh_horas_extras_historial")
    op.drop_index("idx_rrhh_he_liquidacion", table_name="rrhh_horas_extras")
    op.drop_index("idx_rrhh_he_emp_fecha_estado", table_name="rrhh_horas_extras")
    op.drop_index("idx_rrhh_he_fecha_estado", table_name="rrhh_horas_extras")
    op.drop_index("idx_rrhh_he_empleado_fecha", table_name="rrhh_horas_extras")
    op.drop_table("rrhh_horas_extras")
    op.drop_table("rrhh_horas_extras_config")
```

---

## 5. Schemas Pydantic v2 (inline en el router)

```python
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ─── Response básicos ─────────────────────────────────────────

class FichadaRefSchema(BaseModel):
    id: int
    timestamp: datetime
    tipo: str
    origen: str
    model_config = ConfigDict(from_attributes=True)


class HorasExtrasResponse(BaseModel):
    id: int
    empleado_id: int
    empleado_nombre: str = ""
    empleado_legajo: str = ""
    fecha: date
    turno_esperado_minutos: int
    trabajado_minutos: Optional[int] = None
    extras_minutos: Optional[int] = None
    tipo_dia: str
    porcentaje_recargo: Decimal
    estado: str
    error_tipo: Optional[str] = None
    aprobado_por_nombre: Optional[str] = None
    aprobado_at: Optional[datetime] = None
    motivo_rechazo: Optional[str] = None
    reabierto_por_nombre: Optional[str] = None
    reabierto_at: Optional[datetime] = None
    motivo_reapertura: Optional[str] = None
    liquidacion_periodo: Optional[str] = None
    liquidado_at: Optional[datetime] = None
    generada_por: str
    observaciones: Optional[str] = None
    fichada_entrada: Optional[FichadaRefSchema] = None
    fichada_salida: Optional[FichadaRefSchema] = None
    alertas_no_leidas: int = 0
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class HorasExtrasListResponse(BaseModel):
    items: list[HorasExtrasResponse] = []
    total: int = 0
    page: int = 1
    page_size: int = 50


# ─── Create / Update ──────────────────────────────────────────

class HorasExtrasCreate(BaseModel):
    """Bloque manual (sin disparar cron)."""
    empleado_id: int
    fecha: date
    extras_minutos: int = Field(ge=1, le=1440)
    tipo_dia: str = Field(pattern="^(habil_50|sabado_100|domingo_100|feriado_100|manual)$")
    porcentaje_recargo: Decimal = Field(ge=0, le=500)
    observaciones: Optional[str] = Field(default=None, max_length=2000)


class HorasExtrasUpdate(BaseModel):
    """Editar bloque (solo en estados editables: detectada, error_fichadas, pendiente_*)."""
    porcentaje_recargo: Optional[Decimal] = Field(default=None, ge=0, le=500)
    observaciones: Optional[str] = Field(default=None, max_length=2000)


# ─── Workflow actions ─────────────────────────────────────────

class AprobacionRequest(BaseModel):
    porcentaje_override: Optional[Decimal] = Field(default=None, ge=0, le=500)
    observaciones: Optional[str] = Field(default=None, max_length=2000)


class RechazoRequest(BaseModel):
    motivo: str = Field(min_length=3, max_length=2000)


class ReaperturaRequest(BaseModel):
    motivo: str = Field(min_length=3, max_length=2000)


class CompletarFichadaRequest(BaseModel):
    timestamp: datetime
    tipo: str = Field(pattern="^(entrada|salida)$")
    motivo: str = Field(min_length=3, max_length=500)


class DescartarDiaRequest(BaseModel):
    motivo: str = Field(min_length=3, max_length=2000)


class RecalcularRequest(BaseModel):
    fecha_desde: date
    fecha_hasta: date
    empleado_id: Optional[int] = None  # None = todos los activos

    @field_validator("fecha_hasta")
    @classmethod
    def _hasta_ge_desde(cls, v: date, info) -> date:
        desde = info.data.get("fecha_desde")
        if desde and v < desde:
            raise ValueError("fecha_hasta debe ser >= fecha_desde")
        return v


class BulkAprobarRequest(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=500)
    porcentaje_override: Optional[Decimal] = Field(default=None, ge=0, le=500)


class BulkRechazarRequest(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=500)
    motivo: str = Field(min_length=3, max_length=2000)


class LiquidacionRequest(BaseModel):
    periodo: str = Field(pattern="^[0-9]{6}$")  # YYYYMM
    ids: list[int] = Field(min_length=1, max_length=10000)


class LiquidacionResponse(BaseModel):
    periodo: str
    liquidados: int
    rechazados: int
    detalle_rechazos: list[dict[str, Any]] = []


# ─── Config ───────────────────────────────────────────────────

class HorasExtrasConfigSchema(BaseModel):
    porcentaje_dia_habil: Decimal = Field(ge=0, le=500)
    porcentaje_sabado_pm: Decimal = Field(ge=0, le=500)
    porcentaje_domingo: Decimal = Field(ge=0, le=500)
    porcentaje_feriado: Decimal = Field(ge=0, le=500)
    hora_corte_sabado: time
    tolerancia_extras_minutos: int = Field(ge=0, le=240)
    requiere_aprobacion: bool
    cron_activo: bool
    updated_at: Optional[datetime] = None
    actualizado_por_nombre: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


# ─── Alertas / Historial ──────────────────────────────────────

class AlertaResponse(BaseModel):
    id: int
    he_id: int
    tipo: str
    severidad: str
    mensaje: str
    contexto: Optional[dict[str, Any]] = None
    leida_at: Optional[datetime] = None
    leida_por_nombre: Optional[str] = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class HistorialEntryResponse(BaseModel):
    id: int
    he_id: int
    accion: str
    estado_anterior: Optional[str] = None
    estado_nuevo: str
    usuario_id: Optional[int] = None
    usuario_nombre: Optional[str] = None
    motivo: Optional[str] = None
    snapshot: dict[str, Any]
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)
```

---

## 6. Endpoints (router `backend/app/routers/rrhh_horas_extras.py`)

`prefix="/rrhh/horas-extras"`, `tags=["rrhh-horas-extras"]`.

| Método | Path | Permiso | Request | Response | Lógica |
|--------|------|---------|---------|----------|--------|
| GET | `/` | `rrhh.ver_horas_extras` | query: `empleado_id?`, `fecha_desde?`, `fecha_hasta?`, `estado?` (CSV), `tipo_dia?`, `con_alertas?`, `page`, `page_size` | `HorasExtrasListResponse` | Lista paginada con joins a empleado + count alertas. |
| GET | `/{id}` | `rrhh.ver_horas_extras` | – | `HorasExtrasResponse` (con fichadas + historial inline opt.) | Eager load `empleado`, `fichada_*`, alertas count. |
| POST | `/` | `rrhh.gestionar_horas_extras` | `HorasExtrasCreate` | `HorasExtrasResponse` | Crea bloque manual con `generada_por='manual'`, `estado='detectada'`. Log historial. |
| PUT | `/{id}` | `rrhh.gestionar_horas_extras` | `HorasExtrasUpdate` | `HorasExtrasResponse` | Solo editable si `estado in {detectada, error_fichadas, pendiente_*}`. Log historial. |
| PATCH | `/{id}/aprobar` | `rrhh.aprobar_horas_extras` | `AprobacionRequest` | `HorasExtrasResponse` | Solo desde `detectada`. Setea aprobado_*. Log historial. |
| PATCH | `/{id}/rechazar` | `rrhh.aprobar_horas_extras` | `RechazoRequest` | `HorasExtrasResponse` | Desde `detectada`/`aprobada`/`error_fichadas`. Motivo obligatorio. |
| PATCH | `/{id}/reabrir` | `rrhh.aprobar_horas_extras` (o `liquidar_*` si estaba liquidada) | `ReaperturaRequest` | `HorasExtrasResponse` | Desde `aprobada` → `detectada`. Desde `liquidada` → `aprobada` (requiere permiso liquidar). Setea `reabierto_*`, limpia campos del estado dejado atrás. |
| POST | `/bulk/aprobar` | `rrhh.aprobar_horas_extras` | `BulkAprobarRequest` | `{aprobados: int, fallidos: list}` | Loop con audit individual. Transacción única. |
| POST | `/bulk/rechazar` | `rrhh.aprobar_horas_extras` | `BulkRechazarRequest` | `{rechazados: int, fallidos: list}` | Idem. |
| POST | `/{id}/completar-fichada` | `rrhh.gestionar_horas_extras` | `CompletarFichadaRequest` | `HorasExtrasResponse` | Solo desde `error_fichadas`. Crea `RRHHFichada(origen='manual', motivo_manual=motivo)` y recalcula el día. |
| POST | `/{id}/descartar-dia` | `rrhh.aprobar_horas_extras` | `DescartarDiaRequest` | `HorasExtrasResponse` | Desde `error_fichadas` → `rechazada`. |
| POST | `/recalcular` | `rrhh.gestionar_horas_extras` | `RecalcularRequest` | `{procesados: int, creados: int, actualizados: int, alertas: int}` | Trigger manual del cron sobre rango. |
| POST | `/liquidar` | `rrhh.liquidar_horas_extras` | `LiquidacionRequest` | `LiquidacionResponse` | Marca `aprobada` → `liquidada` para los IDs del período. Rechaza si hay IDs en estado distinto de `aprobada`. |
| GET | `/alertas` | `rrhh.ver_horas_extras` | query: `solo_no_leidas`, `severidad?`, `page` | `{items: list[AlertaResponse], total}` | Lista alertas (default solo no-leídas). |
| PATCH | `/alertas/{id}/leida` | `rrhh.ver_horas_extras` | – | `AlertaResponse` | Marca `leida_at`/`leida_por_id`. |
| GET | `/historial/{he_id}` | `rrhh.ver_horas_extras` | – | `list[HistorialEntryResponse]` | Historial completo del bloque ordenado cronológicamente. |
| GET | `/config` | `rrhh.ver_horas_extras` | – | `HorasExtrasConfigSchema` | Singleton `id=1`. |
| PUT | `/config` | `rrhh.config` (existente) | `HorasExtrasConfigSchema` | `HorasExtrasConfigSchema` | Update singleton + setea `actualizado_por_id`. |
| GET | `/exportar` | `rrhh.ver_horas_extras` | query: `periodo` (YYYYMM) o `fecha_desde`+`fecha_hasta`, `estado?` | `StreamingResponse` Excel | Export con columnas: legajo, nombre, fecha, tipo_dia, minutos_extras, porcentaje, estado, observaciones, motivo_rechazo. Usa `openpyxl`, build BytesIO en memoria → NO es long-lived (puede usar `get_current_user`). |

> Todos usan `Depends(get_current_user)` (no SSE/streaming long-lived). Helper `_check_permiso(db, user, codigo)` reutilizado del patrón de `rrhh_horarios.py` (copiado al router nuevo).

---

## 7. Service layer (`backend/app/services/rrhh_horas_extras_service.py`)

```python
class HorasExtrasService:
    """
    Lógica de negocio del módulo HE: detección, workflow, auditoría.

    Convenciones:
    - Todo método que modifica estado del bloque DEBE llamar a `_log_historial`
      ANTES del commit para garantizar atomicidad.
    - Métodos `aprobar_*`, `rechazar_*`, etc. NO chequean permisos — eso es
      responsabilidad del router. El service confía que el caller validó.
    - Idempotencia: si el bloque está congelado, los métodos de detección
      generan alerta en lugar de sobreescribir.
    """

    def __init__(self, db: Session):
        self.db = db
        self._config: RRHHHorasExtrasConfig | None = None

    # ─── Detección ─────────────────────────────────────────────

    def detectar_he_periodo(
        self, fecha_desde: date, fecha_hasta: date,
        empleado_ids: list[int] | None = None,
    ) -> dict[str, int]:
        """
        Detecta HE para todos los empleados activos en el rango.

        Estrategia: itera (empleado, fecha) y delega a `_calcular_he_dia`.
        Idempotente: respeta bloques congelados.

        Returns:
            {procesados, creados, actualizados, alertas, errores}
        """

    def _calcular_he_dia(
        self, empleado: RRHHEmpleado, fecha: date,
    ) -> list[RRHHHorasExtras]:
        """
        Calcula HE de un empleado para un día específico.

        Steps:
          1. Cargar fichadas del empleado en `fecha` (TZ ART).
          2. Validar pares entrada/salida → si inválido: estado='error_fichadas'
             con `error_tipo` apropiado.
          3. Obtener turnos asignados (RRHHEmpleadoHorario) que cubran ese día
             (filtro por `dias_semana`).
          4. Sumar `turno_esperado_minutos` de todos los turnos del día.
          5. Calcular `trabajado_minutos` (lógica reutilizada de
             `rrhh_reportes_service.horas_trabajadas` pero a nivel día).
          6. Si trabajado > teorico + tolerancia_extras_minutos:
             a. Clasificar tipo_dia (puede devolver split por corte sábado).
             b. Para cada tramo, INSERT/UPSERT bloque.
          7. Si presentismo del día es vacaciones/art/licencia: descartar
             todos los bloques con observación automática.
          8. Si bloque YA existe en estado congelado y hay diferencia:
             generar alerta `recalculo_divergente`.

        Returns:
            Lista de bloques afectados (creados o actualizados).
        """

    def _clasificar_tipo_dia(
        self, fecha: date,
        trabajado_minutos: int,
        primera_entrada: datetime,
    ) -> list[tuple[str, int, Decimal]]:
        """
        Clasifica el día y posiblemente lo divide por corte sábado.

        Returns:
            Lista de tuplas (tipo_dia, minutos_extras_tramo, porcentaje).
            En 99% de casos: [(tipo, minutos, pct)].
            En sábado cruzando corte: [('habil_50', m1, 50), ('sabado_100', m2, 100)].
        """

    def _validar_fichadas_dia(
        self, fichadas: list[RRHHFichada],
    ) -> tuple[bool, str | None]:
        """
        Valida que las fichadas formen pares entrada/salida coherentes.

        Returns:
            (válido, error_tipo). error_tipo en ErrorTipoHE si inválido.
        """

    # ─── Workflow ──────────────────────────────────────────────

    def aprobar_bloque(
        self, he_id: int, usuario: Usuario,
        porcentaje_override: Decimal | None = None,
        observaciones: str | None = None,
    ) -> RRHHHorasExtras:
        """Transición detectada → aprobada. Lanza HTTPException si estado inválido."""

    def rechazar_bloque(
        self, he_id: int, usuario: Usuario, motivo: str,
    ) -> RRHHHorasExtras:
        """Transición desde detectada/aprobada/error_fichadas → rechazada."""

    def reabrir_bloque(
        self, he_id: int, usuario: Usuario, motivo: str,
    ) -> RRHHHorasExtras:
        """
        Transición:
          - aprobada → detectada (limpia aprobado_*)
          - liquidada → aprobada (limpia liquidacion_*, requiere permiso liquidar)
          - rechazada → detectada
        Setea reabierto_*. Recalcular siempre se hace explícitamente después
        si el usuario lo pide.
        """

    def completar_fichada_faltante(
        self, he_id: int, usuario: Usuario, timestamp: datetime,
        tipo: str, motivo: str,
    ) -> RRHHHorasExtras:
        """
        Solo desde error_fichadas. Crea RRHHFichada manual + recalcula el día.
        Si el recálculo deja todo válido → estado pasa a 'detectada'.
        """

    def descartar_dia(
        self, he_id: int, usuario: Usuario, motivo: str,
    ) -> RRHHHorasExtras:
        """error_fichadas → rechazada con motivo."""

    def liquidar_periodo(
        self, periodo: str, ids: list[int], usuario: Usuario,
    ) -> dict[str, Any]:
        """
        Marca bloques 'aprobada' como 'liquidada' con liquidacion_periodo=YYYYMM.
        Rechaza con detalle los IDs en estado distinto de 'aprobada'.
        Una sola transacción.
        """

    # ─── Audit & hooks ─────────────────────────────────────────

    def _log_historial(
        self, he: RRHHHorasExtras, accion: str,
        estado_anterior: str | None, estado_nuevo: str,
        usuario_id: int | None, motivo: str | None = None,
    ) -> RRHHHorasExtrasHistorial:
        """
        Append-only insert. Snapshot completo del bloque al momento del cambio.
        DEBE llamarse ANTES del db.commit() del cambio para garantizar atomicidad.
        """

    def notificar_fichada_modificada(
        self, fichada_id: int, evento: str = "modificada",
    ) -> list[RRHHHorasExtrasAlerta]:
        """
        Hook llamado cuando una RRHHFichada es UPDATE/DELETE.

        Busca bloques HE que referencian fichada_entrada_id o fichada_salida_id
        igual al fichada_id Y están en estado congelado (aprobada/liquidada/
        rechazada). Para cada uno:
          1. Re-calcula el día sin persistir cambios (dry-run).
          2. Si hay diferencia material en extras_minutos: crea alerta
             `recalculo_divergente` con contexto {actual, recalculado}.
          3. NO modifica el bloque.

        Para bloques en estado editable (detectada/error_fichadas/pendiente_*),
        invalida y dispara recálculo real.
        """

    def _get_config(self) -> RRHHHorasExtrasConfig:
        """Carga + cachea singleton id=1."""
```

### 7.1 Reutilización del cálculo de horas trabajadas

`rrhh_reportes_service.horas_trabajadas` ya implementa pares entrada/salida. Decisión: **NO** reutilizamos directamente — hacemos un helper privado `_minutos_trabajados_dia(fichadas)` en el service de HE, porque el de reportes opera en agregados mensuales y mezcla concerns. Sí copiamos el algoritmo de pares (extraerlo a `app/utils/rrhh_fichadas_pares.py` queda como refactor opcional fuera de este change).

---

## 8. Cron script (`backend/app/scripts/cron_rrhh_horas_extras.py`)

### 8.1 Estructura

```python
"""
Cron diario de detección de horas extras.

Procesa D-1 (ayer) completo para todos los empleados activos.
Lockfile evita corridas simultáneas.

Cron entry:
  30 3 * * * cd /var/www/html/pricing-app/backend && \
    /var/www/html/pricing-app/backend/venv/bin/python \
    -m app.scripts.cron_rrhh_horas_extras \
    >> /var/log/pricing-app/rrhh_he_cron.log 2>&1

Exit codes:
  0 — OK
  1 — Lock activo (otra corrida en curso)
  2 — Error fatal
  3 — Cron deshabilitado por config (cron_activo=false)
"""
import os
import sys
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path

LOCK_PATH_PRIMARY = Path("/var/run/pricing-app/rrhh_he_cron.lock")
LOCK_PATH_FALLBACK = Path("/tmp/rrhh_he_cron.lock")


@contextmanager
def _file_lock():
    """Lockfile flock. Falla rápido si ya hay corrida activa."""
    import fcntl
    path = LOCK_PATH_PRIMARY if LOCK_PATH_PRIMARY.parent.exists() else LOCK_PATH_FALLBACK
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        raise SystemExit(1)
    try:
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def main() -> int:
    from app.core.database import SessionLocal
    from app.core.logging import get_logger
    from app.models.rrhh_horas_extras import RRHHHorasExtrasConfig
    from app.services.rrhh_horas_extras_service import HorasExtrasService

    logger = get_logger("scripts.cron_rrhh_horas_extras")
    ayer = date.today() - timedelta(days=1)

    with _file_lock():
        db = SessionLocal()
        try:
            cfg = db.query(RRHHHorasExtrasConfig).filter_by(id=1).one_or_none()
            if cfg is None or not cfg.cron_activo:
                logger.warning("Cron HE deshabilitado por config (cron_activo=false)")
                return 3

            service = HorasExtrasService(db)
            result = service.detectar_he_periodo(ayer, ayer)
            db.commit()
            logger.info("Cron HE completado: fecha=%s result=%s", ayer, result)
            return 0
        except Exception:
            db.rollback()
            logger.exception("Error fatal en cron HE")
            return 2
        finally:
            db.close()


if __name__ == "__main__":
    sys.exit(main())
```

### 8.2 Operacional

- Bootstrap path como en otros scripts (sys.path insertion + .env load) — mismo patrón que `sync_hikvision_fichadas.py`.
- Lockfile con `flock` no-bloqueante: si ya hay otra corrida, sale con exit 1 (no acumula colas).
- Logger via `app.core.logging.get_logger`.
- Crontab entry agregado al runbook de deploy (no se autoinstala).

---

## 9. Hook a fichadas modificadas (Fix riesgo 1)

### 9.1 Decisión técnica: SQLAlchemy event listener + idempotencia

**Choice**: SQLAlchemy `event.listen` sobre `RRHHFichada` con `after_update` y `after_delete`. Registrado en `app/models/__init__.py` o en un módulo `app/events/rrhh_he_hooks.py` importado al startup desde `main.py`.

**Implementación**:

```python
# backend/app/events/rrhh_he_hooks.py
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.models.rrhh_fichada import RRHHFichada


def _enqueue_he_check(session: Session, fichada_id: int, evento: str) -> None:
    """Encola la verificación al final de la transacción para no fallar el flush."""
    from app.services.rrhh_horas_extras_service import HorasExtrasService

    pending = session.info.setdefault("_rrhh_he_pending", [])
    pending.append((fichada_id, evento))


@event.listens_for(RRHHFichada, "after_update")
def _on_fichada_update(mapper, connection, target):
    # connection no es Session; capturamos id + evento y procesamos en after_commit
    session = Session.object_session(target)
    if session is not None:
        _enqueue_he_check(session, target.id, "modificada")


@event.listens_for(RRHHFichada, "after_delete")
def _on_fichada_delete(mapper, connection, target):
    session = Session.object_session(target)
    if session is not None:
        _enqueue_he_check(session, target.id, "eliminada")


@event.listens_for(Session, "after_commit")
def _flush_he_pending(session: Session):
    pending = session.info.pop("_rrhh_he_pending", None)
    if not pending:
        return
    # Re-abrimos sub-sesión para no mezclar con la sesión principal ya commiteada.
    from app.core.database import SessionLocal
    from app.services.rrhh_horas_extras_service import HorasExtrasService

    sub = SessionLocal()
    try:
        service = HorasExtrasService(sub)
        for fichada_id, evento in pending:
            service.notificar_fichada_modificada(fichada_id, evento=evento)
        sub.commit()
    except Exception:
        sub.rollback()
        # logger de evento — NUNCA propagar; el commit principal ya pasó.
    finally:
        sub.close()
```

**Alternativas consideradas**:

| Alternativa | Pros | Contras |
|-------------|------|---------|
| Llamada manual desde routers que editan fichadas | Explícito, fácil de debuggear | Riesgo de olvido (si aparece un nuevo endpoint que edita fichadas y no se acuerda invocar el hook → divergencia silenciosa). Hay 3+ paths que crean/editan fichadas (`rrhh_horarios`, `rrhh_fichaje_mobile`, scripts). |
| **SQLAlchemy event listener** (elegida) | Captura TODA modificación sin importar el caller. Imposible olvidarlo. | Acoplamiento implícito; debugger debe saber que existe. Mitigación: documentar en `app/events/__init__.py` README + comentar en modelo. |
| Trigger PostgreSQL | Captura incluso updates fuera de SQLAlchemy | Lógica del hook es Python (recálculo) → necesitaríamos un job cola. Over-engineering para este caso. |

**Por qué `after_commit` y no `after_update`**: si el listener corriera dentro del flush, un fallo del recálculo abortaría la edición original de la fichada, lo cual es inaceptable. Postergar a `after_commit` y usar sub-sesión separada garantiza desacoplamiento. La alerta puede llegar 1-2s después de la edición — tolerable.

**Idempotencia**: `notificar_fichada_modificada` chequea por `(he_id, tipo, contexto.fichada_id)` antes de insertar alerta para no duplicar.

---

## 10. Frontend design

### 10.1 Página principal

**Archivo**: `frontend/src/pages/RRHHHorasExtras.jsx`
**Hooks**: `useState`, `useEffect`, `usePermisos`, `useNavigate`.
**Layout**: header con KPIs (pendientes / con alertas / aprobadas mes / liquidadas mes) + tabs + tabla + sidebar de filtros.

```
┌─────────────────────────────────────────────────────────────────┐
│ RRHH › Horas Extras            [⚙ Config] [↻ Detectar] [↗ XLSX] │
├─────────────────────────────────────────────────────────────────┤
│  Pendientes (12)  │  Con alertas (3)  │  Aprobadas (47)  │ ...  │
├─────────────────────────────────────────────────────────────────┤
│ Filtros: [Empleado] [Fecha desde] [Fecha hasta] [Tipo día] [⌕] │
├─────────────────────────────────────────────────────────────────┤
│ Tabs: Pendientes | Con alertas | Aprobadas | Rechazadas | Liq.  │
├─────────────────────────────────────────────────────────────────┤
│ ☐ Legajo │ Empleado │ Fecha │ Tipo │ Min │ %  │ Estado │ Acciones│
│ ☐ 0123   │ Pérez    │ 04/29 │ háb. │ 120 │ 50 │ deet.  │ ✓ ✗ ⓘ  │
│ ...                                                              │
├─────────────────────────────────────────────────────────────────┤
│ Selección masiva: [Aprobar selección] [Rechazar...] [%...]      │
└─────────────────────────────────────────────────────────────────┘
```

### 10.2 Tabs y filtros

| Tab | Filtro estado backend |
|-----|----------------------|
| Pendientes | `detectada,error_fichadas,pendiente_asignacion_turno` |
| Con alertas | `con_alertas=true` (cualquier estado, alertas no leídas > 0) |
| Aprobadas | `aprobada` |
| Rechazadas | `rechazada` |
| Liquidadas | `liquidada` |

### 10.3 Componentes auxiliares (mismo directorio)

| Componente | Responsabilidad |
|------------|----------------|
| `RRHHHorasExtras.jsx` | Page container + tabs + paginación |
| `HEFiltrosBar.jsx` | Form de filtros |
| `HETabla.jsx` | Tabla con selección + edición inline de % |
| `HEModalAprobar.jsx` | Modal con override % opcional + observaciones |
| `HEModalRechazar.jsx` | Modal con motivo obligatorio (textarea) |
| `HEModalReabrir.jsx` | Modal con motivo + warning si era liquidada |
| `HEModalCompletarFichada.jsx` | Form: timestamp + tipo + motivo |
| `HEModalDescartarDia.jsx` | Form: motivo |
| `HEModalConfig.jsx` | Settings: porcentajes, corte sábado, tolerancia, cron toggle |
| `HEModalHistorial.jsx` | Lista cronológica del historial del bloque |
| `HEPanelAlertas.jsx` | Drawer lateral con alertas no leídas |

### 10.4 CSS Modules

**Archivo**: `frontend/src/pages/RRHHHorasExtras.module.css`

Reglas:
- 100% design tokens (`var(--color-primary)`, `var(--spacing-md)`, etc.).
- NO hardcoded colors / sizes.
- Estados visuales:
  - `detectada` → neutral
  - `error_fichadas` → warning con icono
  - `pendiente_asignacion_turno` → info con icono
  - `aprobada` → success ghost
  - `rechazada` → danger ghost
  - `liquidada` → success solid
  - badges de alertas no leídas → critical chip
- Soporte modo oscuro vía tokens.
- Tabla con `position: sticky` en header.

### 10.5 API methods (`frontend/src/services/api.js`)

```javascript
// Append al export default existente
export const horasExtrasApi = {
  list: (params) => api.get('/rrhh/horas-extras', { params }),
  get: (id) => api.get(`/rrhh/horas-extras/${id}`),
  create: (data) => api.post('/rrhh/horas-extras', data),
  update: (id, data) => api.put(`/rrhh/horas-extras/${id}`, data),
  aprobar: (id, body) => api.patch(`/rrhh/horas-extras/${id}/aprobar`, body),
  rechazar: (id, body) => api.patch(`/rrhh/horas-extras/${id}/rechazar`, body),
  reabrir: (id, body) => api.patch(`/rrhh/horas-extras/${id}/reabrir`, body),
  bulkAprobar: (body) => api.post('/rrhh/horas-extras/bulk/aprobar', body),
  bulkRechazar: (body) => api.post('/rrhh/horas-extras/bulk/rechazar', body),
  completarFichada: (id, body) =>
    api.post(`/rrhh/horas-extras/${id}/completar-fichada`, body),
  descartarDia: (id, body) =>
    api.post(`/rrhh/horas-extras/${id}/descartar-dia`, body),
  recalcular: (body) => api.post('/rrhh/horas-extras/recalcular', body),
  liquidar: (body) => api.post('/rrhh/horas-extras/liquidar', body),
  alertasList: (params) => api.get('/rrhh/horas-extras/alertas', { params }),
  alertaMarcarLeida: (id) =>
    api.patch(`/rrhh/horas-extras/alertas/${id}/leida`),
  historial: (heId) => api.get(`/rrhh/horas-extras/historial/${heId}`),
  configGet: () => api.get('/rrhh/horas-extras/config'),
  configPut: (body) => api.put('/rrhh/horas-extras/config', body),
  exportarXlsx: (params) =>
    api.get('/rrhh/horas-extras/exportar', { params, responseType: 'blob' }),
};
```

### 10.6 Integración con `RRHHSueldos.jsx`

- Sueldos consume `horasExtrasApi.list({ estado: 'liquidada', periodo: 'YYYYMM' })`.
- Se agrega panel "Horas extras liquidadas del período" con totales por empleado.
- `RRHHSueldos` NO modifica el módulo HE — solo lee. Si necesita modificar, debe redirigir al usuario al módulo.

### 10.7 Routing y Sidebar

- `App.jsx`: nueva ruta `/rrhh/horas-extras` lazy-loaded.
- `Sidebar.jsx`: entrada "Horas Extras" dentro de sección RRHH, gateada por `usePermisos().tienePermiso('rrhh.ver_horas_extras')`.

---

## 11. Tests recomendados (a desarrollar en sdd-tasks)

> Manual testing en la app no tiene runner — listar igual los casos por capability para que `sdd-tasks` los convierta en items verificables (curl/UI).

### 11.1 Detección (service)
- Caso 1 proposal: 8→13, 15→19 (fichado pausa) → 0 HE.
- Caso 2 proposal: 8→19 (sin pausa) → 2h HE.
- Caso 3 proposal: 8→13, 15→20 → 1h HE.
- Sábado 11→15 con corte 13:00 → 2 bloques (`habil_50` 2h + `sabado_100` 2h).
- Empleado sin turno + fichadas → `pendiente_asignacion_turno`, `turno_esperado=0`.
- Día con presentismo `vacaciones` + fichadas → no se crea bloque (observación auto).
- Fichadas impares (3 fichadas) → `error_fichadas` con `error_tipo=fichadas_desbalanceadas`.
- HE bajo tolerancia (5min con tol=15) → no se persiste.
- Re-detección sobre `aprobada` con diff → genera alerta, NO sobreescribe.
- Re-detección sobre `detectada` con diff → sobreescribe + log historial.

### 11.2 Workflow (router)
- Aprobar bloque `detectada` → `aprobada` + audit completo.
- Aprobar bloque `aprobada` → 409 Conflict.
- Rechazar sin motivo → 422 validation.
- Reabrir `aprobada` → `detectada` con `reabierto_*` setteado y `aprobado_*` nullificado.
- Reabrir `liquidada` sin permiso `liquidar` → 403.
- Bulk aprobar 50 IDs mixtos → audit individual, no rollback global por uno fallido.
- Liquidar período con IDs en estado `detectada` → response detalla rechazos.
- Liquidar período: bloque queda con `liquidacion_periodo='YYYYMM'`.

### 11.3 Hook fichadas
- Editar fichada referenciada por bloque `aprobada` → 1 alerta `recalculo_divergente`.
- Eliminar fichada → alerta `fichada_eliminada`.
- Editar fichada referenciada por bloque `detectada` → recálculo automático, no alerta.
- Doble edición rápida → no duplica alertas (idempotencia).

### 11.4 Cron
- Lockfile activo → exit 1 sin tocar DB.
- `cron_activo=false` → exit 3, log warning, no procesa.
- Corrida feliz → exit 0, log con counts, no duplica si rerun.

### 11.5 Frontend (smoke)
- Tabla muestra todos los estados con su badge correcto.
- Modal aprobar respeta override de %.
- Toggle dark mode no rompe paleta.
- Filtro por rango de fechas funciona.
- Export XLSX descarga archivo válido.

---

## 12. Riesgos residuales y mitigación

| Riesgo | Probabilidad | Impacto | Mitigación |
|--------|--------------|---------|------------|
| **Race condition cron + recalcular manual simultáneo**: si admin dispara `/recalcular` mientras el cron de las 3:30 corre, ambos pueden intentar UPSERT sobre la misma fila. | Baja | Datos inconsistentes momentáneos | Lockfile cron + endpoint `/recalcular` chequea lock antes de proceder (devolvería 409 si lock activo). Documentar en docstring del endpoint. |
| **Cambio de zona horaria del servidor**: el cron asume que `date.today()` es ART. Si el server se migra a UTC, "ayer" cambia. | Media | HE detectadas para fecha incorrecta | Forzar TZ explícita en cron (`from app.services.rrhh_hikvision_client import ART_TZ`) y usar `datetime.now(ART_TZ).date() - timedelta(days=1)`. |
| **Fichadas tardías post-aprobación**: empleado ficha salida 4h después del cierre, llega cuando el bloque ya está aprobado. | Media | Bloque congelado no refleja realidad | Hook de fichada modificada cubre UPDATE/DELETE pero NO INSERT post-bloque. Mitigación: extender hook a `after_insert` filtrando por `timestamp < hoy - 1d`. Decisión: incluido en service `notificar_fichada_modificada(evento='insertada_tardía')`. |
| **Volumen de alertas no leídas crece sin acotar** | Baja | UX deteriorada en panel alertas | Endpoint `GET /alertas` paginado por default 50. Cron de mantenimiento (futuro, no en este change) puede archivar alertas leídas > 90 días. |
| **Performance en `/recalcular` sobre rangos grandes** (todo el mes × 50 empleados = 1500 días) | Media | Timeout HTTP | Endpoint procesa en transacción única; si el rango supera N días o M empleados, devolver 413 con sugerencia de partir por semanas. Threshold a fijar en config (`max_dias_recalculo_manual=31`, `max_empleados_recalculo_manual=100`). |
| **JSONB snapshots crecen sin acotar** (1 fila historial × cada cambio × cada bloque) | Baja | Tabla pesada en años | Snapshot incluye solo campos materiales (no `created_at`/`updated_at` nested). Eventualmente partition por año. Fuera de scope en este change. |
| **Permisos críticos otorgados por error** | Baja | Aprobaciones/liquidaciones indebidas | Patrón existente `es_critico=True` requiere confirmación al asignar. Cubierto. |
| **Solapamiento de turnos del mismo empleado en un día** (M:N puede generar duplicados) | Media | `turno_esperado_minutos` inflado | `_calcular_he_dia` debe deduplicar por `horario_config_id` antes de sumar minutos. |
| **`hora_corte_sabado` cambiada a mitad de período** | Baja | Bloques históricos quedan con clasificación vieja | Cambio config NO recalcula `aprobada`/`liquidada` (locked). Sí afecta `detectada` futuras. Documentado en UI de config con warning. |

---

## 13. Open questions

- [ ] **Idioma del export XLSX**: ¿headers en español o spanglish (legajo, name, date)? — asumir español, confirmar con usuario en sdd-tasks.
- [ ] **Threshold `max_dias_recalculo_manual` y `max_empleados_recalculo_manual`**: defaults razonables 31/100, pero confirmar con el dueño del producto en `sdd-tasks`.
- [ ] **¿Habilitar recálculo automático al crear/editar `RRHHEmpleadoHorario`?** El proposal lo menciona como "futuro/manual"; si se quiere auto, agregar otro event listener. Decisión postergada a `sdd-tasks` o cambio futuro.
- [ ] **Limpieza de alertas leídas**: cron de purga > 90 días — fuera de scope, abrir change futuro `rrhh-horas-extras-mantenimiento` si se necesita.

---

## 14. Resumen de decisiones (locked-in)

1. 4 tablas: `rrhh_horas_extras`, `rrhh_horas_extras_config`, `rrhh_horas_extras_historial`, `rrhh_horas_extras_alertas`.
2. 4 columnas nuevas de revision-1 en bloque principal: `reabierto_por_id`, `reabierto_at`, `motivo_reapertura`, `error_tipo`.
3. Cron `30 3 * * *` con lockfile `/var/run/pricing-app/rrhh_he_cron.lock` (fallback `/tmp/`).
4. Hook fichadas vía SQLAlchemy event listener `after_commit` con sub-sesión.
5. Estado `liquidada` reabrible solo con permiso `rrhh.liquidar_horas_extras` (crítico).
6. Audit append-only en `rrhh_horas_extras_historial` con `JSONB` snapshot.
7. Permisos: 4 nuevos (`ver/gestionar/aprobar/liquidar`), `aprobar`+`liquidar` críticos, `ADMIN` con todos, `GERENTE` solo `ver`.
8. Migración Alembic `20260430_create_rrhh_horas_extras.py` (date locked en orquestación).
9. Pydantic v2 inline en el router `rrhh_horas_extras.py` (no schemas/ separado — patrón del repo).
10. Frontend con CSS Modules + design tokens, sin librerías nuevas.
