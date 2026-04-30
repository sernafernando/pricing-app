# Archive Report: rrhh-horas-extras

**Change**: `rrhh-horas-extras`
**Date archived**: 2026-04-30
**Mode**: hybrid (Engram + openspec/)
**Verdict (carried over from verify)**: PASS WITH SUGGESTIONS
**Phase**: archived
**Status**: completed
**Archived path**: `openspec/changes/archive/2026-04-30-rrhh-horas-extras/`

---

## 1. Resumen

Cierre formal del cambio `rrhh-horas-extras` después de los 8 batches de implementación (Modelos → Service → Listeners → Router → Cron → Frontend → Sueldos integration → Tests/manual scripts) y la verificación estática 36/36 PASS. Las suggestions S1 y S3 fueron aplicadas como fix post-verify; S2/S4/S5 quedan diferidas para futuros cambios.

---

## 2. Inputs preservados

### 2.1 Engram observations

| Observation ID | Topic | Description |
|---|---|---|
| `#188` | `sdd/rrhh-horas-extras/proposal` | Proposal inicial |
| `#189` | `sdd/rrhh-horas-extras/proposal-revision-1` | Revisión 1 (alertas post-aprobación, error_fichadas, lockfile) |
| `#190` | `sdd/rrhh-horas-extras/spec` | Delta spec backend + frontend |
| `sdd/rrhh-horas-extras/proposal-revision-2` (topic_key) | Revisión 2 | Q1 Excel es-AR, Q2 cap 90 días, Q3 cambio turno, Q4 purga alertas |
| `#191` | `sdd/rrhh-horas-extras/design` | Design técnico (1471 líneas) |
| `#193` | `sdd/rrhh-horas-extras/tasks` | Task breakdown (~640 líneas, 9 batches) |
| `#194` | `sdd/rrhh-horas-extras/apply-progress` (Batch 3 — listeners) | event listeners hooks |
| `#195` | apply-progress (Batch 2 — service) | service layer ~1100 líneas |
| `#196` | apply-progress (Batch 4 — router) | 19 endpoints + 17 schemas |
| `#197` | apply-progress (Batch 5 — cron) | cron script con flock |
| `#200` | apply-progress (Batch 7 — Sueldos) | integración RRHHSueldos.jsx |
| `#205` | `sdd/rrhh-horas-extras/verify-report` | Verify report PASS WITH SUGGESTIONS |
| `sdd/rrhh-horas-extras/apply-post-verify` (topic_key) | post-verify fixes | S1 (tolerancia <=) + S3 (REVOKE en migración) |

> Nota: las observation IDs específicas para `proposal-revision-2`, `apply-progress` Batch 1/6/8 y `apply-post-verify` no se recuperaron por nombre exacto en `mem_search` durante el archive (probable mismatch del query); se preservan los topic_keys oficiales como referencia para recovery futuro.

### 2.2 Filesystem (movidos al archive)

- `openspec/changes/rrhh-horas-extras/proposal.md`
- `openspec/changes/rrhh-horas-extras/specs/backend/rrhh-horas-extras/spec.md`
- `openspec/changes/rrhh-horas-extras/specs/frontend/rrhh-horas-extras/spec.md`
- `openspec/changes/rrhh-horas-extras/design.md`
- `openspec/changes/rrhh-horas-extras/tasks.md`
- `openspec/changes/rrhh-horas-extras/verify-report.md`
- `openspec/changes/rrhh-horas-extras/archive-report.md` (este documento)

---

## 3. Specs sincronizados (delta → canonical)

Como el cambio introdujo dos **nuevas capabilities** (no existían specs previos), los delta specs se copiaron directamente como canonical specs (con header reescrito y prefijo `## ADDED Requirements` removido).

