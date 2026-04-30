# Tasks: RRHH — Horas Extras (detección, aprobación y liquidación)

**Change**: `rrhh-horas-extras`
**Mode**: hybrid (Engram + openspec/)
**Date**: 2026-04-30
**Depends on**:
- Proposal Engram #188 + `openspec/changes/rrhh-horas-extras/proposal.md`
- Revisión 1 Engram #189 (alertas, error_fichadas, lockfile, historial)
- Revisión 2 (Q1–Q4: export es-AR, cap 90 días, hook empleado_horarios, purga alertas)
- Spec Engram #190 (36 requirements / 75+ scenarios)
- Design Engram #191 + `openspec/changes/rrhh-horas-extras/design.md` (1471 líneas, 14 secciones)

**Convención**: cada task atómica, con archivos, refs spec/design, criterio de aceptación y complejidad (S/M/L). Dentro de un mismo batch los tasks pueden ejecutarse en paralelo; los batches son secuenciales.

---

## Batch 1 — Foundations: backend models + migración Alembic ✅ DONE (2026-04-30)

> **Spec**: requirements *Modelo `rrhh_horas_extras` con audit fields (revisión 1)*, *Modelo `rrhh_horas_extras_config` (singleton)*, *Tabla `rrhh_horas_extras_alertas`*, *Tabla `rrhh_horas_extras_historial` append-only*, *Permisos del módulo (4)*.
> **Design**: §2 Data models, §4 Migración Alembic.

> **Implementación**: T-1.1..T-1.8 completadas. Archivos: `backend/app/models/rrhh_horas_extras.py` (4 modelos + 4 enums + 5 constantes de tipo_alerta), `backend/alembic/versions/20260430_create_rrhh_horas_extras.py` (migración + seed singleton + 4 permisos + asignaciones a ADMIN/GERENTE), `backend/app/models/__init__.py` (registro). `down_revision = "add_idx_mlp_official_store_id"` (head verificado). NO se corrió `alembic upgrade head` — el usuario lo aplica manualmente.

### T-1.1 — Definir enums Python del módulo

- **Files**: `backend/app/models/rrhh_horas_extras.py` (nuevo, sección de enums al inicio).
- **Spec ref**: spec backend `Modelo rrhh_horas_extras…` (estados válidos).
- **Design ref**: §2.1 (`TipoDiaHE`, `EstadoHE`, `GeneradaPorHE`, `ErrorTipoHE`), §2.4 (`severidad`).
- **Acceptance**: enums `EstadoHE` (6 valores), `TipoDiaHE` (5), `GeneradaPorHE` (2), `ErrorTipoHE` (5) presentes y heredan `(str, enum.Enum)`. Tipos de alerta documentados como constantes string (no enum, según design §2.4) — `fichada_modificada`, `fichada_eliminada`, `recalculo_divergente`, `turno_modificado_post_aprobacion`, `liquidacion_afectada_por_cambio_turno` (revisión 2).
- **Complexity**: S
- **Depends on**: —

### T-1.2 — Modelo `RRHHHorasExtras` (bloque principal con audit revisión 1)

- **Files**: `backend/app/models/rrhh_horas_extras.py`.
- **Spec ref**: *Modelo `rrhh_horas_extras` con audit fields (revisión 1)*, *Bloques aprobados/rechazados/liquidados son inmutables ante el cron* (constraint único), *Workflow de estados*.
- **Design ref**: §2.1 (código completo del modelo).
- **Acceptance**: clase `RRHHHorasExtras` con TODAS las columnas del design §2.1 incluidas las 4 de revisión 1 (`reabierto_por_id`, `reabierto_at`, `motivo_reapertura`, `error_tipo`). `__table_args__` con `UniqueConstraint(empleado_id, fecha, tipo_dia)`, los 5 `CheckConstraint` (estado, tipo_dia, generada_por, porcentaje_rango, error_tipo_consistencia, liquidacion_consistencia) e índices nombrados (`idx_rrhh_he_empleado_fecha`, `idx_rrhh_he_fecha_estado`, `idx_rrhh_he_emp_fecha_estado`, `idx_rrhh_he_liquidacion` parcial). `relationship()` a empleado, fichadas, usuarios, historial (cascade) y alertas (cascade). `__repr__` corto.
- **Complexity**: M
- **Depends on**: T-1.1

### T-1.3 — Modelo `RRHHHorasExtrasConfig` (singleton + revisión 2)

- **Files**: `backend/app/models/rrhh_horas_extras.py`.
- **Spec ref**: *Modelo `rrhh_horas_extras_config` (singleton)*.
- **Design ref**: §2.2.
- **Acceptance**: `RRHHHorasExtrasConfig` con `id` PK + `CheckConstraint("id = 1")`, columnas `porcentaje_dia_habil`, `porcentaje_sabado_pm`, `porcentaje_domingo`, `porcentaje_feriado` (Numeric(5,2)), `hora_corte_sabado` (Time), `tolerancia_extras_minutos` (Int), `requiere_aprobacion` (Bool), `cron_activo` (Bool), `actualizado_por_id` (FK), `updated_at`. **Revisión 2**: agregar columnas `dias_retencion_alertas` (Int, NOT NULL, default 15, CHECK >= 1) y `cap_dias_recalculo_manual` (Int, NOT NULL, default 90, CHECK BETWEEN 1 AND 366). Constraint `ck_rrhh_he_config_pct_no_neg` y `ck_rrhh_he_config_tolerancia_rango`. `__repr__`.
- **Complexity**: S
- **Depends on**: T-1.1

### T-1.4 — Modelo `RRHHHorasExtrasAlerta`

- **Files**: `backend/app/models/rrhh_horas_extras.py`.
- **Spec ref**: *Tabla `rrhh_horas_extras_alertas`*, *Alertas por modificación de fichadas post-aprobación*.
- **Design ref**: §2.4.
- **Acceptance**: `RRHHHorasExtrasAlerta` con `he_id` (FK CASCADE), `tipo` (String 40), `severidad` (default `"warning"`, check `IN ('info','warning','critical')`), `mensaje` (Text), `contexto` (JSONB), `leida_at`, `leida_por_id`, `created_at`. Tipos válidos documentados en docstring incluyendo (revisión 2) `liquidacion_afectada_por_cambio_turno`. Índice parcial `idx_rrhh_he_alerta_no_leida` (WHERE leida_at IS NULL) e `idx_rrhh_he_alerta_created`. `__repr__`.
- **Complexity**: S
- **Depends on**: T-1.2

### T-1.5 — Modelo `RRHHHorasExtrasHistorial` (append-only)

- **Files**: `backend/app/models/rrhh_horas_extras.py`.
- **Spec ref**: *Tabla `rrhh_horas_extras_historial` append-only*, *Historial append-only* (cada transición inserta fila).
- **Design ref**: §2.3.
- **Acceptance**: `RRHHHorasExtrasHistorial` con `he_id` (FK CASCADE), `accion` (String 40), `estado_anterior`, `estado_nuevo`, `usuario_id` (nullable), `motivo` (Text), `snapshot` (JSONB NOT NULL), `created_at`. Índices `idx_rrhh_he_hist_he_created` y `idx_rrhh_he_hist_accion`. Acciones documentadas en docstring (`detectada`, `recalculada`, `aprobada`, `rechazada`, `reabierta`, `liquidada`, `completada_fichada`, `descartada`, `edicion_porcentaje`, `edicion_observaciones`, `fichada_modificada_post_aprobacion`, `recalculo_por_cambio_turno`, `purga_alerta`). Sin métodos de UPDATE/DELETE expuestos.
- **Complexity**: S
- **Depends on**: T-1.2

### T-1.6 — Migración Alembic `20260430_create_rrhh_horas_extras.py`

- **Files**: `backend/alembic/versions/20260430_create_rrhh_horas_extras.py` (nuevo).
- **Spec ref**: requirements de las 4 tablas + permisos.
- **Design ref**: §4 Migración Alembic (incluye orden de FK: config → he → historial → alertas → permisos).
- **Acceptance**: Verificar `alembic heads` antes de fijar `down_revision` (al momento del design la última era `20260316_create_rrhh_hikvision_users_cache`, pero la rama avanzó: validar). `upgrade()` crea las 4 tablas en el orden del design §4.1 con todos los `CheckConstraint`/`UniqueConstraint`/índices nombrados. Incluye seed del singleton (`INSERT ... ON CONFLICT (id) DO NOTHING`) con defaults documentados (50/100/100/100, corte 13:00, tolerancia 15, requiere_aprobacion=true, cron_activo=true, dias_retencion_alertas=15, cap_dias_recalculo_manual=90 — los dos últimos de revisión 2). `downgrade()` dropea en orden inverso (alertas → historial → he → config) y limpia los 4 permisos + asignaciones (patrón `20260312_rrhh_permisos.py`).
- **Complexity**: L
- **Depends on**: T-1.2, T-1.3, T-1.4, T-1.5

### T-1.7 — Seed de permisos + asignación a roles base en migración

- **Files**: dentro de `backend/alembic/versions/20260430_create_rrhh_horas_extras.py` (mismo archivo de T-1.6).
- **Spec ref**: *Permisos del módulo (4)*.
- **Design ref**: §4.1 paso 5 (PERMISOS_HE).
- **Acceptance**: 4 permisos insertados en `permisos` con códigos `rrhh.ver_horas_extras` (orden 130, no crítico), `rrhh.gestionar_horas_extras` (131, no crítico), `rrhh.aprobar_horas_extras` (132, **crítico**), `rrhh.liquidar_horas_extras` (133, **crítico**). Asignación a `roles_permisos_base`: `ADMIN` recibe los 4, `GERENTE` recibe solo `rrhh.ver_horas_extras`. `SUPERADMIN` cubierto por wildcard existente (no requiere INSERT explícito). `ON CONFLICT DO NOTHING` para idempotencia.
- **Complexity**: S
- **Depends on**: T-1.6 (mismo archivo)

### T-1.8 — Registrar nuevos modelos en `app/models/__init__.py`

