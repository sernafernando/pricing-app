# Proposal: RRHH — Horas Extras (detección, aprobación y liquidación)

**Change**: `rrhh-horas-extras`
**Status**: Proposal
**Date**: 2026-04-30
**Mode**: hybrid (Engram + openspec/)
**Depends on**: `rrhh-module` (ya implementado — Phase 7 de horarios/fichadas)

---

## 1. Intent

El módulo RRHH ya cuenta con `rrhh_fichadas` (Hikvision/manual/mobile), `rrhh_horarios_config` (turnos), `rrhh_empleado_horarios` (M:N empleado–turno con prioridad `principal`), `rrhh_horarios_excepciones` (feriados) y `rrhh_reportes_service.horas_trabajadas` (que calcula horas trabajadas, **pero NO clasifica como horas extras**).

Falta la capa de **detección, aprobación y liquidación de horas extras (HE)**:

- No existe un cálculo automático de excedente sobre el turno teórico.
- No hay workflow de aprobación / rechazo / liquidación con auditoría.
- No hay diferenciación de tipo de día (hábil 50%, sábado/domingo/feriado 100%).
- No hay tolerancia específica para HE (la `tolerancia_minutos` de `rrhh_horarios_config` es para tardanzas, NO para HE — no se debe reutilizar).
- No hay reporte mensual exportable para liquidación de sueldos.
- No hay contemplación de empleados sin turno asignado o con fichadas en días sin turno (sábados sin turno, etc.).

Este cambio cierra ese gap: convierte fichadas crudas en HE auditables y liquidables, integradas con el sistema de permisos y con los sueldos.

---

## 2. Scope

### 2.1 In Scope

**Backend**

- Nuevo modelo `RRHHHorasExtras` (tabla `rrhh_horas_extras`): un registro por empleado por día con `extras_minutos`, `tipo_dia`, `porcentaje_recargo`, `estado`, auditoría de aprobación/liquidación.
- Nuevo modelo `RRHHHorasExtrasConfig` (tabla `rrhh_horas_extras_config`, singleton): porcentajes default por tipo de día, hora_corte_sabado, `tolerancia_extras_minutos`, flag `requiere_aprobacion`.
- Migración Alembic (`YYYYMMDD_rrhh_horas_extras.py`) que crea ambas tablas + seed del singleton de config con valores default (50/100/100/100, corte sábado 13:00, tolerancia 15min, requiere_aprobacion=true).
- Servicio `rrhh_horas_extras_service.py` con la lógica de detección:
  - `detectar_dia(empleado_id, fecha)` → calcula HE de un empleado/día a partir de fichadas y turnos asignados.
  - `detectar_lote(fecha)` → corre detección sobre todos los empleados activos para una fecha.
  - `recalcular_empleado(empleado_id, fecha_desde, fecha_hasta)` → reprocesa al asignar turnos retroactivamente.
  - `aprobar_bloque`, `rechazar_bloque`, `liquidar_periodo`.
- Nuevo router `rrhh_horas_extras.py` (prefijo `/rrhh/horas-extras`) con CRUD + acciones de workflow + endpoints de config + export Excel.
- 4 nuevos permisos en categoría `RRHH` (códigos en sección 5).
- Cron diario que invoca `detectar_lote(yesterday)`. Hora exacta a definir en design (debe NO colisionar con `sync_hikvision_fichadas.py` ni con los `sync_*_incremental.py` activos).
- Endpoint consumible por `RRHHSueldos.jsx` que devuelve HE liquidadas del período.

**Frontend**