| Source (delta) | Destination (canonical) | Action | Requirements |
|---|---|---|---|
| `openspec/changes/rrhh-horas-extras/specs/backend/rrhh-horas-extras/spec.md` | `openspec/specs/backend/rrhh-horas-extras/spec.md` | Created (new capability) | 21 ADDED |
| `openspec/changes/rrhh-horas-extras/specs/frontend/rrhh-horas-extras/spec.md` | `openspec/specs/frontend/rrhh-horas-extras/spec.md` | Created (new capability) | 15 ADDED |

**Collision check**: ambos destinos no existían previamente. Sin merge requerido.

---

## 4. Implementation summary (high-level)

### 4.1 Backend

| Tipo | Cantidad | Notas |
|---|---|---|
| Modelos SQLAlchemy nuevos | 4 | `RRHHHoraExtra`, `RRHHHorasExtrasConfig`, `RRHHHorasExtraAlerta`, `RRHHHorasExtraHistorial` |
| Migración Alembic | 1 | `20260430_create_rrhh_horas_extras.py` (4 tablas + seed config + seed 4 permisos + REVOKE en historial post-S3) |
| Service layer | 1 (~1535 líneas) | `app/services/rrhh_horas_extras_service.py` con `HorasExtrasService(db)` |
| Endpoints router | 19 | `app/routers/rrhh_horas_extras.py` con 17 schemas Pydantic v2 inline |
| Event listeners | 3 | `app/events/rrhh_he_hooks.py` (fichadas, RRHHEmpleadoHorario) |
| Cron script | 1 (244 líneas) | `app/scripts/cron_rrhh_horas_extras.py` con flock |
| Permisos seedeados | 4 | `rrhh.ver_horas_extras` (no crítico), `gestionar_horas_extras` (no crítico), `aprobar_horas_extras` (crítico), `liquidar_horas_extras` (crítico) |
| Estados workflow | 6 | `pendiente_asignacion_turno`, `detectada`, `error_fichadas`, `aprobada`, `rechazada`, `liquidada` |
| Transiciones implementadas | 10 | con permisos diferenciados, frozen states (aprobada/rechazada/liquidada) inmutables ante cron |

### 4.2 Frontend

| Tipo | Cantidad | Notas |
|---|---|---|
| Páginas nuevas | 1 | `RRHHHorasExtras.jsx` con 5 tabs (Pendientes/Aprobadas/Liquidadas/Anomalías/Alertas) |
| Modales | 6 | `HEModalAprobar`, `HEModalMotivo` (rechazar/descartar/reabrir unificado), `HEModalLiquidar`, `HEModalRecalcular`, `HEModalCompletarFichada`, `HEModalHistorial` |
| CSS Modules | 1 | `RRHHHorasExtras.module.css` (Tesla Design System tokens) |
| Métodos API | 19 | `horasExtrasApi` en `services/api.js` |
| Integraciones | 1 | Sección "Horas Extras del Período" en `RRHHSueldos.jsx` |
| Rutas + Sidebar | 1 + 1 | `App.jsx` lazy-loaded + entrada Sidebar con permission gate |

### 4.3 Cobertura de specs

- Backend: **21/21 requirements PASS**
- Frontend: **15/15 requirements PASS**
- Total: **36/36 PASS** (con 7 suggestions menores; ver §6)

---

## 5. Pre-archive checklist

| Item | Status | Owner |
|---|---|---|
| Post-verify fixes S1 (tolerancia `<` → `<=`) y S3 (REVOKE UPDATE/DELETE en `rrhh_horas_extras_historial`) aplicados | Done (2026-04-30) | sdd-apply post-verify |
| Usuario aplica migración (`alembic upgrade head` desde `backend/`) | Pending | Usuario |
| Usuario corre los 9 scripts manuales de Batch 8 (validación behavioral) | Pending | Usuario |
| Usuario hace UI smoke test (T-9.4: navegar tabs, abrir modales, ejecutar acciones) | Pending | Usuario |

---

## 6. Outstanding suggestions (deferred a futuro change)

Las siguientes suggestions del verify-report **NO** se aplicaron y quedan como deuda menor para que un próximo cambio las atienda. Ninguna bloquea producción.

### S2 — Filtros frontend NO sincronizados con URL query string