- **Files**: `backend/app/models/__init__.py`.
- **Spec ref**: convención del repo (todos los modelos importados para que Alembic los detecte).
- **Design ref**: §5 Affected Areas (proposal §5).
- **Acceptance**: Import de `RRHHHorasExtras`, `RRHHHorasExtrasConfig`, `RRHHHorasExtrasAlerta`, `RRHHHorasExtrasHistorial` y los enums (`EstadoHE`, `TipoDiaHE`, `GeneradaPorHE`, `ErrorTipoHE`) desde `app.models.rrhh_horas_extras`. Patrón consistente con los otros modelos RRHH (mismo orden alfabético del archivo).
- **Complexity**: S
- **Depends on**: T-1.2, T-1.3, T-1.4, T-1.5

---

## Batch 2 — Service layer (lógica de negocio) ✅ DONE (2026-04-30)

> **Spec**: requirements *Detección automática*, *Tolerancia*, *Clasificación tipo_dia*, *Empleado sin turno*, *Días licencia/ART/vacaciones*, *Fichadas desbalanceadas*, *Workflow*, *Inmutabilidad ante el cron*, *Reapertura*, *Liquidación*, *Idempotencia bulk*.
> **Design**: §7 Service layer (skeleton de `HorasExtrasService`), §1.2 garantías idempotencia, §3 máquina de estados.

- [x] T-2.1 Helper `_clasificar_tipo_dia` (corte sábado, feriado, día normal)
- [x] T-2.2 Helper `_validar_fichadas_dia` (devuelve `(válido, error_tipo)`)
- [x] T-2.3 Método `_calcular_he_dia` (single day, multi-turno)
- [x] T-2.4 Método `detectar_he_periodo` (loop empleados activos)
- [x] T-2.5 Helper `_log_historial` (append-only)
- [x] T-2.6 Métodos de workflow: `aprobar_bloque`, `rechazar_bloque`, `reabrir_bloque`
- [x] T-2.7 Métodos de anomalías: `completar_fichada_faltante`, `descartar_dia`
- [x] T-2.8 Método `liquidar_periodo` (bulk con validación)
- [x] T-2.9 Hook `notificar_fichada_modificada` (Riesgo 1)
- [x] T-2.10 Método `recalcular_por_cambio_turno` (revisión 2 — Q3)
- [x] T-2.11 Método `purgar_alertas_viejas` (revisión 2 — Q4)

### T-2.1 — Helper `_clasificar_tipo_dia` (corte sábado, feriado, día normal)

- **Files**: `backend/app/services/rrhh_horas_extras_service.py` (nuevo).
- **Spec ref**: *Clasificación de tipo de día con corte de sábado configurable* (incluye los 6 scenarios: antes corte, después corte, cruza corte, domingo, feriado, día especial laborable).
- **Design ref**: §7 método `_clasificar_tipo_dia`.
- **Acceptance**: Función privada que recibe `(fecha, trabajado_minutos, primera_entrada)` y retorna `list[tuple[str, int, Decimal]]`. Lee `rrhh_horarios_excepciones` para feriados (tipo='feriado' AND es_laborable=false) → `feriado_100`. Domingo → `domingo_100`. Sábado: split por `hora_corte_sabado` si las HE cruzan; antes del corte `habil_50`, después `sabado_100`. L-V → `habil_50`. Día especial laborable → clasificación normal por día de semana.
- **Complexity**: M
- **Depends on**: T-1.2 (modelos)

### T-2.2 — Helper `_validar_fichadas_dia` (devuelve `(válido, error_tipo)`)

- **Files**: `backend/app/services/rrhh_horas_extras_service.py`.
- **Spec ref**: *Fichadas desbalanceadas crean bloque con estado `error_fichadas`* (3 scenarios: sin salida, sin entrada, impares).
- **Design ref**: §7 método `_validar_fichadas_dia`.
- **Acceptance**: Recibe `list[RRHHFichada]` ordenadas. Devuelve `(True, None)` si pares balanceados; si no, `(False, error_tipo)` con `error_tipo` ∈ `{sin_fichada_salida, sin_fichada_entrada, fichadas_desbalanceadas, solapamiento, otro}` según el caso (ver enum `ErrorTipoHE` del design §2.1). Solapamientos detectados (entrada después de entrada anterior sin salida) marcan `solapamiento`.
- **Complexity**: M
- **Depends on**: T-1.1

### T-2.3 — Método `_calcular_he_dia` (single day, multi-turno)

- **Files**: `backend/app/services/rrhh_horas_extras_service.py`.
- **Spec ref**: *Detección automática de horas extras*, *Empleado cumple turno exacto*, *Empleado trabaja en corrido sin fichar pausa*, *Empleado se queda más allá*, *Empleado ficha menos*, *Empleado sin turno asignado*, *Días licencia/ART/vacaciones*.
- **Design ref**: §7 método `_calcular_he_dia` (8 steps documentados).
- **Acceptance**: Implementa los 8 pasos del design §7: cargar fichadas en TZ ART, validar pares (delegando a T-2.2), obtener turnos con `dias_semana` cubriendo el día (deduplicando por `horario_config_id` para evitar el riesgo de §12 — solapamiento M:N), sumar `turno_esperado_minutos`, calcular `trabajado_minutos`, comparar con `tolerancia_extras_minutos`, clasificar tipo_dia (delegando a T-2.1, posible split), persistir bloque(s). Si presentismo del día es `vacaciones`/`art`/`licencia`: NO crear bloque. Si bloque congelado existe con divergencia: generar alerta `recalculo_divergente` (no sobrescribir).
- **Complexity**: L
- **Depends on**: T-2.1, T-2.2, T-1.2, T-1.4

### T-2.4 — Método `detectar_he_periodo` (loop empleados activos)

- **Files**: `backend/app/services/rrhh_horas_extras_service.py`.
- **Spec ref**: *Detección automática*, *Cron diario determinista 03:30*, *Asignación retroactiva de turno reprocesa bloques pendientes*.
- **Design ref**: §7 método `detectar_he_periodo`.
- **Acceptance**: Recibe `(fecha_desde, fecha_hasta, empleado_ids=None)`. Itera empleados activos × fechas y delega a `_calcular_he_dia`. Devuelve `dict` con `procesados`, `creados`, `actualizados`, `alertas`, `errores`. Idempotente: bloques en `aprobada`/`rechazada`/`liquidada`/`error_fichadas` no se sobrescriben. Bloques en `pendiente_asignacion_turno` se reprocesan al asignar turno.
- **Complexity**: M
- **Depends on**: T-2.3

### T-2.5 — Helper `_log_historial` (append-only)

- **Files**: `backend/app/services/rrhh_horas_extras_service.py`.
- **Spec ref**: *Historial append-only* (3 scenarios), *Cada transición inserta fila*.
- **Design ref**: §7 método `_log_historial` (DEBE ejecutarse antes del commit).
- **Acceptance**: Inserta `RRHHHorasExtrasHistorial` con `accion`, `estado_anterior`, `estado_nuevo`, `usuario_id` (None si automático/cron), `motivo`, `snapshot` JSONB con campos materiales (`extras_minutos`, `trabajado_minutos`, `turno_esperado_minutos`, `tipo_dia`, `porcentaje_recargo`, `estado`, `observaciones`, `fichada_entrada_id`, `fichada_salida_id`). NO commit explícito (caller controla atomicidad).
- **Complexity**: S
- **Depends on**: T-1.5

### T-2.6 — Métodos de workflow: `aprobar_bloque`, `rechazar_bloque`, `reabrir_bloque`

- **Files**: `backend/app/services/rrhh_horas_extras_service.py`.
- **Spec ref**: *Workflow de estados con permisos diferenciados*, *Bulk approve continúa pese a errores individuales*, *Reapertura manual de bloques aprobados*, *Reapertura post-liquidación* (design §3.2).
- **Design ref**: §7 (`aprobar_bloque`, `rechazar_bloque`, `reabrir_bloque`) + §3.1 reglas de transición.
- **Acceptance**: 3 métodos públicos. `aprobar_bloque(he_id, usuario, porcentaje_override?, observaciones?)`: solo desde `detectada`; setea `aprobado_por_id`/`aprobado_at`; aplica override (si presente, marca `tipo_dia='manual'`); llama `_log_historial`. `rechazar_bloque(he_id, usuario, motivo)`: desde `detectada`/`aprobada`/`error_fichadas`; motivo obligatorio (length >= 3). `reabrir_bloque(he_id, usuario, motivo)`: `aprobada → detectada` (limpia `aprobado_*`), `liquidada → aprobada` (limpia `liquidacion_*`/`liquidado_*`, requiere chequeo de permiso `liquidar` en el router), `rechazada → detectada`. Setea siempre `reabierto_por_id`/`reabierto_at`/`motivo_reapertura`. Lanza `HTTPException(409 o 422)` si el estado no permite la transición.
- **Complexity**: L
- **Depends on**: T-2.5

### T-2.7 — Métodos de anomalías: `completar_fichada_faltante`, `descartar_dia`

- **Files**: `backend/app/services/rrhh_horas_extras_service.py`.
- **Spec ref**: *Aprobador completa la fichada faltante*, *Aprobador descarta el día completo*, *Intento de aprobar bloque en error_fichadas falla*.
- **Design ref**: §7 (`completar_fichada_faltante`, `descartar_dia`).
- **Acceptance**: `completar_fichada_faltante(he_id, usuario, timestamp, tipo, motivo)`: solo desde `error_fichadas`; crea `RRHHFichada(origen='manual', motivo_manual=motivo, registrado_por_id=usuario.id)`; recalcula el día con `_calcular_he_dia`; si nuevas fichadas son válidas, bloque pasa a `detectada` (o desaparece si HE < tolerancia). `descartar_dia(he_id, usuario, motivo)`: solo desde `error_fichadas` → `rechazada` con `motivo_rechazo=motivo`. Ambos llaman `_log_historial`.
- **Complexity**: M
- **Depends on**: T-2.5, T-2.3

### T-2.8 — Método `liquidar_periodo` (bulk con validación)