- Nueva página `frontend/src/pages/RRHHHorasExtras.jsx` + `RRHHHorasExtras.module.css` (CSS Modules, Tesla Design System).
- 3 tabs: **Pendientes** | **Aprobadas** | **Liquidadas**.
- Filtros: empleado, rango de fecha, estado, tipo_dia.
- Acciones masivas (sobre selección): aprobar selección, cambiar % a múltiples, rechazar con motivo.
- Edición inline de `porcentaje_recargo` por bloque al momento de aprobar.
- Botón "Re-detectar día" para recalcular un bloque manualmente.
- Botón "Exportar Excel" del período liquidación.
- Estado adicional visible: `pendiente_asignacion_turno` (empleado sin turno).
- Vinculación con sueldos: la pestaña "Liquidadas" alimenta `RRHHSueldos.jsx`.

### 2.2 Out of Scope

- **Cálculo monetario** del importe de la HE (peso × hora × %) — eso vive en `RRHHSueldos`, este módulo entrega minutos × % y deja al de sueldos multiplicar por valor hora.
- **Aprobación condicional / multi-nivel** (workflow con dos firmantes). Hay un único nivel: usuario con `rrhh.aprobar_horas_extras`.
- **Notificaciones automáticas** (mail/push) al empleado o supervisor.
- **Compensación con días libres** (banco de horas) — fuera de alcance, se evalúa en cambio futuro.
- **HE en días de licencia/ART/vacaciones** — explícitamente NO se generan HE en días con presentismo `vacaciones`/`art`/`licencia`. Si las fichadas existen igual, el bloque se descarta con observación automática.
- **Modificación retroactiva de la regla** (cambiar % default no recalcula liquidaciones ya cerradas).
- **Edición masiva de fichadas** desde esta página (ya existe en `RRHHHorarios`).

---

## 3. Approach

### 3.1 Definición de horas extras

```
HE_minutos(empleado, fecha) = max(0, trabajado_real_minutos - turno_teorico_total_minutos)
```

donde:

- `trabajado_real_minutos` = suma de pares `(entrada_i, salida_i)` ordenados por timestamp en la fecha. Si quedan fichadas desbalanceadas, el bloque se marca anomalía y NO se computa HE hasta corrección manual.
- `turno_teorico_total_minutos` = suma de minutos teóricos de TODOS los turnos asignados al empleado para ese día (mediante `rrhh_empleado_horarios` filtrando por `dias_semana` del turno).
- Solo se registra si `HE_minutos > tolerancia_extras_minutos` (default 15). Por debajo de la tolerancia: NO se crea registro.

**Casos clave (locked con el usuario)** — turno mañana 8-13 + tarde 15-19 (teórico 9h):

| Fichadas | Trabajado | Teórico | HE |
|---|---|---|---|
| 8→13, 15→19 (4 fichadas, hace pausa) | 9h | 9h | 0 |
| 8→19 (2 fichadas, no fichó pausa) | 11h | 9h | 2h |
| 8→13, 15→20 (4 fichadas, se quedó) | 10h | 9h | 1h |

El sistema **confía en las fichadas crudas**: si el empleado no fichó la pausa, esos minutos cuentan como trabajados. Es responsabilidad del empleado fichar entrada/salida correctas; cualquier corrección se hace editando fichadas en `RRHHHorarios`, lo que dispara recálculo del día.

### 3.2 Detección automática (cron)

- Job nightly que llama a `detectar_lote(yesterday)`.
- Idempotente: si ya existe `rrhh_horas_extras` para ese empleado+fecha y `estado` es `detectada` o `pendiente_asignacion_turno`, se reescribe; si está `aprobada`, `rechazada` o `liquidada`, se conserva (se loggea diferencia para auditoría).
- Disparable manualmente desde UI por usuarios con `rrhh.gestionar_horas_extras` (botón "Detectar día/rango").
- Hora exacta del cron y método (entry de `sync_all_incremental.sh`, systemd timer, Celery beat, etc.) → a resolver en `sdd-design`. Constraint: NO colisionar con `sync_hikvision_fichadas.py` ni con los `sync_*_incremental.py` que ya corren.

### 3.3 Clasificación tipo de día (mixto, editable)