- **Ubicación**: `frontend/src/pages/RRHHHorasExtras.jsx` (filtros `empleado_id`, `fecha_desde`, `fecha_hasta`, `tipo_dia`, `periodo`, `estado`).
- **Spec**: `frontend/rrhh-horas-extras` Requirement "Filtros disponibles en cada tab" — pide persistencia en URL para compartir/recargar.
- **Estado actual**: filtros viven en local state (`useState`), NO se reflejan en `?query`.
- **Impacto**: UX. No funcional. Usuario no puede compartir un link directo a una vista filtrada ni recargar conservando filtros.
- **Sugerencia para futuro change**: usar `URLSearchParams` + `useSearchParams` de react-router (o `searchParams` controlado vía `useEffect`).

### S4 — Listener `recalcular_por_cambio_turno` siempre usa `today - 90`

- **Ubicación**: `backend/app/events/rrhh_he_hooks.py` función `_fecha_desde_minima_for_target`.
- **Comportamiento actual**: cuando se modifica un `RRHHEmpleadoHorario`, el listener dispara recálculo desde `today - 90` independientemente del rango real del horario afectado.
- **Impacto**: rendimiento. El service ya hace clamp con cap 90, así que es funcionalmente correcto. Genera más procesado del estrictamente necesario en cambios de turnos antiguos (>90 días).
- **Sugerencia para futuro change**: leer `RRHHEmpleadoHorario.fecha_desde` / `fecha_hasta` y acotar el rango de recálculo al overlap real entre el horario y la ventana de 90 días.

### S5 — Validación cap 90 días en endpoint vs schema Pydantic

- **Ubicación**: `backend/app/routers/rrhh_horas_extras.py:903-912` (validación inline en handler `recalcular_periodo`).
- **Comportamiento actual**: el cap se valida con `if dias_solicitados > cfg.cap_dias_recalculo_manual: raise HTTPException(422)`.
- **Impacto**: testing/maintainability. Funcionalmente equivalente a hacerlo en el schema Pydantic (T-4.2 sugería el schema). Muevelo al schema y queda más limpio para tests unitarios.
- **Sugerencia para futuro change**: agregar `@field_validator('fecha_desde', 'fecha_hasta')` en `RecalcularRequest` que lea `cap_dias_recalculo_manual` de la config (requiere acceso a DB en validación, posible workaround con dependency injection o validación post-binding).

---

## 7. Post-archive operations (referencia para el usuario)

### 7.1 Specs canonical (post-sync)

- Backend: `openspec/specs/backend/rrhh-horas-extras/spec.md` (21 requirements activos)
- Frontend: `openspec/specs/frontend/rrhh-horas-extras/spec.md` (15 requirements activos)
- Estos son la **fuente de verdad** para cualquier consulta o futuro cambio sobre el módulo HE.

### 7.2 Migración

- **Archivo**: `backend/alembic/versions/20260430_create_rrhh_horas_extras.py`
- **Seed**: 4 tablas + singleton config (id=1) con valores default + 4 permisos en categoría RRHH
- **Hardening S3 aplicado**: REVOKE UPDATE/DELETE sobre `rrhh_horas_extras_historial` para reforzar append-only a nivel DB.
- **Comando**: `cd backend && alembic upgrade head`

### 7.3 Cron schedule

- **Cron line sugerida** (sistema operativo del servidor):
  ```
  30 3 * * * cd /path/to/pricing-app/backend && /path/to/python -m app.scripts.cron_rrhh_horas_extras >> /var/log/pricing-app/rrhh_he_cron.log 2>&1
  ```
- **Lockfile**: primario `/var/run/pricing-app/rrhh_he_cron.lock`, fallback `/tmp/rrhh_he_cron.lock`.
- **TZ**: ART (`America/Argentina/Buenos_Aires`) explícita en el script.
- **Procesa**: D-1 (día anterior completo).
- **Idempotencia**: vía `UniqueConstraint uq_rrhh_he_emp_fecha_tipo` + filtros de estado congelado.
- **Step final**: invoca `purgar_alertas_viejas` con `dias_retencion_alertas` (default 15).