- **Files**: `backend/app/services/rrhh_horas_extras_service.py`.
- **Spec ref**: *Liquidación mensual de bloques aprobados* (3 scenarios: éxito, no aprobado falla, sin permiso 403), *Idempotencia y atomicidad bulk*.
- **Design ref**: §7 método `liquidar_periodo`.
- **Acceptance**: Recibe `(periodo: str (YYYYMM), ids: list[int], usuario)`. Por cada id: si estado != `aprobada` → agrega a `detalle_rechazos` y NO modifica; si OK → setea `estado='liquidada'`, `liquidacion_periodo`, `liquidado_por_id`, `liquidado_at` y llama `_log_historial`. Devuelve `{periodo, liquidados, rechazados, detalle_rechazos}`. Una sola transacción.
- **Complexity**: M
- **Depends on**: T-2.5

### T-2.9 — Hook `notificar_fichada_modificada` (Riesgo 1)

- **Files**: `backend/app/services/rrhh_horas_extras_service.py`.
- **Spec ref**: *Alertas por modificación de fichadas post-aprobación* (2 scenarios), *Edición de fichada vinculada a bloque detectada SÍ recalcula*.
- **Design ref**: §7 método `notificar_fichada_modificada` + §9.1 idempotencia.
- **Acceptance**: Recibe `(fichada_id, evento)` con `evento ∈ {modificada, eliminada, insertada_tardia}`. Para cada bloque que referencia `fichada_entrada_id` o `fichada_salida_id == fichada_id`: si estado congelado (`aprobada`/`liquidada`/`rechazada`) → dry-run del recálculo, si hay diferencia material crear alerta `recalculo_divergente` con contexto JSONB `{actual, recalculado, fichada_id}`; si estado editable (`detectada`/`error_fichadas`/`pendiente_*`) → recalcular real. Idempotencia: chequear `(he_id, tipo, contexto.fichada_id)` antes de insertar alerta para no duplicar.
- **Complexity**: L
- **Depends on**: T-2.3, T-2.5, T-1.4

### T-2.10 — Método `recalcular_por_cambio_turno` (revisión 2 — Q3)

- **Files**: `backend/app/services/rrhh_horas_extras_service.py`.
- **Spec ref**: revisión 2 Q3 (resolución de open question del design §13).
- **Design ref**: §13 open question Q3 + §12 Riesgos residuales (race condition).
- **Acceptance**: Firma `recalcular_por_cambio_turno(empleado_id: int, fecha_desde_minima: date) -> dict[str, int]`. Aplica **cap de 90 días** (lee `rrhh_horas_extras_config.cap_dias_recalculo_manual`) — si `(date.today() - fecha_desde_minima).days > cap` se limita a `today - cap_dias`. Para cada bloque del empleado desde `fecha_desde_minima` hasta hoy:
  - estado `detectada`/`pendiente_asignacion_turno`/`error_fichadas` → recalcular con `_calcular_he_dia`.
  - estado `aprobada` o `rechazada` → revertir a `detectada` (audit con motivo automático "Cambio de turno detectado, requiere re-aprobación") + `_log_historial`.
  - estado `liquidada` → **NO modificar**; en su lugar crear alerta `liquidacion_afectada_por_cambio_turno` (severidad `critical`) con contexto `{empleado_id, fecha, fichada_ids, snapshot_actual}`.
  - Devuelve `{procesados, recalculados, reabiertos, alertas_liquidadas}`.
- **Complexity**: L
- **Depends on**: T-2.3, T-2.5, T-1.4

### T-2.11 — Método `purgar_alertas_viejas` (revisión 2 — Q4)

- **Files**: `backend/app/services/rrhh_horas_extras_service.py`.
- **Spec ref**: revisión 2 Q4 (resolución de open question §13 "Limpieza de alertas leídas").
- **Design ref**: §13 open question (purga de alertas leídas).
- **Acceptance**: Firma `purgar_alertas_viejas(dias: int | None = None) -> dict[str, int]`. Si `dias` None, lee `rrhh_horas_extras_config.dias_retencion_alertas` (default 15). Hard-delete (`db.query(RRHHHorasExtrasAlerta).filter(...)`) de alertas **leídas** (`leida_at IS NOT NULL`) cuya `created_at < (today - dias)`. Devuelve `{purgadas: int, retenidas: int}`. Loggea info por cantidad eliminada. NO purga alertas no-leídas (siempre se conservan hasta resolución manual).
- **Complexity**: S
- **Depends on**: T-1.4, T-1.3

---

## Batch 3 — SQLAlchemy event listeners (hooks) ✅ DONE (2026-04-30)

> **Spec**: *Alertas por modificación de fichadas post-aprobación*, revisión 2 Q3 (cambio de empleado_horario dispara recálculo).
> **Design**: §9 Hook a fichadas modificadas (decisión `after_commit` + sub-sesión).

- [x] T-3.1 Listener en `RRHHFichada` (`after_update` / `after_delete` / `after_insert`)
- [x] T-3.2 Listener en `RRHHEmpleadoHorario` (revisión 2 Q3)
- [x] T-3.3 Registrar listeners en `app/main.py` (startup)

### T-3.1 — Listener en `RRHHFichada` (`after_update` / `after_delete` / `after_insert`)

- **Files**: `backend/app/events/rrhh_he_hooks.py` (nuevo); `backend/app/events/__init__.py` (nuevo, vacío para namespace).
- **Spec ref**: *Edición de fichada vinculada a bloque aprobado dispara alerta*, *Edición de fichada vinculada a bloque detectada SÍ recalcula*.
- **Design ref**: §9.1 código completo + tabla de alternativas (rechazada manual, elegido event listener).
- **Acceptance**: Listeners `after_update`, `after_delete`, `after_insert` (este último filtrado por `timestamp < hoy - 1 día` según riesgo §12 "Fichadas tardías post-aprobación") en `RRHHFichada` que encolan `(fichada_id, evento)` en `session.info["_rrhh_he_pending"]`. Listener `after_commit` en `Session` que abre sub-sesión, llama `service.notificar_fichada_modificada(fichada_id, evento)` por cada item, commitea sub-sesión, swallowa errores (logger.exception). NUNCA propaga excepciones al commit principal.
- **Complexity**: M
- **Depends on**: T-2.9

### T-3.2 — Listener en `RRHHEmpleadoHorario` (revisión 2 Q3)

- **Files**: `backend/app/events/rrhh_he_hooks.py`.
- **Spec ref**: revisión 2 Q3.
- **Design ref**: §13 open question Q3 (decisión: SÍ habilitar recálculo automático al editar `rrhh_empleado_horarios`).
- **Acceptance**: Listeners `after_insert`, `after_update`, `after_delete` sobre `RRHHEmpleadoHorario`. Encolan en `session.info["_rrhh_he_horarios_pending"]` la tupla `(empleado_id, fecha_desde_minima)`. `fecha_desde_minima` se calcula como el `min(fecha_desde, fecha_hasta_anterior_si_existe)` del registro afectado, o `today - 90` si fecha_desde es muy antigua (cap de revisión 2). Listener `after_commit` invoca `service.recalcular_por_cambio_turno(empleado_id, fecha_desde_minima)` en sub-sesión, swallowa errores.
- **Complexity**: M
- **Depends on**: T-2.10

### T-3.3 — Registrar listeners en `app/main.py` (startup)

- **Files**: `backend/app/main.py`.
- **Spec ref**: convención del repo (los hooks deben cargarse al startup).
- **Design ref**: §9.1 (importado desde `main.py`).
- **Acceptance**: Import `import app.events.rrhh_he_hooks` en `main.py` ANTES de `include_router(...)` para garantizar que los listeners queden registrados antes de aceptar requests. Comentario corto explicando que importar el módulo dispara `@event.listens_for`.
- **Complexity**: S
- **Depends on**: T-3.1, T-3.2

---

## Batch 4 — Schemas Pydantic v2 + Router ✅ DONE (2026-04-30)

> **Spec**: TODOS los requirements del dominio backend (endpoints + permisos + bulk + export).
> **Design**: §5 Schemas Pydantic v2, §6 Endpoints (tabla con 21 endpoints).

- [x] T-4.1 Schemas Pydantic v2 inline en el router
- [x] T-4.2 Validación cap 90 días en `RecalcularRequest` (revisión 2 — Q2)
- [x] T-4.3 Endpoints de listado, detalle, filtros y paginación
- [x] T-4.4 Endpoints de transiciones de estado (individual + bulk)
- [x] T-4.5 Endpoints de anomalías
- [x] T-4.6 Endpoint de recálculo manual con cap (revisión 2 — Q2)
- [x] T-4.7 Endpoints de liquidación + export Excel (revisión 2 — Q1)
- [x] T-4.8 Endpoints de alertas
- [x] T-4.9 Endpoint de historial
- [x] T-4.10 Endpoints de config (GET/PUT singleton)
- [x] T-4.11 Registrar router en `app/main.py`

### T-4.1 — Schemas Pydantic v2 inline en el router

- **Files**: `backend/app/routers/rrhh_horas_extras.py` (nuevo, sección de schemas al inicio).
- **Spec ref**: requirements de listado, detalle, alertas, historial, config, liquidación.
- **Design ref**: §5 (código completo de TODOS los schemas listados).
- **Acceptance**: 17 clases Pydantic v2 (TODAS las listadas en design §5: `FichadaRefSchema`, `HorasExtrasResponse`, `HorasExtrasListResponse`, `HorasExtrasCreate`, `HorasExtrasUpdate`, `AprobacionRequest`, `RechazoRequest`, `ReaperturaRequest`, `CompletarFichadaRequest`, `DescartarDiaRequest`, `RecalcularRequest`, `BulkAprobarRequest`, `BulkRechazarRequest`, `LiquidacionRequest`, `LiquidacionResponse`, `HorasExtrasConfigSchema`, `AlertaResponse`, `HistorialEntryResponse`). `model_config = ConfigDict(from_attributes=True)` en todos los Response. Validators con `@field_validator`. **Schema config (T-4.1)** debe incluir los nuevos campos de revisión 2 (`dias_retencion_alertas`, `cap_dias_recalculo_manual`).
- **Complexity**: M
- **Depends on**: T-1.2, T-1.3, T-1.4, T-1.5

### T-4.2 — Validación cap 90 días en `RecalcularRequest` (revisión 2 — Q2)