| Día | Tipo | % default |
|---|---|---|
| Lunes a Viernes (cualquier hora) | `habil_50` | 50% |
| Sábado hasta `hora_corte_sabado` (13:00 default) | `habil_50` | 50% |
| Sábado desde `hora_corte_sabado` | `sabado_100` | 100% |
| Domingo | `domingo_100` | 100% |
| Fecha en `rrhh_horarios_excepciones` con `tipo='feriado'` | `feriado_100` | 100% |
| Override manual al aprobar | `manual` | editable libre |

- Si las HE de un día cruzan el corte de sábado (ej. trabaja sábado 11-15: 2h hábil + 2h al 100%), se generan **dos registros** distintos para ese empleado/fecha — uno por tramo.
- El default por tipo es **configurable globalmente** desde `rrhh_horas_extras_config`. Cambiarlo NO recalcula registros ya `aprobada`/`liquidada`.
- Al aprobar, el aprobador puede sobreescribir `porcentaje_recargo` del bloque (queda `tipo_dia='manual'` con audit trail).

### 3.4 Workflow de estados

```
[detectada] ──aprobar──▶ [aprobada] ──liquidar──▶ [liquidada]
     │                       │
     └───rechazar──▶ [rechazada]
     │
     └─(sin turno)─▶ [pendiente_asignacion_turno] ──reasignar turno──▶ recalcular ──▶ [detectada]
```

- Granularidad: **por bloque** (un empleado, un día, un tramo de tipo_dia). NO bulk a nivel empleado/día.
- UI permite acciones masivas sobre **selección de bloques**, pero internamente es loop de operaciones individuales con su propio audit (`aprobado_por_id`, `aprobado_at`, `motivo_rechazo`).
- `liquidar_periodo(yyyymm)` marca como `liquidada` todas las `aprobada` del período y setea `liquidacion_periodo`. Solo permitido a usuarios con `rrhh.liquidar_horas_extras`.

### 3.5 Anomalías

| Caso | Comportamiento |
|---|---|
| Empleado SIN turno asignado | Se crea registro con `estado='pendiente_asignacion_turno'`, `turno_esperado_minutos=0`, `extras_minutos=trabajado_minutos`. NO se calcula tipo_dia hasta tener turno. Se conservan fichadas. Al asignar turno, el sistema recalcula retroactivamente (job manual o automático al guardar `rrhh_empleado_horarios`). |
| Empleado CON turno general pero NO en ese día de la semana (ej. trabaja sábado pero no tiene turno de sábado) | `turno_esperado_minutos=0`. Las horas trabajadas cuentan **completas** como HE. `tipo_dia` = clasificación normal según fecha. `estado='detectada'`. |
| Fichadas desbalanceadas (cantidad impar o sin par entrada/salida) | `estado='detectada'`, `extras_minutos=NULL`, `observaciones='Fichadas desbalanceadas, requiere corrección'`. No bloquea aprobación pero se muestra warning en UI. |
| Día con presentismo `vacaciones`/`art`/`licencia` | NO se crea registro de HE aunque haya fichadas. Se loggea en `observaciones` del día siguiente. |
| Cambio retroactivo de fichada (edit manual) | El servicio recalcula el día afectado si `estado in ('detectada', 'pendiente_asignacion_turno')`. Si ya estaba aprobada/rechazada/liquidada NO se recalcula automático — requiere acción manual ("Re-detectar día"). |

---

## 4. Modelo tentativo (a refinar en design)

### 4.1 `rrhh_horas_extras`