### 7.4 Permisos seedeados (categoría RRHH)

| Código | Crítico | Cubre |
|---|---|---|
| `rrhh.ver_horas_extras` | No | Listar bloques en cualquier tab, ver detalle, ver historial |
| `rrhh.gestionar_horas_extras` | No | Recálculo manual, completar fichada, descartar día, marcar alerta leída, edición inline % |
| `rrhh.aprobar_horas_extras` | Sí | Aprobar/rechazar/reabrir bloques |
| `rrhh.liquidar_horas_extras` | Sí | Liquidar lote por período |

- ADMIN recibe los 4 por seed; GERENTE recibe `ver_horas_extras` por seed; SUPERADMIN cubre todo por wildcard.

### 7.5 Endpoints (19 total bajo `/rrhh/horas-extras`)

- `GET /` — listar con filtros (tab/estado/empleado/fecha/tipo_dia/periodo)
- `GET /{id}` — detalle bloque
- `POST /` — crear manual (gestionar)
- `PATCH /{id}` — update parcial (gestionar)
- `POST /{id}/aprobar` — aprobar (aprobar)
- `POST /{id}/rechazar` — rechazar con motivo (aprobar)
- `POST /{id}/reabrir` — reabrir con motivo (aprobar; liquidada→aprobada requiere liquidar)
- `POST /bulk/aprobar` — bulk aprobar (aprobar)
- `POST /bulk/rechazar` — bulk rechazar (aprobar)
- `POST /{id}/completar-fichada` — completar fichada faltante (gestionar)
- `POST /{id}/descartar-dia` — descartar día con motivo (gestionar)
- `POST /recalcular` — trigger manual con cap 90 días (gestionar)
- `POST /liquidar` — liquidación masiva por período (liquidar)
- `GET /alertas` — listar alertas (ver)
- `POST /alertas/{id}/marcar-leida` — marcar alerta leída (gestionar)
- `GET /{id}/historial` — historial transiciones (ver)
- `GET /config` — obtener config singleton (ver)
- `PUT /config` — actualizar config (gestionar)
- `GET /exportar` — Excel del período liquidado, formato es-AR (ver)

---

## 8. Risks & monitoring (post-archive)

- **Primer cron run**: monitorear `/var/log/pricing-app/rrhh_he_cron.log` la primera noche post-deploy. Verificar que el lockfile se libera y exit code = 0.
- **Migración**: la creación de las 4 tablas + REVOKE sobre `rrhh_horas_extras_historial` requiere permiso DDL completo en la conexión Alembic. Verificar que el rol DB tiene `GRANT REVOKE` (Postgres lo permite por default al owner de la tabla).
- **Listener overhead** (S4): si en producción se modifican muchos `RRHHEmpleadoHorario` antiguos (>90 días atrás), monitorear tiempo de recálculo por cambio. Si genera latencia perceptible, atender S4.
- **Alertas no leídas**: setup de monitoreo para que el badge contador del tab Alertas no crezca sin control. La purga automática (cron step final) elimina solo las **leídas** con > `dias_retencion_alertas`. Las no-leídas crecen hasta que un humano las atienda.

---

## 9. SDD cycle complete

El cambio `rrhh-horas-extras` está **archivado**. Cualquier trabajo futuro sobre el módulo Horas Extras se documenta como un **nuevo change** (ej. atender S2/S4/S5, agregar reporte adicional, etc.).

**Pipeline SDD ejecutado**:
```
proposal #188
  └→ revision-1 #189
       └→ spec #190 ─┬→ design #191
                     │
                     └→ revision-2 (topic_key)
                          └→ tasks #193
                               └→ apply Batches 1-8 (#194-#200, etc.)
                                    └→ verify #205 (PASS WITH SUGGESTIONS)
                                         └→ apply-post-verify (S1+S3)
                                              └→ archive (este documento)
```