- **Files**: `backend/app/routers/rrhh_horas_extras.py` (sección schemas).
- **Spec ref**: revisión 2 Q2.
- **Design ref**: §12 riesgo "Performance en `/recalcular` sobre rangos grandes" + revisión 2 Q2.
- **Acceptance**: `RecalcularRequest` extiende validators: `@field_validator("fecha_hasta")` ya valida orden; agregar validation que `(fecha_hasta - fecha_desde).days <= cap_dias_recalculo_manual` (lee del singleton al ejecutar, default 90). Si excede, ValueError → FastAPI devuelve **422 Unprocessable Entity** con detalle `"Rango excede cap de N días configurado"`. Test debe cubrir: 89 días OK, 90 días OK (inclusivo), 91 días → 422.
- **Complexity**: S
- **Depends on**: T-4.1, T-1.3

### T-4.3 — Endpoints de listado, detalle, filtros y paginación

- **Files**: `backend/app/routers/rrhh_horas_extras.py`.
- **Spec ref**: requirements de listado paginado, filtros, modal detalle.
- **Design ref**: §6 tabla endpoints filas 1-2 (GET `/`, GET `/{id}`).
- **Acceptance**: `GET /rrhh/horas-extras/` con query params `empleado_id?`, `fecha_desde?`, `fecha_hasta?`, `estado?` (CSV), `tipo_dia?`, `con_alertas?`, `page` (default 1), `page_size` (default 50, max 200). Response `HorasExtrasListResponse`. `GET /rrhh/horas-extras/{id}` retorna `HorasExtrasResponse` con eager load de empleado + fichadas + count alertas no leídas. Permiso: `rrhh.ver_horas_extras` en ambos. Helper `_check_permiso(db, user, codigo)` copiado del patrón de `rrhh_horarios.py`.
- **Complexity**: M
- **Depends on**: T-4.1

### T-4.4 — Endpoints de transiciones de estado (individual + bulk)

- **Files**: `backend/app/routers/rrhh_horas_extras.py`.
- **Spec ref**: *Workflow de estados con permisos diferenciados*, *Bulk approve continúa pese a errores*, *Idempotencia bulk*.
- **Design ref**: §6 filas PATCH `/aprobar`, `/rechazar`, `/reabrir`, POST `/bulk/aprobar`, `/bulk/rechazar`.
- **Acceptance**:
  - `PATCH /{id}/aprobar` (perm `rrhh.aprobar_horas_extras`) recibe `AprobacionRequest`, llama `service.aprobar_bloque`.
  - `PATCH /{id}/rechazar` (perm `rrhh.aprobar_horas_extras`) recibe `RechazoRequest`, llama `service.rechazar_bloque`.
  - `PATCH /{id}/reabrir` (perm `rrhh.aprobar_horas_extras` o `rrhh.liquidar_horas_extras` si bloque era `liquidada`).
  - `POST /bulk/aprobar` (perm `rrhh.aprobar_horas_extras`) loop con audit individual, devuelve `{aprobados, fallidos: list[{id, status, detail}]}`.
  - `POST /bulk/rechazar` (perm `rrhh.aprobar_horas_extras`) idem.
  - Todos retornan `HorasExtrasResponse` (singular) o lista de resultados (bulk). 422 si motivo vacío en rechazo/reapertura. 409 si transición inválida.
- **Complexity**: L
- **Depends on**: T-4.1, T-2.6

### T-4.5 — Endpoints de anomalías

- **Files**: `backend/app/routers/rrhh_horas_extras.py`.
- **Spec ref**: *Aprobador completa fichada faltante*, *Aprobador descarta el día completo*.
- **Design ref**: §6 filas POST `/{id}/completar-fichada` y POST `/{id}/descartar-dia`.
- **Acceptance**:
  - `POST /{id}/completar-fichada` (perm `rrhh.gestionar_horas_extras`) recibe `CompletarFichadaRequest`, llama `service.completar_fichada_faltante`. Solo permitido desde `error_fichadas`.
  - `POST /{id}/descartar-dia` (perm `rrhh.aprobar_horas_extras`) recibe `DescartarDiaRequest`, llama `service.descartar_dia`. Solo desde `error_fichadas`.
  - Retornan `HorasExtrasResponse`.
- **Complexity**: S
- **Depends on**: T-4.1, T-2.7

### T-4.6 — Endpoint de recálculo manual con cap (revisión 2 — Q2)

- **Files**: `backend/app/routers/rrhh_horas_extras.py`.
- **Spec ref**: *Trigger manual sobre rango ejecuta misma lógica*.
- **Design ref**: §6 fila POST `/recalcular` + §12 riesgo race condition + revisión 2 Q2.
- **Acceptance**: `POST /rrhh/horas-extras/recalcular` (perm `rrhh.gestionar_horas_extras`) recibe `RecalcularRequest`. Validation cap (T-4.2). Antes de ejecutar: chequear lockfile del cron — si activo, devolver `409 Conflict` con detalle "Cron en curso, intentá luego" (riesgo §12). Si OK: llama `service.detectar_he_periodo(...)`. Retorna `{procesados, creados, actualizados, alertas, errores}`.
- **Complexity**: M
- **Depends on**: T-4.2, T-2.4

### T-4.7 — Endpoints de liquidación + export Excel (revisión 2 — Q1)

- **Files**: `backend/app/routers/rrhh_horas_extras.py`.
- **Spec ref**: *Liquidación mensual*, *Export Excel del período liquidado*, revisión 2 Q1 (es-AR).
- **Design ref**: §6 filas POST `/liquidar`, GET `/exportar`.
- **Acceptance**:
  - `POST /rrhh/horas-extras/liquidar` (perm `rrhh.liquidar_horas_extras`) recibe `LiquidacionRequest` (period YYYYMM + lista ids). Llama `service.liquidar_periodo`. Devuelve `LiquidacionResponse`.
  - `GET /rrhh/horas-extras/exportar` (perm `rrhh.ver_horas_extras`) recibe `periodo` (YYYYMM) o `fecha_desde`+`fecha_hasta`, `estado?`. Genera XLSX con `openpyxl`, `BytesIO` en memoria, `StreamingResponse` con headers `Content-Disposition: attachment; filename="horas_extras_{periodo}.xlsx"`.
  - **Revisión 2 Q1**: headers en castellano rioplatense ("Legajo", "Apellido y Nombre", "Fecha", "Tipo de día", "Minutos extra", "% Recargo", "Estado", "Observaciones", "Motivo de rechazo"). Formato fecha **DD/MM/YYYY**. Locale `es-AR` (cell `number_format='dd/mm/yyyy'` para fechas). Encabezado bold + freeze panes en fila 2.
  - Si no hay rows: archivo solo con headers, NO error.
- **Complexity**: M
- **Depends on**: T-4.1, T-2.8

### T-4.8 — Endpoints de alertas

- **Files**: `backend/app/routers/rrhh_horas_extras.py`.
- **Spec ref**: *Tabla `rrhh_horas_extras_alertas`*, *Marcar alerta como leída*.
- **Design ref**: §6 filas GET `/alertas`, PATCH `/alertas/{id}/leida`.
- **Acceptance**:
  - `GET /rrhh/horas-extras/alertas` (perm `rrhh.ver_horas_extras`) con query `solo_no_leidas` (default `true`), `severidad?`, `page`, `page_size`. Retorna `{items: list[AlertaResponse], total}`.
  - `PATCH /rrhh/horas-extras/alertas/{id}/leida` (perm `rrhh.ver_horas_extras` per spec — la spec dice ver, gestionar también podría, validar) setea `leida_at=now()`, `leida_por_id=current_user.id`. Retorna `AlertaResponse`.
- **Complexity**: S
- **Depends on**: T-4.1

### T-4.9 — Endpoint de historial

- **Files**: `backend/app/routers/rrhh_horas_extras.py`.
- **Spec ref**: *Historial append-only*.
- **Design ref**: §6 fila GET `/historial/{he_id}`.
- **Acceptance**: `GET /rrhh/horas-extras/historial/{he_id}` (perm `rrhh.ver_horas_extras`) retorna `list[HistorialEntryResponse]` ordenada por `created_at ASC`. NO acciones de UPDATE/DELETE expuestas (append-only by convention).
- **Complexity**: S
- **Depends on**: T-4.1

### T-4.10 — Endpoints de config (GET/PUT singleton)

- **Files**: `backend/app/routers/rrhh_horas_extras.py`.
- **Spec ref**: *Modelo `rrhh_horas_extras_config` (singleton)*, *Update de config no toca bloques liquidados*.
- **Design ref**: §6 filas GET `/config`, PUT `/config`.
- **Acceptance**:
  - `GET /rrhh/horas-extras/config` (perm `rrhh.ver_horas_extras`) retorna `HorasExtrasConfigSchema` del singleton id=1.
  - `PUT /rrhh/horas-extras/config` (perm `rrhh.config` existente — NO crear nuevo, reutilizar el del módulo de configuración) recibe `HorasExtrasConfigSchema`, actualiza el singleton + setea `actualizado_por_id=current_user.id`. Cambiar `dias_retencion_alertas` o `cap_dias_recalculo_manual` (revisión 2) toma efecto inmediato. Cambiar porcentajes NO recalcula bloques en estados congelados.
- **Complexity**: S
- **Depends on**: T-4.1

### T-4.11 — Registrar router en `app/main.py`

- **Files**: `backend/app/main.py`.
- **Spec ref**: convención repo (`include_router`).
- **Design ref**: §5 Affected Areas (proposal).
- **Acceptance**: `from app.routers import rrhh_horas_extras` + `app.include_router(rrhh_horas_extras.router)` en el bloque de RRHH del archivo. Sin tocar otras rutas. Verificar que el orden no rompe otros módulos.
- **Complexity**: S
- **Depends on**: T-4.3..T-4.10

---

## Batch 5 — Cron script ✅ DONE (2026-04-30)

> **Spec**: *Cron diario determinista 03:30 con lockfile* (4 scenarios).
> **Design**: §8 Cron script.