| Campo | Tipo | Notas |
|---|---|---|
| `id` | int PK | |
| `empleado_id` | FK `rrhh_empleados.id` ON DELETE CASCADE, indexed | |
| `fecha` | date, indexed | |
| `fichada_entrada_id` | FK `rrhh_fichadas.id` nullable | primer entrada del tramo |
| `fichada_salida_id` | FK `rrhh_fichadas.id` nullable | última salida del tramo |
| `turno_esperado_minutos` | int | suma de minutos teóricos del/los turnos del día (0 si sin turno) |
| `trabajado_minutos` | int | minutos efectivos por pares entrada/salida |
| `extras_minutos` | int nullable | `max(0, trabajado - teorico)`. NULL si fichadas desbalanceadas |
| `tipo_dia` | varchar(20) | `habil_50` \| `sabado_100` \| `domingo_100` \| `feriado_100` \| `manual` |
| `porcentaje_recargo` | numeric(5,2) | editable por aprobador |
| `estado` | varchar(30), indexed | `detectada` \| `aprobada` \| `rechazada` \| `liquidada` \| `pendiente_asignacion_turno` |
| `aprobado_por_id` | FK `usuarios.id` nullable | |
| `aprobado_at` | datetime tz nullable | |
| `motivo_rechazo` | text nullable | |
| `liquidacion_periodo` | varchar(6) nullable, indexed | `YYYYMM` cuando `estado='liquidada'` |
| `liquidado_por_id` | FK `usuarios.id` nullable | |
| `liquidado_at` | datetime tz nullable | |
| `generada_por` | varchar(10) | `sistema` \| `manual` |
| `generada_por_id` | FK `usuarios.id` nullable | si `generada_por='manual'` |
| `observaciones` | text nullable | |
| `created_at` / `updated_at` | datetime tz | server defaults estándar |

**Índices**:
- `idx_rrhh_he_empleado_fecha (empleado_id, fecha)`
- `idx_rrhh_he_estado_fecha (estado, fecha)`
- `idx_rrhh_he_liquidacion (liquidacion_periodo)` (parcial WHERE NOT NULL)
- `uq_rrhh_he_empleado_fecha_tipo (empleado_id, fecha, tipo_dia)` — evita duplicados cuando el cron reejecuta

### 4.2 `rrhh_horas_extras_config` (singleton)

| Campo | Tipo | Default |
|---|---|---|
| `id` | int PK | siempre `1` (singleton, check constraint) |
| `porcentaje_dia_habil` | numeric(5,2) | 50.00 |
| `porcentaje_sabado_pm` | numeric(5,2) | 100.00 |
| `porcentaje_domingo` | numeric(5,2) | 100.00 |
| `porcentaje_feriado` | numeric(5,2) | 100.00 |
| `hora_corte_sabado` | time | 13:00:00 |
| `tolerancia_extras_minutos` | int | 15 |
| `requiere_aprobacion` | boolean | true |
| `updated_at` | datetime tz | onupdate |
| `actualizado_por_id` | FK `usuarios.id` nullable | |

> Diseño y nombres definitivos los fija `sdd-design`. Esto es el contrato funcional.

---

## 5. Affected Areas

| Area | Impacto | Descripción |
|---|---|---|
| `backend/app/models/rrhh_horas_extras.py` | New | Modelos `RRHHHorasExtras` y `RRHHHorasExtrasConfig` |
| `backend/app/models/__init__.py` | Modified | Importar nuevos modelos |
| `backend/app/services/rrhh_horas_extras_service.py` | New | Lógica de detección, aprobación, liquidación, recálculo |
| `backend/app/routers/rrhh_horas_extras.py` | New | CRUD + workflow + export Excel |
| `backend/app/main.py` | Modified | Registrar router |
| `backend/app/models/permiso.py` | Modified | 4 permisos nuevos en categoría RRHH |
| `backend/app/services/rrhh_reportes_service.py` | Modified (opcional) | Helper para que `RRHHSueldos` lea HE liquidadas del período |
| `backend/alembic/versions/YYYYMMDD_rrhh_horas_extras.py` | New | Crea ambas tablas + seed config singleton |
| `backend/app/scripts/detectar_horas_extras_diario.py` | New | Script invocable por cron |
| `backend/app/scripts/sync_all_incremental.sh` | Modified | Agregar invocación al script (orden a definir en design) |
| `frontend/src/pages/RRHHHorasExtras.jsx` | New | Página con 3 tabs |
| `frontend/src/pages/RRHHHorasExtras.module.css` | New | CSS Modules |
| `frontend/src/pages/RRHHSueldos.jsx` | Modified | Consumir endpoint de HE liquidadas |
| `frontend/src/App.jsx` | Modified | Ruta nueva |
| `frontend/src/components/Sidebar.jsx` | Modified | Entry "Horas Extras" en sección RRHH |
| `frontend/src/services/api.js` | Modified | Funciones cliente del nuevo router |