- [x] T-5.1 Script `cron_rrhh_horas_extras.py` con flock no-bloqueante
- [x] T-5.2 Step de detección (D-1) en el cron
- [x] T-5.3 Step de purga de alertas viejas (revisión 2 — Q4)
- [x] T-5.4 Logging estructurado y exit codes
- [x] T-5.5 Documentar crontab entry

### T-5.1 — Script `cron_rrhh_horas_extras.py` con flock no-bloqueante

- **Files**: `backend/app/scripts/cron_rrhh_horas_extras.py` (nuevo).
- **Spec ref**: *Cron diario determinista 03:30 con lockfile* (scenario lockfile activo + libera lockfile en error).
- **Design ref**: §8.1 código completo (`_file_lock` context manager).
- **Acceptance**: Estructura del design §8.1: lockfile primario `/var/run/pricing-app/rrhh_he_cron.lock`, fallback `/tmp/rrhh_he_cron.lock`. `fcntl.flock(..., LOCK_EX | LOCK_NB)` — si bloqueado: `SystemExit(1)`. `finally`: libera lock + cierra fd. Bootstrap path estilo `sync_hikvision_fichadas.py` (sys.path insert + `.env` load). TZ explícita: `from app.services.rrhh_hikvision_client import ART_TZ` + `datetime.now(ART_TZ).date() - timedelta(days=1)` (riesgo §12 cambio TZ).
- **Complexity**: M
- **Depends on**: T-2.4

### T-5.2 — Step de detección (D-1) en el cron

- **Files**: `backend/app/scripts/cron_rrhh_horas_extras.py`.
- **Spec ref**: *Cron procesa D-1 completo determinístico*.
- **Design ref**: §8.1 función `main()`.
- **Acceptance**: Dentro del lock: chequear `cron_activo` del singleton; si false → exit 3 con WARNING. Si true: instanciar `HorasExtrasService(db)` y llamar `detectar_he_periodo(ayer, ayer)`. `db.commit()` al finalizar OK. `db.rollback()` en excepción → exit 2.
- **Complexity**: S
- **Depends on**: T-5.1

### T-5.3 — Step de purga de alertas viejas (revisión 2 — Q4)

- **Files**: `backend/app/scripts/cron_rrhh_horas_extras.py`.
- **Spec ref**: revisión 2 Q4.
- **Design ref**: §13 open question (purga alertas leídas).
- **Acceptance**: ÚLTIMO step antes de salir del lock (después de detección y `db.commit()`). Llamar `service.purgar_alertas_viejas()` (sin args → usa `dias_retencion_alertas` de config). Loggear info `"Purga alertas: {purgadas} eliminadas, {retenidas} retenidas"`. Si la purga falla: log error pero NO romper el exit code de la detección (la detección ya commiteó).
- **Complexity**: S
- **Depends on**: T-5.2, T-2.11

### T-5.4 — Logging estructurado y exit codes

- **Files**: `backend/app/scripts/cron_rrhh_horas_extras.py`.
- **Spec ref**: *Cron libera lockfile en error*, *Cron deshabilitado por config*.
- **Design ref**: §8.1 docstring exit codes.
- **Acceptance**: Logger via `app.core.logging.get_logger("scripts.cron_rrhh_horas_extras")`. Exit codes documentados en docstring del módulo: `0` OK, `1` lock activo, `2` error fatal, `3` cron deshabilitado. Cada path loggea: INFO al iniciar, INFO con counts al finalizar OK, WARNING si lockfile activo / cron_activo=false, EXCEPTION con stacktrace en error fatal. Log lines con prefijo emoji (✅ ❌ 🔄) según convención del repo.
- **Complexity**: S
- **Depends on**: T-5.1

### T-5.5 — Documentar crontab entry

- **Files**: `backend/app/scripts/cron_rrhh_horas_extras.py` (docstring del módulo).
- **Spec ref**: *Cron diario determinista 03:30*.
- **Design ref**: §8.1 docstring (entry).
- **Acceptance**: Docstring del módulo incluye comentario block con la entry exacta:
  ```
  30 3 * * * cd /var/www/html/pricing-app/backend && \
    /var/www/html/pricing-app/backend/venv/bin/python \
    -m app.scripts.cron_rrhh_horas_extras \
    >> /var/log/pricing-app/rrhh_he_cron.log 2>&1
  ```
  + nota "NO se autoinstala — agregar manualmente al crontab del usuario `www-data` o equivalente". El script NO modifica `sync_all_incremental.sh` (es independiente, corre por su cuenta).
- **Complexity**: S
- **Depends on**: —

---

## Batch 6 — Frontend page + componentes ✅ DONE (2026-04-30)

> **Spec**: requirements del dominio frontend (5 tabs, filtros, bulk, modal detalle, anomalías, alertas, edición inline %, recalcular, exportar, integración sueldos, visibilidad permisos, estados vacíos/errores).
> **Design**: §10 Frontend design (tabs, componentes, CSS, API).

- [x] T-6.1 `RRHHHorasExtras.jsx` skeleton con 5 tabs
- [x] T-6.2 Tab Pendientes — tabla + filtros + bulk actions
- [x] T-6.3 Tab Aprobadas — tabla + opción "Reabrir" + Liquidar
- [x] T-6.4 Tab Liquidadas — tabla read-only + export
- [x] T-6.5 Tab Anomalías — tabla con CTAs
- [x] T-6.6 Tab Alertas — tabla con CTAs
- [x] T-6.7 Modal detalle bloque (fichadas + historial)
- [x] T-6.8 Modal completar fichada
- [x] T-6.9 Modal rechazo / descarte / reapertura (motivo obligatorio)
- [x] T-6.10 Modal cambio de % recargo (individual + bulk)
- [x] T-6.11 CSS Modules siguiendo design tokens
- [x] T-6.12 API methods en `services/api.js`
- [x] T-6.13 Registrar ruta en `App.jsx` + entrada en Sidebar
- [x] T-6.14 Permission checks con `usePermisos()`

### T-6.1 — `RRHHHorasExtras.jsx` skeleton con 5 tabs

- **Files**: `frontend/src/pages/RRHHHorasExtras.jsx` (nuevo), `frontend/src/pages/RRHHHorasExtras.module.css` (nuevo).
- **Spec ref**: *Página `RRHHHorasExtras.jsx` con cinco tabs*.
- **Design ref**: §10.1 layout, §10.2 tabs.
- **Acceptance**: Page container con header (título "RRHH › Horas Extras" + botones globales `[Config] [Detectar] [Exportar]`), tabs `Pendientes | Con alertas | Aprobadas | Rechazadas | Liquidadas` (5). Filtro estado backend mapeado:
  - Pendientes: `detectada,error_fichadas,pendiente_asignacion_turno`
  - Con alertas: `con_alertas=true`
  - Aprobadas: `aprobada`, Rechazadas: `rechazada`, Liquidadas: `liquidada`.
  Badge contador en "Con alertas" + "Pendientes" con anomalías. `usePermisos()` para gateo del componente. Si sin `rrhh.ver_horas_extras` → componente "permiso denegado" estándar.
- **Complexity**: M
- **Depends on**: T-6.11, T-6.12, T-6.14

### T-6.2 — Tab Pendientes — tabla + filtros + bulk actions

- **Files**: `frontend/src/pages/RRHHHorasExtras.jsx`, `frontend/src/pages/components/HEFiltrosBar.jsx` (nuevo), `frontend/src/pages/components/HETabla.jsx` (nuevo).
- **Spec ref**: *Filtros por tab*, *Selección múltiple y acciones bulk* (Aprobar, Rechazar, Cambiar %), *Edición inline % recargo antes de aprobar*.
- **Design ref**: §10.1 layout + §10.3 componentes auxiliares.
- **Acceptance**: Tabla con columnas: checkbox, Legajo, Empleado, Fecha, Tipo día, Min, %, Estado, Acciones (✓ ✗ ⓘ). Filtros sincronizados con query params URL (`empleado_id`, `fecha_desde/hasta`, `tipo_dia`, `estado`). Barra acciones bulk visible solo con selección N>0: `[Aprobar selección]` (perm `aprobar`), `[Rechazar...]` (perm `aprobar`), `[Cambiar %...]` (perm `gestionar`). Edición inline de `%` por fila (perm `gestionar`) con commit en blur/Enter → llama `horasExtrasApi.update`. Paginación al pie.
- **Complexity**: L
- **Depends on**: T-6.1

### T-6.3 — Tab Aprobadas — tabla + opción "Reabrir" + Liquidar

- **Files**: `frontend/src/pages/RRHHHorasExtras.jsx`, reutiliza `HETabla.jsx`.
- **Spec ref**: *Selección múltiple y acciones bulk* (Aprobadas: Liquidar perm `liquidar`, Reabrir perm `aprobar`).
- **Design ref**: §10.3.
- **Acceptance**: Tab muestra bloques `aprobada`. Acciones bulk: `[Liquidar selección]` (perm `liquidar`), `[Reabrir con motivo]` (perm `aprobar`). Acción individual "Reabrir" en cada fila. Modal de liquidar pide `periodo` (YYYYMM, default mes actual).
- **Complexity**: M
- **Depends on**: T-6.2

### T-6.4 — Tab Liquidadas — tabla read-only + export

- **Files**: `frontend/src/pages/RRHHHorasExtras.jsx`.
- **Spec ref**: *Botón Exportar Excel*.
- **Design ref**: §10.2.
- **Acceptance**: Tab muestra bloques `liquidada` con filtro adicional `periodo` (YYYYMM picker). Tabla read-only (sin checkboxes ni acciones individuales destructivas). Botón `[Exportar XLSX]` invoca `horasExtrasApi.exportarXlsx({ periodo })` con `responseType: 'blob'` y dispara descarga browser con nombre `horas_extras_{periodo}.xlsx`.
- **Complexity**: M
- **Depends on**: T-6.2

### T-6.5 — Tab Anomalías — tabla con CTAs

- **Files**: `frontend/src/pages/RRHHHorasExtras.jsx`.
- **Spec ref**: *Tab Anomalías* (3 scenarios: completar, descartar, descartar sin motivo bloquea).
- **Design ref**: §10.2 (estado `error_fichadas` filtrado dentro del tab Pendientes con sub-filter).
- **Acceptance**: Sub-vista del tab Pendientes O tab dedicado (decisión: tab dedicado de Anomalías por badge prioritario). Tabla con icono warning, columna `error_tipo` visible, observaciones. CTAs por fila: `[Completar fichada]` (perm `gestionar`) → modal T-6.8; `[Descartar día]` (perm `aprobar`) → modal T-6.9. Estilo visual: badge crítico en rojo/naranja.
- **Complexity**: M
- **Depends on**: T-6.2, T-6.8, T-6.9

### T-6.6 — Tab Alertas — tabla con CTAs

- **Files**: `frontend/src/pages/RRHHHorasExtras.jsx`.
- **Spec ref**: *Tab Alertas* (3 scenarios: marcar leída, reabrir desde alerta, toggle ver leídas).
- **Design ref**: §10.3 `HEPanelAlertas.jsx`.
- **Acceptance**: Tabla con: severidad (badge), tipo, mensaje, fecha, bloque vinculado (link). CTAs: `[Marcar como leída]` (perm `ver` o `gestionar` según T-4.8) → `horasExtrasApi.alertaMarcarLeida(id)`; `[Reabrir bloque]` (perm `aprobar`) → modal de reapertura T-6.9 sobre `he_id` de la alerta + marca leída automáticamente. Toggle "Ver leídas" cambia query `solo_no_leidas` y refetch. Badge contador en el tab refleja count de alertas `severidad=critical|warning` no leídas.
- **Complexity**: M
- **Depends on**: T-6.2

### T-6.7 — Modal detalle bloque (fichadas + historial)

- **Files**: `frontend/src/pages/components/HEModalHistorial.jsx` (nuevo).
- **Spec ref**: *Modal detalle del bloque* (2 scenarios).
- **Design ref**: §10.3 `HEModalHistorial.jsx`.
- **Acceptance**: Modal abierto al click ⓘ sobre fila o cualquier punto no-clickeable. Muestra: datos del bloque, fichadas asociadas (entrada + salida con timestamp), timeline cronológico de historial (`horasExtrasApi.historial(heId)`) con accion + estado_anterior→estado_nuevo + usuario + motivo. Audit fields visibles: `aprobado_por`, `liquidado_por`, `reabierto_por`. Si bloque `liquidada`: botones Liquidar/Reabrir ocultos por permiso (solo `liquidar` permite reabrir).
- **Complexity**: M
- **Depends on**: T-6.12

### T-6.8 — Modal completar fichada

- **Files**: `frontend/src/pages/components/HEModalCompletarFichada.jsx` (nuevo).
- **Spec ref**: *Completar fichada faltante* (scenario éxito).
- **Design ref**: §10.3 `HEModalCompletarFichada.jsx`.
- **Acceptance**: Form con datetime picker (timestamp), select tipo (`entrada`|`salida`), textarea motivo (min 3 chars). `[Confirmar]` disabled si motivo vacío. On submit → `horasExtrasApi.completarFichada(heId, body)`. Toast de éxito → bloque pasa a `detectada` y desaparece del tab Anomalías.
- **Complexity**: S
- **Depends on**: T-6.12

### T-6.9 — Modal rechazo / descarte / reapertura (motivo obligatorio)

- **Files**: `frontend/src/pages/components/HEModalRechazar.jsx`, `HEModalDescartarDia.jsx`, `HEModalReabrir.jsx` (3 modals nuevos, similares).
- **Spec ref**: *Rechazar requiere motivo obligatorio*, *Descartar sin motivo bloquea confirm*, *Reapertura sin motivo falla*.
- **Design ref**: §10.3.
- **Acceptance**: 3 modals con misma estructura: título contextual + textarea motivo (min 3 chars, max 2000) + botones `[Cancelar] [Confirmar]`. Confirm disabled si motivo vacío. `HEModalReabrir` muestra warning extra "Esta acción afecta una liquidación cerrada" si el bloque era `liquidada` (chequea estado del bloque). Bulk variant: motivo único aplicado a todos los seleccionados.
- **Complexity**: M
- **Depends on**: T-6.12

### T-6.10 — Modal cambio de % recargo (individual + bulk)

- **Files**: `frontend/src/pages/components/HEModalAprobar.jsx` (nuevo, también cubre cambio de % al aprobar).
- **Spec ref**: *Cambio masivo de % recargo*, *Editar % inline persiste cambio*.
- **Design ref**: §10.3 `HEModalAprobar.jsx`.
- **Acceptance**: Modal con input numérico `porcentaje_override` (0-500, opcional), textarea observaciones (opcional). Si se aprueba con override → backend setea `tipo_dia='manual'`. Bulk variant: aplica el mismo override a todos los seleccionados. Llama `horasExtrasApi.aprobar` o `bulkAprobar`.
- **Complexity**: S
- **Depends on**: T-6.12

### T-6.11 — CSS Modules siguiendo design tokens

- **Files**: `frontend/src/pages/RRHHHorasExtras.module.css`.
- **Spec ref**: convención frontend repo (Tesla Design System).
- **Design ref**: §10.4 reglas (100% design tokens, NO hardcoded, estados visuales, dark mode, sticky header).
- **Acceptance**: 100% `var(--color-*)` y `var(--spacing-*)` y `var(--radius-*)`. NO valores hex/rgb/px hardcoded (excepción: `0` o `1px` para borders cuando convencional). Clases para cada estado: `.estado--detectada`, `.estado--error_fichadas`, `.estado--pendiente_asignacion_turno`, `.estado--aprobada`, `.estado--rechazada`, `.estado--liquidada`. Badges de alertas no leídas (chip critical). Modo oscuro vía tokens existentes. Header de tabla con `position: sticky; top: 0`.
- **Complexity**: M
- **Depends on**: —

### T-6.12 — API methods en `services/api.js`

- **Files**: `frontend/src/services/api.js`.
- **Spec ref**: convención repo (axios via `services/api.js`).
- **Design ref**: §10.5 (código completo de `horasExtrasApi`).
- **Acceptance**: Append del objeto `horasExtrasApi` con TODOS los 18 métodos del design §10.5: `list`, `get`, `create`, `update`, `aprobar`, `rechazar`, `reabrir`, `bulkAprobar`, `bulkRechazar`, `completarFichada`, `descartarDia`, `recalcular`, `liquidar`, `alertasList`, `alertaMarcarLeida`, `historial`, `configGet`, `configPut`, `exportarXlsx` (con `responseType: 'blob'`). Export named.
- **Complexity**: S
- **Depends on**: —

### T-6.13 — Registrar ruta en `App.jsx` + entrada en Sidebar

- **Files**: `frontend/src/App.jsx`, `frontend/src/components/Sidebar.jsx`.
- **Spec ref**: *Visibilidad condicional de acciones según permisos* + convención del repo.
- **Design ref**: §10.7 Routing y Sidebar.
- **Acceptance**: `App.jsx`: ruta nueva `/rrhh/horas-extras` lazy-loaded (`React.lazy`). `Sidebar.jsx`: entrada "Horas Extras" dentro de la sección "RRHH" (después de "Horarios" o "Sueldos" según orden actual), gateada por `usePermisos().tienePermiso('rrhh.ver_horas_extras')`. Icono consistente con otras entradas RRHH.
- **Complexity**: S
- **Depends on**: T-6.1

### T-6.14 — Permission checks con `usePermisos()`

- **Files**: `frontend/src/pages/RRHHHorasExtras.jsx` y todos los componentes auxiliares.
- **Spec ref**: *Visibilidad condicional de acciones según permisos* (2 scenarios).
- **Design ref**: §10.7 + convención repo (hook existente).
- **Acceptance**: Cada botón/CTA visible solo si el usuario tiene el permiso correspondiente:
  - `rrhh.ver_horas_extras`: render del componente entero (sino "permiso denegado").
  - `rrhh.gestionar_horas_extras`: gates `[Detectar]` global, edición inline %, `[Completar fichada]`, `[Cambiar %...]`, `[Marcar leída]` (si es la regla en T-4.8).
  - `rrhh.aprobar_horas_extras`: gates `[Aprobar...]`, `[Rechazar...]`, `[Reabrir...]`, `[Descartar día]`.
  - `rrhh.liquidar_horas_extras`: gate `[Liquidar...]` y `[Reabrir]` sobre `liquidada`.
  Botones deshabilitados (con tooltip) en lugar de ocultos cuando es contextual (estado del bloque); ocultos cuando es por permiso ausente.
- **Complexity**: M
- **Depends on**: T-6.1..T-6.10

---

## Batch 7 — Integración con `RRHHSueldos.jsx` ✅ DONE (2026-04-30)

> **Spec**: requirement frontend *Integración con `RRHHSueldos.jsx`*.
> **Design**: §10.6.

> **Implementación**: T-7.1 verificada (endpoint completo en `backend/app/routers/rrhh_horas_extras.py:954-1088` — castellano rioplatense, DD/MM/YYYY, decimales con coma, mime correcto, freeze panes, filename `horas_extras_{periodo}.xlsx`). T-7.2 implementada en `frontend/src/pages/RRHHSueldos.jsx` + `RRHHSueldos.module.css` (sección "Horas Extras del Período" con month input, resumen agregado, tabla agrupada por empleado, botones "Ver detalle" y "Descargar Excel", permission gate `rrhh.ver_horas_extras`, soft cap 1000 con banner de truncado). T-7.3 documentada en JSDoc (convención de horas equivalentes y flag para revisar columnas con equipo de sueldos antes de uso productivo).

### T-7.1 — Endpoint export Excel del período (revisión 2 — Q1) ✅

- **Files**: ya entregado en T-4.7. Esta task es VERIFICACIÓN/AJUSTES si Sueldos requiere variantes adicionales (ej. agrupado por empleado).
- **Spec ref**: *Sueldos consume HE del período*, *Export Excel del período*.
- **Design ref**: §10.6.
- **Acceptance**: ✅ VERIFICADO. Endpoint `GET /rrhh/horas-extras/exportar?periodo=YYYYMM[&estado=liquidada]` (`rrhh_horas_extras.py:954`) retorna `StreamingResponse` con mime `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`, filename `horas_extras_{periodo}.xlsx`, headers en castellano rioplatense (Legajo · Apellido y Nombre · CUIL · Fecha · Tipo de día · Minutos extra · % Recargo · Estado · Observaciones · Motivo de rechazo), fechas DD/MM/YYYY, decimales con coma, freeze panes A2. Para el flujo de Sueldos, no se requiere endpoint agregado adicional: la grilla en pantalla agrega client-side desde `horasExtrasApi.list({estado: 'liquidada', periodo, page_size: 1000})`.
- **Complexity**: S
- **Depends on**: T-4.7