---

## 6. Permisos nuevos (categoría RRHH)

| Código | Crítico | Default ADMIN | Default GERENTE | Descripción |
|---|---|---|---|---|
| `rrhh.ver_horas_extras` | no | sí | sí | Ver bloques de HE en cualquier estado |
| `rrhh.gestionar_horas_extras` | no | sí | no | Disparar detección manual, editar `porcentaje_recargo`, agregar bloque manual |
| `rrhh.aprobar_horas_extras` | **sí** | sí | no | Aprobar/rechazar bloques |
| `rrhh.liquidar_horas_extras` | **sí** | sí | no | Marcar período como liquidado (irreversible sin permiso aún mayor) |

`SUPERADMIN` recibe todos por wildcard `*`. `GERENTE` solo lectura.

---

## 7. Risks

| Riesgo | Probabilidad | Mitigación |
|---|---|---|
| El cron colisiona con `sync_hikvision_fichadas.py` y procesa fichadas incompletas | Media | El job de HE corre **después** del último sync de Hikvision del día (orden definido en `sync_all_incremental.sh`). Idempotencia: si una fichada llega tarde, el rerun reescribe el bloque siempre que esté en `detectada`. |
| Recálculo retroactivo pisa decisiones humanas | Media | Solo se recalculan bloques en `detectada` o `pendiente_asignacion_turno`. Estados `aprobada`/`rechazada`/`liquidada` quedan congelados; cambio requiere acción manual explícita. |
| Falsos positivos por fichadas desbalanceadas (empleado olvida fichar salida) | Alta | `extras_minutos=NULL` + warning en UI. NO se aprueba automáticamente. El usuario corrige fichadas en `RRHHHorarios` y re-detecta. |
| Tolerancia mal configurada genera ruido o pierde HE legítimas | Media | `tolerancia_extras_minutos` editable en config y aislada de `rrhh_horarios_config.tolerancia_minutos` (que es para tardanzas). Default 15 min, documentado en docstring del modelo y en pantalla de config. |
| Volumen de registros (1 fila × empleado × día × tipo) crece rápido | Baja | Índices compuestos sobre `(empleado_id, fecha)` y `(estado, fecha)`. Liquidados se mantienen para auditoría — eventualmente archivables a tabla histórica (fuera de scope). |
| Conflicto de % default cambia los bloques históricos | Baja | Cambiar config NO toca bloques `aprobada`/`liquidada`. Solo afecta nuevas detecciones. Documentado en UI de config. |
| Empleado sin turno acumula registros `pendiente_asignacion_turno` indefinidamente | Media | Dashboard de control muestra contador y botón de recalcular al asignar turno. UI bloquea liquidación si hay pendientes en el período. |
| Permisos críticos otorgados por error | Baja | `aprobar` y `liquidar` marcados `es_critico=True` en `PERMISOS_SISTEMA` → confirmación adicional al asignar (patrón existente). |

---

## 8. Rollback Plan

1. **Frontend**: revertir entries en `App.jsx`, `Sidebar.jsx`, `RRHHSueldos.jsx`. Borrar `RRHHHorasExtras.jsx` y CSS module. Build de frontend.
2. **Backend**: deshabilitar router en `main.py` (comentar `include_router`) — esto deja la API muerta pero no rompe nada existente.
3. **Cron**: remover invocación en `sync_all_incremental.sh`.
4. **DB**: `alembic downgrade -1` ejecuta el downgrade de la migración `YYYYMMDD_rrhh_horas_extras.py` que dropea `rrhh_horas_extras` y `rrhh_horas_extras_config`. **Pérdida de datos: total** de aprobaciones/liquidaciones registradas; aceptable porque pre-rollout no hay datos productivos en estas tablas. Si rollback es post-uso productivo, exportar a Excel antes de downgrade.
5. **Permisos**: la migración debe incluir downgrade que elimine los 4 permisos nuevos de `permisos` (y `rol_permiso`/`usuario_permiso` por cascade) — patrón ya usado en `20260312_rrhh_permisos.py`.
6. **Branch**: `git revert <merge-commit>` en `develop` antes de promover a `main`. Si ya en `main`, hotfix de revert.

---

## 9. Dependencies

- **Existentes en repo** (ya implementados):
  - `rrhh_fichadas` (`backend/app/models/rrhh_fichada.py`)
  - `rrhh_horarios_config` + `rrhh_horarios_excepciones` (`backend/app/models/rrhh_horario.py`)
  - `rrhh_empleado_horarios` (`backend/app/models/rrhh_empleado_horario.py`) — incluye método `horas_trabajadas` reutilizable como referencia.
  - `rrhh_reportes_service.horas_trabajadas` (`backend/app/services/rrhh_reportes_service.py`) — lógica de pares fichada referencia.
  - `PermisosService` y `verificar_permisos_compras.py` como patrón.
  - Sistema de cron `sync_all_incremental.sh`.
- **Externas**: ninguna nueva. `openpyxl` ya está en `requirements.txt` (lo usa `RRHHReportes`).

---

## 10. Success Criteria

- [ ] Tablas `rrhh_horas_extras` y `rrhh_horas_extras_config` existen, con singleton seedeado y los 4 permisos persistidos.
- [ ] El cron diario procesa fichadas del día anterior y crea bloques con `estado='detectada'` (o `pendiente_asignacion_turno` para empleados sin turno) sin duplicar registros existentes.
- [ ] Los 3 casos del usuario (turno mañana+tarde) producen 0 / 2h / 1h respectivamente sobre fichadas reales.
- [ ] Sábado con tramo cruzando 13:00 genera dos bloques (`habil_50` + `sabado_100`).
- [ ] Empleado sin turno trabajando sábado: `turno_esperado=0`, todas las horas como HE, `tipo_dia='sabado_100'` o `habil_50` según hora.
- [ ] Bloques bajo `tolerancia_extras_minutos` no se persisten.
- [ ] Aprobación/rechazo/liquidación auditados (usuario, timestamp, motivo) y respetan permisos críticos.
- [ ] Acciones masivas en UI procesan selecciones N>1 sin errores y reflejan permisos.
- [ ] `RRHHSueldos.jsx` lista las HE liquidadas del período en curso vía endpoint nuevo.
- [ ] Export Excel del período reproduce columnas: legajo, nombre, fecha, tipo_dia, minutos, %, observaciones, estado.
- [ ] `alembic downgrade -1` restaura el esquema sin afectar tablas RRHH existentes.
- [ ] No se introducen `bare except`, todos los endpoints declaran `response_model`, hay type hints completos, y todos los checks de permiso usan `PermisosService`.

---

## 11. Next Steps

1. `sdd-spec` — escribir specs delta con scenarios Given/When/Then por cada estado del workflow, anomalías y casos del usuario.
2. `sdd-design` — fijar nombres definitivos, decidir hora del cron y orquestación, sequence diagrams del recálculo retroactivo y del liquidar_periodo, schemas Pydantic v2 inline.
3. `sdd-tasks` — break-down en tareas completables por sesión, agrupadas por fase (modelo+migración → service → router → cron → frontend → integración sueldos).