### T-7.2 — Botón en `RRHHSueldos.jsx` para descargar HE del período ✅

- **Files**: `frontend/src/pages/RRHHSueldos.jsx`, `frontend/src/pages/RRHHSueldos.module.css`.
- **Spec ref**: *Sueldos muestra HE liquidadas del período*.
- **Design ref**: §10.6.
- **Acceptance**: ✅ Sección "Horas Extras del Período" agregada debajo de la tabla de datos bancarios (sin alterar funcionalidad existente). Componentes:
  - Selector `<input type="month">` con default mes anterior al actual.
  - Resumen: Empleados con HE, Total horas 50%, Total horas 100% (formateados es-AR).
  - Botón "Ver detalle" → `useNavigate` a `/rrhh/horas-extras?periodo=YYYYMM&estado=liquidada`.
  - Botón "Descargar Excel" → `horasExtrasApi.exportarXlsx({ periodo })` con patrón blob (Blob → ObjectURL → anchor click → revoke).
  - Tabla agregada por empleado: Legajo · Apellido y Nombre · Horas 50% · Horas 100% · Horas equivalentes (h50*1.5 + h100*2.0). Tooltips con minutos exactos.
  - Permission gate: visible sólo si `tienePermiso('rrhh.ver_horas_extras')`.
  - Loading + error states + soft cap 1000 con banner de truncado (`HE_PAGE_SIZE_CAP`).
  - Fuente: `horasExtrasApi.list({ estado: 'liquidada', periodo, page: 1, page_size: 1000 })` agrupado client-side por `empleado_id`. Clasificación por `tipo_dia`: `habil_50` → 50%; `sabado_100|domingo_100|feriado_100` → 100%; otros (manual) → según `porcentaje_recargo` (≥100 → 100%, sino 50%).
- **Complexity**: M
- **Depends on**: T-6.12, T-4.7

### T-7.3 — Validar columnas y flujo de liquidación de sueldos ✅

- **Files**: `frontend/src/pages/RRHHSueldos.jsx` (JSDoc top-level).
- **Spec ref**: convergencia entre módulos (proposal §10 success criteria).
- **Design ref**: §10.6 (Sueldos NO modifica HE — solo lee, redirige al módulo HE para edits).
- **Acceptance**: ✅ Confirmado:
  - El panel de HE en Sueldos es READ-ONLY: NO ofrece botones de editar / aprobar / rechazar / liquidar. Sólo "Ver detalle" (que delega a `/rrhh/horas-extras?periodo=...&estado=liquidada` para acciones) y "Descargar Excel".
  - Convención documentada en JSDoc del componente: `horas_eq = h50 * 1.5 + h100 * 2.0`. Columnas Excel exportadas vs. columnas en pantalla quedan listadas en el mismo bloque.
  - Flag explícito en el JSDoc: el formato Excel debe revisarse con el equipo de sueldos antes del primer uso productivo. Si requieren CUIL en grilla, separar Apellido/Nombre, o cualquier otro ajuste, se modifica el endpoint backend `rrhh_horas_extras.exportar_excel`.
- **Complexity**: S
- **Depends on**: T-7.2

---

## Batch 8 — Tests ✅ DONE (2026-04-30)

> **Spec**: TODOS los scenarios del spec deben tener cobertura. **Repo no tiene runner configurado** (`AGENTS.md`: "no tests configured — manual testing"); estos tasks documentan los **casos de prueba manual via API endpoints/curl/UI** que verifican cada scenario. Si en el futuro se agrega `pytest`, los scripts manuales sirven como base.
> **Design**: §11 Tests recomendados (lista por capability).

> **Implementación T-8.1..T-8.9**: 9 scripts standalone bajo `backend/app/scripts/test_manual_rrhh_he_*.py`. Cada uno se ejecuta con `python -m app.scripts.<nombre>`, imprime PASS/FAIL por aserción, hace cleanup automático en `finally` y retorna exit 0 si todo pasa, 1 si algún fallo.
>
> | Task  | Script (`backend/app/scripts/...`)              | Cómo correr                                                      |
> |-------|--------------------------------------------------|------------------------------------------------------------------|
> | T-8.1 | `test_manual_rrhh_he_clasificacion.py`           | `python -m app.scripts.test_manual_rrhh_he_clasificacion`        |
> | T-8.2 | `test_manual_rrhh_he_calculo_dia.py`             | `python -m app.scripts.test_manual_rrhh_he_calculo_dia`          |
> | T-8.3 | `test_manual_rrhh_he_state_machine.py`           | `python -m app.scripts.test_manual_rrhh_he_state_machine`        |
> | T-8.4 | `test_manual_rrhh_he_listener_fichada.py`        | `python -m app.scripts.test_manual_rrhh_he_listener_fichada`     |
> | T-8.5 | `test_manual_rrhh_he_listener_horario.py`        | `python -m app.scripts.test_manual_rrhh_he_listener_horario`     |
> | T-8.6 | `test_manual_rrhh_he_cap_recalculo.py`           | `python -m app.scripts.test_manual_rrhh_he_cap_recalculo`        |
> | T-8.7 | `test_manual_rrhh_he_purga.py`                   | `python -m app.scripts.test_manual_rrhh_he_purga`                |
> | T-8.8 | `test_manual_rrhh_he_permisos.py`                | `python -m app.scripts.test_manual_rrhh_he_permisos` (estático)  |
> | T-8.9 | `test_manual_rrhh_he_export_excel.py`            | `python -m app.scripts.test_manual_rrhh_he_export_excel`         |
>
> Notas:
> - T-8.3, T-8.4, T-8.5, T-8.6, T-8.9 requieren un `Usuario(id=1)` existente en la DB para los FK (aprobado_por_id, etc.). Si no existe el id=1, los scripts hacen SKIP con WARN explicativo.
> - T-8.4 y T-8.5 importan `app.events.rrhh_he_hooks` explícitamente para registrar los listeners (sin pasar por `app.main`).
> - T-8.8 valida los permisos por análisis estático del router (regex sobre `_check_permiso(... "<codigo>")`), no E2E con HTTP. La verificación E2E queda cubierta por T-9.4.
> - Todos los scripts usan suffixes `TEST_HE_T8X_<timestamp>` para identificar y limpiar su propia data.

### T-8.1 — Casos manuales del service (clasificación tipo_dia, sábado, validación fichadas)

- **Files**: `backend/app/scripts/test_manual_rrhh_he_service.py` (nuevo, opcional pero recomendado).
- **Spec ref**: *Detección automática*, *Clasificación tipo_dia*, *Fichadas desbalanceadas*, *Tolerancia*.
- **Design ref**: §11.1.
- **Acceptance**: Script ejecutable que: (a) instancia `HorasExtrasService(SessionLocal())`, (b) corre los **3 casos del proposal** (turno mañana+tarde 8-13/15-19) sobre fichadas mock conocidas, (c) verifica resultados esperados (0h / 2h / 1h respectivamente), (d) imprime PASS/FAIL. Casos extras: sábado 11-15 cruzando 13:00 → 2 bloques; fichadas impares → `error_fichadas`; HE bajo tolerancia → no se persiste; día con presentismo `vacaciones` → no se crea.
- **Complexity**: M
- **Depends on**: T-2.4

### T-8.2 — Casos manuales del cálculo turno mañana+tarde (3 scenarios del spec)

- **Files**: incluido en T-8.1 o sub-script dedicado.
- **Spec ref**: *Empleado cumple el turno exacto sin extras*, *Empleado trabaja en corrido*, *Empleado se queda más allá*.
- **Design ref**: §11.1 + spec scenarios 1-3.
- **Acceptance**: Sub-tests parametrizados con las 3 entradas de fichadas del spec; assert `extras_minutos in {0 (no se persiste), 120, 60}` y `estado='detectada'` para los que se persisten.
- **Complexity**: S
- **Depends on**: T-8.1

### T-8.3 — Casos manuales de transiciones de estado (state machine)

- **Files**: `backend/app/scripts/test_manual_rrhh_he_workflow.py` (nuevo).
- **Spec ref**: *Workflow de estados con permisos diferenciados*, *Bloques aprobados/rechazados/liquidados son inmutables ante el cron*, *Reapertura manual*.
- **Design ref**: §11.2 + §3.1 reglas de transición.
- **Acceptance**: Script que crea bloque `detectada` y lo lleva por el camino feliz: `detectada → aprobada → liquidada` y verifica audit fields. Casos error: aprobar `error_fichadas` → 422; rechazar sin motivo → 422; reabrir `liquidada` sin permiso liquidar → 403; reabrir con permiso → vuelve a `aprobada`. Bulk: 5 bloques mixtos (3 detectada, 1 error_fichadas, 1 aprobada) → response detalla los 5 con status individual.
- **Complexity**: M
- **Depends on**: T-2.6, T-2.8

### T-8.4 — Caso manual del event listener (modificación fichada → alerta)

- **Files**: `backend/app/scripts/test_manual_rrhh_he_hooks.py` (nuevo).
- **Spec ref**: *Edición de fichada vinculada a bloque aprobado dispara alerta*, *Edición de fichada vinculada a bloque detectada SÍ recalcula*.
- **Design ref**: §11.3.
- **Acceptance**: Crear bloque `aprobada` con `fichada_entrada_id=F1`, editar F1 vía ORM → verificar que se inserta 1 alerta `recalculo_divergente` con contexto, bloque NO cambia. Eliminar F1 → alerta `fichada_eliminada`. Crear bloque `detectada` con fichada → editar fichada → recálculo automático, NO alerta. Doble edición rápida → no duplica alertas (idempotencia chequeada por `(he_id, tipo, fichada_id)`).
- **Complexity**: M
- **Depends on**: T-3.1

### T-8.5 — Caso manual del event listener (cambio empleado_horario → recálculo + alerta liquidada) — revisión 2

- **Files**: `backend/app/scripts/test_manual_rrhh_he_hooks.py`.
- **Spec ref**: revisión 2 Q3.
- **Design ref**: revisión 2.
- **Acceptance**: Crear bloque `aprobada` (E, F, habil_50). Editar `RRHHEmpleadoHorario` del empleado E con `fecha_desde <= F` → verificar bloque vuelve a `detectada` con motivo automático en historial. Crear bloque `liquidada` (E, F2, habil_50, periodo=202604). Editar empleado_horario nuevamente → bloque NO cambia, se inserta alerta `liquidacion_afectada_por_cambio_turno` severidad `critical`. Cap 90 días: editar empleado_horario con `fecha_desde = today - 200` → solo se procesan bloques desde `today - 90`.
- **Complexity**: M
- **Depends on**: T-3.2

### T-8.6 — Casos manuales del cap 90 días en endpoint recálculo (revisión 2 Q2)

- **Files**: `backend/app/scripts/test_manual_rrhh_he_endpoints.py` (nuevo).
- **Spec ref**: revisión 2 Q2.
- **Design ref**: §12 riesgo performance.
- **Acceptance**: 3 curls sobre `POST /rrhh/horas-extras/recalcular`:
  - `fecha_desde=2026-01-01, fecha_hasta=2026-04-01` (90 días) → 200 OK.
  - `fecha_desde=2026-01-01, fecha_hasta=2026-04-02` (91 días) → 422 Unprocessable Entity con detail conteniendo "cap".
  - `fecha_desde=2026-04-01, fecha_hasta=2026-03-30` (orden invertido) → 422 con detail "fecha_hasta debe ser >= fecha_desde".
- **Complexity**: S
- **Depends on**: T-4.6

### T-8.7 — Caso manual de purga de alertas (revisión 2 Q4)

- **Files**: `backend/app/scripts/test_manual_rrhh_he_hooks.py`.
- **Spec ref**: revisión 2 Q4.
- **Design ref**: revisión 2.
- **Acceptance**: Insertar 3 alertas: una `leida_at = today - 20 days` (debe purgarse con default 15), una `leida_at = today - 10 days` (no purgar), una `leida_at = NULL` (NO purgar nunca). Llamar `service.purgar_alertas_viejas()` → verificar `{purgadas: 1, retenidas: 2}`. Cambiar `dias_retencion_alertas=30` y reejecutar → 0 purgadas. Run cron y confirmar que purga es ejecutada como último step (T-5.3).
- **Complexity**: S
- **Depends on**: T-2.11, T-5.3

### T-8.8 — Casos manuales de permisos (403 sin permiso en cada endpoint sensible)

- **Files**: `backend/app/scripts/test_manual_rrhh_he_endpoints.py`.
- **Spec ref**: *Permisos del módulo (4)* (3 scenarios), *Aprobar sin permiso retorna 403*, *Liquidar sin permiso retorna 403*.
- **Design ref**: §11.2.
- **Acceptance**: Token de usuario con SOLO `rrhh.ver_horas_extras`:
  - `GET /rrhh/horas-extras` → 200.
  - `PATCH /rrhh/horas-extras/{id}/aprobar` → 403.
  - `POST /rrhh/horas-extras/liquidar` → 403.
  - `POST /rrhh/horas-extras/{id}/completar-fichada` → 403.
  Token con `gestionar` (sin `aprobar`): aprobar → 403, completar-fichada → 200. Token con `aprobar` (sin `liquidar`): liquidar → 403. Token con SUPERADMIN (wildcard): todo OK.
- **Complexity**: S
- **Depends on**: T-4.3, T-4.4, T-4.5, T-4.6, T-4.7

### T-8.9 — Caso manual de export Excel (formato es-AR, headers correctos)

- **Files**: manual via curl + abrir XLSX en LibreOffice/Excel.
- **Spec ref**: *Export Excel del período liquidado* (2 scenarios), revisión 2 Q1.
- **Design ref**: §11.2.
- **Acceptance**: Liquidar 5 bloques periodo=202604. `GET /rrhh/horas-extras/exportar?periodo=202604` → descarga XLSX. Abrir y verificar:
  - Headers en castellano rioplatense: "Legajo", "Apellido y Nombre", "Fecha", "Tipo de día", "Minutos extra", "% Recargo", "Estado", "Observaciones", "Motivo de rechazo".
  - Fechas en formato DD/MM/YYYY (ej. "29/04/2026").
  - 5 filas + header.
  - Header bold + freeze panes en fila 2.
  Periodo sin liquidaciones (202601): retorna XLSX con headers solo, sin filas, NO error.
- **Complexity**: S
- **Depends on**: T-4.7

---

## Batch 9 — Verificación previa al deploy

> **Spec**: success criteria del proposal §10.
> **Design**: §11 + §12 mitigaciones.

### T-9.1 — `alembic upgrade head` en dev DB

- **Files**: ninguno (operación DB).
- **Spec ref**: *Migración seedea singleton*, success criteria proposal.
- **Design ref**: §4.
- **Acceptance**: Ejecutar `cd backend && alembic upgrade head`. Verificar que las 4 tablas existen (`\d rrhh_horas_extras*` en psql). Verificar que el singleton de config está seedeado con defaults de revisión 2 incluidos: `SELECT * FROM rrhh_horas_extras_config WHERE id=1` muestra `dias_retencion_alertas=15` y `cap_dias_recalculo_manual=90`. Si la DB de dev tiene datos previos en tablas RRHH, NO deben ser tocadas. `alembic downgrade -1` y `alembic upgrade head` deben funcionar idempotente.
- **Complexity**: S
- **Depends on**: T-1.6, T-1.7

### T-9.2 — Sanity check: 4 permisos creados, asignaciones a roles

- **Files**: ninguno (queries DB).
- **Spec ref**: *Permisos del módulo (4)*.
- **Design ref**: §4.1 paso 5.
- **Acceptance**: `SELECT codigo, es_critico FROM permisos WHERE codigo LIKE 'rrhh.%horas_extras%'` retorna 4 filas con `aprobar` y `liquidar` con `es_critico=true`. `SELECT r.codigo, p.codigo FROM roles_permisos_base rpb JOIN roles r ON r.id=rpb.rol_id JOIN permisos p ON p.id=rpb.permiso_id WHERE p.codigo LIKE 'rrhh.%horas_extras%'` retorna ADMIN×4 + GERENTE×1 (`ver`).
- **Complexity**: S
- **Depends on**: T-9.1

### T-9.3 — Probar cron manualmente con un día de fichadas conocidas

- **Files**: ninguno (operación CLI).
- **Spec ref**: *Cron procesa D-1 completo determinístico*, *Cron libera lockfile en error*, *Cron deshabilitado por config*.
- **Design ref**: §11.4.
- **Acceptance**: Setear `cron_activo=false` en config + ejecutar `python -m app.scripts.cron_rrhh_horas_extras` → exit 3, log warning, no procesa. Setear `cron_activo=true` + tener fichadas conocidas para `today - 1`. Ejecutar → exit 0, log con counts, bloques creados. Re-ejecutar inmediatamente sin esperar lock release → exit 1 (lockfile activo). Re-ejecutar después → idempotente, no duplica.
- **Complexity**: S
- **Depends on**: T-5.4, T-9.1

### T-9.4 — Smoke test E2E: detección → aprobación → liquidación → export

- **Files**: ninguno (UI + DB queries).
- **Spec ref**: success criteria proposal §10 (todos los items).
- **Design ref**: §11 (combinado).
- **Acceptance**: Flujo end-to-end:
  1. Cron corre y crea bloques `detectada` para D-1.
  2. UI: navegar a `/rrhh/horas-extras`, tab Pendientes muestra los bloques.
  3. Aprobar 1 bloque con override % → tab Aprobadas muestra con `tipo_dia='manual'` y audit fields.
  4. Liquidar el bloque (periodo del mes actual) → tab Liquidadas lo muestra.
  5. Exportar XLSX del periodo → archivo descargado, headers correctos, fecha DD/MM/YYYY.
  6. Editar la fichada del bloque liquidada → alerta `recalculo_divergente` aparece en tab Alertas.
  7. Reabrir el bloque desde la alerta → vuelve a `aprobada`, alerta marcada leída.
  8. Editar empleado_horario del empleado afectado → alerta `liquidacion_afectada_por_cambio_turno` (revisión 2 Q3).
  Verificar que cada paso registra fila en historial.
- **Complexity**: M
- **Depends on**: T-9.3, T-6.13, T-7.2

---

## Resumen ejecutivo

| Batch | Tasks | Foco |
|-------|-------|------|
| 1 | 8 | Modelos + migración + permisos (foundation) |
| 2 | 11 | Service layer (lógica de negocio + revisión 2) |
| 3 | 3 | Event listeners (hooks fichadas + horarios) |
| 4 | 11 | Schemas Pydantic + Router (21 endpoints) |
| 5 | 5 | Cron script (lockfile + purga) |
| 6 | 14 | Frontend page + 9 modales + componentes |
| 7 | 3 | Integración con `RRHHSueldos.jsx` |
| 8 | 9 | Tests manuales (cobertura de scenarios) |
| 9 | 4 | Verificación pre-deploy |
| **Total** | **68** | |

### Implementation order

Batches secuenciales 1 → 9. Tasks dentro de un batch pueden paralelizarse; sus `Depends on` indican deps intra-batch específicas. Foundation (Batch 1) habilita Service (Batch 2), que habilita listeners (Batch 3) y router (Batch 4). El cron (Batch 5) depende del service. El frontend (Batch 6) depende solo de los API methods que se publican junto con el router (Batch 4). Sueldos (Batch 7) depende del export del router. Tests (Batch 8) cubren cada capability ya implementada. Verificación final (Batch 9) consolida el deploy.

### Next step

`sdd-apply` empezando por **Batch 1** (T-1.1 a T-1.8 en paralelo donde lo permitan las deps).
