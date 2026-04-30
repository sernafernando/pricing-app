# Spec: backend/rrhh-horas-extras

**Capability**: `backend/rrhh-horas-extras`
**Status**: Active (canonical source of truth)
**Origen**: Sincronizado desde `openspec/changes/archive/2026-04-30-rrhh-horas-extras/specs/backend/rrhh-horas-extras/spec.md`
**Última actualización**: 2026-04-30

> Detección automática de horas extras (HE), workflow de aprobación/rechazo/reapertura, liquidación mensual y export Excel para Sueldos. Incluye los fixes de Revisión 1 (alertas post-aprobación, fichadas desbalanceadas con `error_fichadas`, lockfile + cron 03:30, audit append-only) y Revisión 2 (Excel es-AR, cap recálculo manual, recálculo por cambio de turno, purga alertas).

---

## Requirements

### Requirement: Detección automática de horas extras por bloque empleado-día-tipo_dia

El sistema MUST calcular horas extras (HE) como el excedente positivo entre los minutos efectivamente trabajados y la suma de los minutos teóricos de los turnos asignados al empleado para esa fecha. El sistema MUST NOT generar registros con `extras_minutos` negativos.

La fórmula es:

```
HE_minutos(empleado, fecha) = max(0, trabajado_real_minutos - turno_teorico_total_minutos)
```

donde `trabajado_real_minutos` es la suma de pares `(entrada_i, salida_i)` ordenados por timestamp, y `turno_teorico_total_minutos` es la suma de los minutos teóricos de **todos** los turnos asignados al empleado para ese día (vía `rrhh_empleado_horarios` filtrando por `dias_semana`).

El sistema MUST persistir un registro en `rrhh_horas_extras` por bloque (empleado, fecha, tipo_dia). Cuando un día genera múltiples tipo_dia (ej. sábado cruzando las 13:00), el sistema MUST crear un registro por tramo.

#### Scenario: Empleado cumple el turno exacto sin extras

- GIVEN un empleado con turno mañana 08:00–13:00 y turno tarde 15:00–19:00 (teórico 9h)
- AND fichadas del día: `(08:00 entrada, 13:00 salida, 15:00 entrada, 19:00 salida)`
- WHEN el cron de detección procesa la fecha
- THEN NO se persiste ningún registro en `rrhh_horas_extras` para esa fecha
- AND `extras_minutos = 0` queda por debajo de la tolerancia y se descarta

#### Scenario: Empleado trabaja en corrido sin fichar la pausa

- GIVEN un empleado con turno mañana 08:00–13:00 y turno tarde 15:00–19:00 (teórico 9h)
- AND fichadas del día: `(08:00 entrada, 19:00 salida)`
- WHEN el cron de detección procesa la fecha
- THEN se persiste un registro en `rrhh_horas_extras` con `trabajado_minutos=660`, `turno_esperado_minutos=540`, `extras_minutos=120`
- AND `estado='detectada'`

#### Scenario: Empleado se queda más allá de la salida teórica

- GIVEN un empleado con turno mañana 08:00–13:00 y turno tarde 15:00–19:00 (teórico 9h)
- AND fichadas del día: `(08:00, 13:00, 15:00, 20:00)`
- WHEN el cron de detección procesa la fecha
- THEN se persiste un registro con `trabajado_minutos=600`, `turno_esperado_minutos=540`, `extras_minutos=60`
- AND `estado='detectada'`

#### Scenario: Empleado ficha menos que su turno teórico

- GIVEN un empleado con turno 08:00–19:00 (teórico 11h)
- AND fichadas del día: `(08:00 entrada, 17:00 salida)` (trabajado 9h)
- WHEN el cron de detección procesa la fecha
- THEN NO se persiste ningún registro en `rrhh_horas_extras` (no hay HE)
- AND el sistema MUST NOT registrar `extras_minutos` negativo

---

### Requirement: Tolerancia mínima para descartar HE menores

El sistema MUST descartar (no persistir) cualquier bloque cuyo `extras_minutos` sea menor o igual a `rrhh_horas_extras_config.tolerancia_extras_minutos`. La tolerancia MUST ser independiente de `rrhh_horarios_config.tolerancia_minutos` (que es para tardanzas, no para HE).

#### Scenario: HE bajo tolerancia no se persiste

- GIVEN `tolerancia_extras_minutos = 15`
- AND un empleado con `extras_minutos = 10` calculados para una fecha
- WHEN el cron de detección procesa la fecha
- THEN NO se crea registro en `rrhh_horas_extras`

#### Scenario: HE igual a la tolerancia no se persiste

- GIVEN `tolerancia_extras_minutos = 15`
- AND un empleado con `extras_minutos = 15` calculados para una fecha
- WHEN el cron procesa la fecha
- THEN NO se crea registro (descartado por umbral inclusivo)

#### Scenario: HE por encima de la tolerancia se persiste

- GIVEN `tolerancia_extras_minutos = 15`
- AND un empleado con `extras_minutos = 16` calculados para una fecha
- WHEN el cron procesa la fecha
- THEN se persiste un registro con `extras_minutos=16`, `estado='detectada'`

---

### Requirement: Clasificación de tipo de día con corte de sábado configurable

El sistema MUST clasificar cada bloque de HE en uno de: `habil_50`, `sabado_100`, `domingo_100`, `feriado_100` o `manual`. El corte de sábado MUST leerse de `rrhh_horas_extras_config.hora_corte_sabado` (default 13:00). Cuando el tramo de HE de un sábado **cruza** ese corte, el sistema MUST persistir DOS registros separados: uno con `tipo_dia='habil_50'` y otro con `tipo_dia='sabado_100'`, cada uno con sus `extras_minutos` proporcionales al lado del corte.

El `porcentaje_recargo` inicial MUST tomarse del singleton de config según el `tipo_dia`. Un aprobador con permiso MAY editar el `porcentaje_recargo` al aprobar; en ese caso el sistema MUST setear `tipo_dia='manual'` y mantener auditoría del valor previo en el historial.

#### Scenario: HE en sábado antes del corte

- GIVEN `hora_corte_sabado = 13:00`
- AND un empleado trabaja sábado de 08:00 a 12:00 sin tener turno asignado ese día
- WHEN el cron procesa la fecha
- THEN se crea un registro con `tipo_dia='habil_50'`, `porcentaje_recargo=50.00`

#### Scenario: HE en sábado después del corte

- GIVEN `hora_corte_sabado = 13:00`
- AND un empleado trabaja sábado de 14:00 a 18:00 sin turno asignado ese día
- WHEN el cron procesa la fecha
- THEN se crea un registro con `tipo_dia='sabado_100'`, `porcentaje_recargo=100.00`

#### Scenario: HE de sábado que cruza el corte de las 13:00

- GIVEN `hora_corte_sabado = 13:00`
- AND un empleado trabaja sábado de 11:00 a 15:00 sin turno asignado ese día
- WHEN el cron procesa la fecha
- THEN se crean DOS registros:
  - uno con `tipo_dia='habil_50'`, `extras_minutos=120` (11:00–13:00)
  - otro con `tipo_dia='sabado_100'`, `extras_minutos=120` (13:00–15:00)
- AND ambos comparten `(empleado_id, fecha)` y se distinguen por `tipo_dia` (constraint único)

#### Scenario: HE en domingo

- GIVEN un empleado trabaja domingo (sin turno asignado ese día)
- WHEN el cron procesa la fecha
- THEN se crea un registro con `tipo_dia='domingo_100'`, `porcentaje_recargo=100.00`

#### Scenario: HE en feriado declarado en `rrhh_horarios_excepciones`

- GIVEN existe un registro en `rrhh_horarios_excepciones` con la fecha objetivo, `tipo='feriado'` y `es_laborable=false`
- AND un empleado trabaja esa fecha
- WHEN el cron procesa la fecha
- THEN se crea un registro con `tipo_dia='feriado_100'`, `porcentaje_recargo=100.00`

#### Scenario: Día especial laborable se clasifica según el día de semana

- GIVEN una fecha con registro en `rrhh_horarios_excepciones` con `es_laborable=true`
- AND la fecha es martes
- AND un empleado tiene HE ese día
- WHEN el cron procesa la fecha
- THEN se crea un registro con `tipo_dia='habil_50'` (clasificación normal por día de semana, NO `feriado_100`)

---

### Requirement: Empleado sin turno asignado entra en estado `pendiente_asignacion_turno`

El sistema MUST crear el registro de HE incluso cuando el empleado no tiene ningún turno asignado en `rrhh_empleado_horarios` para esa fecha, con `estado='pendiente_asignacion_turno'`, `turno_esperado_minutos=0` y `extras_minutos=trabajado_minutos`. El sistema MUST conservar las fichadas vinculadas. Cuando se asigne un turno retroactivamente, el sistema MUST reprocesar el bloque en la próxima corrida del cron (o trigger manual), recalculando `turno_esperado_minutos` y eventualmente moviendo el bloque a `detectada` o eliminándolo si la HE cae bajo tolerancia.

#### Scenario: Empleado sin turno con fichadas válidas

- GIVEN un empleado activo SIN entradas en `rrhh_empleado_horarios`
- AND tiene fichadas del día `(08:00, 17:00)` (trabajado 9h)
- WHEN el cron procesa la fecha
- THEN se crea un registro con `estado='pendiente_asignacion_turno'`, `turno_esperado_minutos=0`, `extras_minutos=540`, `tipo_dia` clasificado por la fecha

#### Scenario: Asignación retroactiva de turno reprocesa bloques pendientes

- GIVEN un bloque existente en `estado='pendiente_asignacion_turno'`
- AND se le asigna al empleado un turno cuyo `dias_semana` cubre la fecha del bloque
- WHEN corre el siguiente cron (o se invoca trigger manual sobre el rango)
- THEN el bloque se recalcula con el nuevo `turno_esperado_minutos`
- AND si `extras_minutos > tolerancia` queda en `estado='detectada'`
- AND si `extras_minutos <= tolerancia` el registro se elimina

#### Scenario: Empleado con turnos solo lunes-viernes que ficha sábado

- GIVEN un empleado con turnos asignados solo para lunes-viernes
- AND tiene fichadas un sábado: `(09:00, 14:00)`
- WHEN el cron procesa la fecha
- THEN se crea(n) registro(s) con `turno_esperado_minutos=0`, `extras_minutos=300` total
- AND la HE se distribuye según corte sábado: `habil_50` (09:00–13:00, 240 min) + `sabado_100` (13:00–14:00, 60 min)
- AND `estado='detectada'` (no `pendiente_asignacion_turno` porque sí tiene turnos asignados, solo no para ese día)

---

### Requirement: Días con presentismo de licencia/ART/vacaciones se omiten

El sistema MUST NOT generar registros de HE para fechas en las que el empleado tenga un registro en `rrhh_presentismo` con tipo `vacaciones`, `art` o `licencia`, incluso si existen fichadas en esa fecha. Si las fichadas existen, el sistema SHOULD loggear la observación a nivel de cron sin crear bloque.

#### Scenario: Empleado en licencia con fichadas en el día se omite

- GIVEN un empleado con `rrhh_presentismo` para la fecha con tipo `licencia`
- AND tiene fichadas `(08:00, 13:00)` ese día
- WHEN el cron procesa la fecha
- THEN NO se crea registro en `rrhh_horas_extras` para esa fecha
- AND el cron loggea la omisión sin error

---

### Requirement: Fichadas desbalanceadas crean bloque con estado `error_fichadas`

Cuando las fichadas del día NO forman pares válidos `(entrada, salida)`, el sistema MUST crear un registro con `estado='error_fichadas'`, `extras_minutos=NULL` y `error_tipo` descriptivo (`salida_faltante` | `entrada_faltante` | `fichadas_inconsistentes` | `otro`). El sistema MUST NOT permitir la transición `error_fichadas → aprobada`. Solo las acciones "completar fichada" o "descartar día" pueden sacar al bloque de este estado.

#### Scenario: Empleado ficha entrada pero no salida

- GIVEN un empleado con una sola fichada del día: `(08:00 entrada)`
- WHEN el cron procesa la fecha
- THEN se crea un registro con `estado='error_fichadas'`, `error_tipo='salida_faltante'`, `extras_minutos=NULL`, `observaciones` descriptiva

#### Scenario: Empleado ficha salida sin entrada

- GIVEN un empleado con una sola fichada del día: `(17:00 salida)`
- WHEN el cron procesa la fecha
- THEN se crea un registro con `estado='error_fichadas'`, `error_tipo='entrada_faltante'`, `extras_minutos=NULL`

#### Scenario: Empleado tiene cantidad impar de fichadas

- GIVEN un empleado con tres entradas y una salida en el día
- WHEN el cron procesa la fecha
- THEN se crea un registro con `estado='error_fichadas'`, `error_tipo='fichadas_inconsistentes'`, `extras_minutos=NULL`

#### Scenario: Aprobador completa la fichada faltante

- GIVEN un bloque en `estado='error_fichadas'` con `error_tipo='salida_faltante'`
- AND un usuario con permiso `rrhh.gestionar_horas_extras`
- WHEN el usuario invoca "Completar fichada" indicando hora y motivo
- THEN se crea una `RRHHFichada(origen='manual', motivo_manual={motivo}, registrado_por_id={user})`
- AND el bloque se reprocesa y pasa a `estado='detectada'`
- AND queda entrada en `rrhh_horas_extras_historial`

#### Scenario: Aprobador descarta el día completo

- GIVEN un bloque en `estado='error_fichadas'`
- AND un usuario con permiso `rrhh.gestionar_horas_extras`
- WHEN el usuario invoca "Descartar día" con motivo obligatorio
- THEN el bloque pasa a `estado='rechazada'` con `motivo_rechazo={motivo}`
- AND queda entrada en `rrhh_horas_extras_historial`

#### Scenario: Intento de aprobar bloque en error_fichadas falla

- GIVEN un bloque en `estado='error_fichadas'`
- AND un usuario con permiso `rrhh.aprobar_horas_extras`
- WHEN intenta aprobar el bloque vía endpoint
- THEN el sistema responde HTTP `422 Unprocessable Entity` con detail descriptivo
- AND el estado del bloque NO cambia

---

### Requirement: Workflow de estados con permisos diferenciados

El sistema MUST exponer las transiciones de estado bajo estos permisos:

| Transición | Permiso requerido |
|---|---|
| `detectada → aprobada` | `rrhh.aprobar_horas_extras` |
| `detectada → rechazada` (motivo obligatorio) | `rrhh.aprobar_horas_extras` |
| `error_fichadas → detectada` (vía completar fichada) | `rrhh.gestionar_horas_extras` |
| `error_fichadas → rechazada` (vía descartar día) | `rrhh.gestionar_horas_extras` |
| `aprobada → detectada` (reapertura) | `rrhh.aprobar_horas_extras` |
| `aprobada → liquidada` (lote por período) | `rrhh.liquidar_horas_extras` |

Una operación bulk MUST procesar cada bloque individualmente; un fallo en uno NO MUST bloquear la transición de los demás. La respuesta MUST detallar éxitos y fallos por bloque.

#### Scenario: Aprobar sin permiso retorna 403

- GIVEN un bloque en `estado='detectada'`
- AND un usuario sin `rrhh.aprobar_horas_extras`
- WHEN intenta aprobar
- THEN el sistema responde HTTP `403 Forbidden`
- AND el estado del bloque NO cambia

#### Scenario: Aprobar con permiso registra auditoría

- GIVEN un bloque en `estado='detectada'`
- AND un usuario con `rrhh.aprobar_horas_extras`
- WHEN aprueba el bloque
- THEN el bloque pasa a `estado='aprobada'`
- AND se setean `aprobado_por_id={user.id}` y `aprobado_at={now}`
- AND se inserta una fila en `rrhh_horas_extras_historial`

#### Scenario: Rechazar requiere motivo obligatorio

- GIVEN un bloque en `estado='detectada'`
- AND un usuario con `rrhh.aprobar_horas_extras`
- WHEN rechaza el bloque con `motivo='X'`
- THEN el bloque pasa a `estado='rechazada'` con `motivo_rechazo='X'`
- AND se inserta historial
- AND si el motivo está vacío el sistema responde `422 Unprocessable Entity`

#### Scenario: Bulk approve continúa pese a errores individuales

- GIVEN una selección de 5 bloques: 3 en `detectada`, 1 en `error_fichadas`, 1 ya `aprobada`
- AND un usuario con `rrhh.aprobar_horas_extras`
- WHEN invoca aprobación masiva sobre los 5
- THEN los 3 en `detectada` pasan a `aprobada`
- AND el bloque en `error_fichadas` falla con detalle `422` en la respuesta por-item
- AND el bloque ya `aprobada` se reporta como no-op
- AND la respuesta lista por-item el resultado (éxito/error) sin abortar el lote

---

### Requirement: Bloques aprobados/rechazados/liquidados son inmutables ante el cron

El sistema (cron y servicio de detección) MUST NOT modificar bloques cuyo `estado` sea `aprobada`, `rechazada` o `liquidada`. Solo bloques en `detectada` o `pendiente_asignacion_turno` MAY ser reescritos por reprocesos automáticos. Los bloques `error_fichadas` solo cambian por acción humana (completar/descartar).

#### Scenario: Cron encuentra un bloque ya aprobado

- GIVEN un bloque en `estado='aprobada'` para empleado E, fecha F, tipo `habil_50`
- WHEN el cron vuelve a procesar la fecha F del empleado E
- THEN el bloque NO cambia ningún campo
- AND NO se crea bloque duplicado (`uq_rrhh_he_empleado_fecha_tipo` lo impide)

---

### Requirement: Alertas por modificación de fichadas post-aprobación

Cuando una `rrhh_fichadas` vinculada (vía `fichada_entrada_id` o `fichada_salida_id`) a un bloque en `estado` `aprobada`, `rechazada` o `liquidada` es **modificada o eliminada**, el sistema MUST insertar una fila en `rrhh_horas_extras_alertas` con `he_bloque_id`, `fichada_id`, `tipo_alerta`, `mensaje` descriptivo y `leida=false`. El sistema MUST NOT recalcular automáticamente el bloque congelado.

#### Scenario: Edición de fichada vinculada a bloque aprobado dispara alerta

- GIVEN un bloque en `estado='aprobada'` con `fichada_entrada_id=F1` y `fichada_salida_id=F2`
- AND un usuario edita la `RRHHFichada` con `id=F1` (cambia el horario)
- WHEN se ejecuta el hook/handler que detecta la edición
- THEN se inserta fila en `rrhh_horas_extras_alertas` con `he_bloque_id={bloque.id}`, `fichada_id=F1`, mensaje descriptivo
- AND el bloque NO cambia de estado ni recalcula

#### Scenario: Edición de fichada vinculada a bloque detectada SÍ recalcula

- GIVEN un bloque en `estado='detectada'` con fichadas vinculadas
- AND un usuario edita una de esas fichadas
- WHEN corre el siguiente cron (o trigger manual sobre el rango)
- THEN el bloque se recalcula con los nuevos valores
- AND NO se inserta alerta (no es estado congelado)

---

### Requirement: Reapertura manual de bloques aprobados

Un usuario con `rrhh.aprobar_horas_extras` MUST poder reabrir un bloque en `estado='aprobada'` aportando un motivo obligatorio. Al reabrir, el sistema MUST: (a) cambiar el estado a `detectada`; (b) setear `reabierto_por_id`, `reabierto_at` y `motivo_reapertura`; (c) insertar fila en `rrhh_horas_extras_historial`. En la próxima corrida del cron (o trigger manual) el bloque será recalculado con las fichadas actuales.

El sistema MUST NOT permitir reabrir bloques en `estado='liquidada'` desde este permiso (la reapertura post-liquidación queda fuera de scope; se documentará en design si requiere permiso especial).

#### Scenario: Reapertura exitosa con motivo

- GIVEN un bloque en `estado='aprobada'`
- AND un usuario con `rrhh.aprobar_horas_extras`
- WHEN invoca reapertura con `motivo='fichada modificada el lunes'`
- THEN el bloque pasa a `estado='detectada'`
- AND se setean `reabierto_por_id`, `reabierto_at`, `motivo_reapertura='fichada modificada el lunes'`
- AND se inserta entrada en `rrhh_horas_extras_historial` con snapshot JSONB del estado previo

#### Scenario: Reapertura sin motivo falla

- GIVEN un bloque en `estado='aprobada'`
- WHEN un usuario con permiso intenta reabrir sin motivo
- THEN el sistema responde `422 Unprocessable Entity`

#### Scenario: Reapertura sobre bloque liquidado se rechaza

- GIVEN un bloque en `estado='liquidada'`
- WHEN un usuario con `rrhh.aprobar_horas_extras` (sin permiso especial) intenta reabrir
- THEN el sistema responde `403 Forbidden` o `409 Conflict` (definir en design)

---

### Requirement: Historial append-only de transiciones de estado

El sistema MUST insertar una fila en `rrhh_horas_extras_historial` por cada transición de estado de un bloque, conteniendo: `he_bloque_id`, `estado_anterior`, `estado_nuevo`, `usuario_id` (si aplica), `motivo` (si aplica), `datos_snapshot` (JSONB con los valores relevantes del bloque ANTES del cambio), `created_at`. La tabla MUST ser append-only: el sistema MUST NOT permitir UPDATE ni DELETE sobre filas existentes.

#### Scenario: Aprobación inserta fila en historial

- GIVEN un bloque en `estado='detectada'`
- WHEN un usuario lo aprueba
- THEN se inserta una fila con `estado_anterior='detectada'`, `estado_nuevo='aprobada'`, `usuario_id={user.id}`, `datos_snapshot={...}`

#### Scenario: Recálculo automático del cron también inserta historial

- GIVEN un bloque en `estado='pendiente_asignacion_turno'`
- WHEN el cron lo recalcula y lo mueve a `detectada`
- THEN se inserta fila con `usuario_id=NULL`, `motivo='cron recalculation'` (o equivalente), snapshot del estado anterior

#### Scenario: Intento de UPDATE sobre historial falla

- GIVEN una fila existente en `rrhh_horas_extras_historial`
- WHEN se intenta un UPDATE o DELETE (a nivel ORM o DB)
- THEN la operación falla (vía constraint, trigger o convención de servicio — definir en design)

---

### Requirement: Cron diario determinista a las 03:30 con lockfile

El sistema MUST proveer un script (`backend/app/scripts/detectar_horas_extras_diario.py`) invocable por cron a las **03:30 AM** que procese el día anterior completo (D-1). El script MUST ser idempotente: corridas múltiples sobre el mismo día NO MUST generar duplicados ni alterar bloques en estado congelado.

El script MUST adquirir un **lockfile** (`/var/run/pricing-app/rrhh_he_cron.lock` o `/tmp/rrhh_he_cron.lock` como fallback) antes de procesar. Si el lockfile ya está bloqueado, el script MUST loggear un WARNING y abortar sin procesar.

El script MUST liberar el lockfile al finalizar, incluso si hubo error (uso de `try/finally` o context manager equivalente).

#### Scenario: Cron procesa D-1 completo determinístico

- GIVEN hoy es 2026-05-02
- AND existen fichadas de varios empleados para 2026-05-01
- WHEN corre el cron a las 03:30
- THEN se procesan las fichadas de **2026-05-01** (D-1)
- AND para cada empleado activo se generan los bloques correspondientes (o ninguno si HE bajo tolerancia)
- AND si se ejecuta el script una segunda vez sin lockfile, el resultado final en DB es idéntico

#### Scenario: Cron encuentra lockfile activo

- GIVEN el lockfile `/var/run/pricing-app/rrhh_he_cron.lock` está bloqueado por otro proceso
- WHEN se invoca el script
- THEN el script loggea WARNING y aborta con exit code distinto de 0
- AND NO modifica ninguna fila

#### Scenario: Trigger manual sobre rango ejecuta misma lógica

- GIVEN un usuario con `rrhh.gestionar_horas_extras` invoca `POST /rrhh/horas-extras/recalcular?fecha_desde=2026-04-15&fecha_hasta=2026-04-20`
- WHEN el endpoint procesa
- THEN se ejecuta la misma función de detección sobre todas las fechas del rango
- AND solo se modifican bloques en `detectada` y `pendiente_asignacion_turno`
- AND bloques en `aprobada`/`rechazada`/`liquidada`/`error_fichadas` se conservan inmutables

#### Scenario: Cron libera lockfile en error

- GIVEN el script lanza una excepción durante el procesamiento
- WHEN finaliza la ejecución (con error)
- THEN el lockfile se libera
- AND la siguiente corrida puede adquirirlo

---

### Requirement: Liquidación mensual de bloques aprobados

El sistema MUST exponer una operación `liquidar_periodo(yyyymm, lista_bloques)` que cambie a `estado='liquidada'` todos los bloques `aprobada` indicados, seteando `liquidacion_periodo='YYYYMM'`, `liquidado_por_id` y `liquidado_at`. La operación MUST requerir el permiso `rrhh.liquidar_horas_extras`. El sistema MUST insertar fila en historial por cada bloque liquidado.

Los bloques en `estado='liquidada'` MUST NOT poder ser reabiertos por el permiso `rrhh.aprobar_horas_extras` solo. La reapertura post-liquidación está fuera de scope (se evaluará en design si requiere permiso especial).

#### Scenario: Liquidar lote en período exitoso

- GIVEN una lista de bloques en `estado='aprobada'`
- AND un usuario con `rrhh.liquidar_horas_extras`
- WHEN invoca liquidar para `periodo='202604'`
- THEN cada bloque pasa a `estado='liquidada'`, `liquidacion_periodo='202604'`, `liquidado_por_id={user.id}`, `liquidado_at={now}`
- AND se insertan filas en historial

#### Scenario: Liquidar bloque no aprobado falla

- GIVEN un bloque en `estado='detectada'`
- AND un usuario con `rrhh.liquidar_horas_extras` lo incluye en un lote
- WHEN invoca liquidar
- THEN ese bloque falla con `422 Unprocessable Entity` en la respuesta por-item
- AND los demás bloques (si están en `aprobada`) se procesan normalmente

#### Scenario: Liquidar sin permiso retorna 403

- GIVEN un usuario sin `rrhh.liquidar_horas_extras`
- WHEN invoca el endpoint de liquidación
- THEN el sistema responde `403 Forbidden`

---

### Requirement: Export Excel del período liquidado

El sistema MUST exponer un endpoint (a definir ruta exacta en design) que devuelva un Excel con todos los bloques `liquidada` de un período `YYYYMM`, conteniendo al menos las columnas: `legajo`, `nombre_empleado`, `fecha`, `tipo_dia`, `extras_minutos`, `porcentaje_recargo`, `estado`, `observaciones`. La salida MUST ser consumible por `RRHHSueldos.jsx`.

#### Scenario: Export del período devuelve XLSX

- GIVEN existen bloques en `estado='liquidada'` con `liquidacion_periodo='202604'`
- AND un usuario con `rrhh.ver_horas_extras`
- WHEN invoca el export para período `202604`
- THEN la respuesta es un archivo `.xlsx` con una fila por bloque liquidado
- AND las columnas requeridas están presentes

#### Scenario: Export de período sin liquidaciones devuelve archivo vacío

- GIVEN no existen bloques liquidados para `liquidacion_periodo='202601'`
- WHEN se invoca el export
- THEN la respuesta es un archivo `.xlsx` con encabezados pero sin filas de datos (NO error)

---

### Requirement: Permisos del módulo de horas extras

El sistema MUST registrar 4 permisos en categoría `RRHH` con la siguiente semántica:

| Código | Crítico | Cubre |
|---|---|---|
| `rrhh.ver_horas_extras` | no | Listar bloques en cualquier tab (Pendientes, Aprobadas, Liquidadas, Anomalías, Alertas), ver detalle, ver historial |
| `rrhh.gestionar_horas_extras` | no | Disparar detección manual, completar fichada faltante, descartar día, marcar alerta como leída, cambiar `porcentaje_recargo` antes de aprobar |
| `rrhh.aprobar_horas_extras` | sí | Aprobar / rechazar / reabrir bloques |
| `rrhh.liquidar_horas_extras` | sí | Marcar lote como `liquidada` |

Los endpoints del módulo MUST validar el permiso correspondiente vía `PermisosService` (patrón existente en `verificar_permisos_compras.py`). `SUPERADMIN` recibe todos por wildcard.

#### Scenario: Usuario solo con ver_horas_extras lista bloques

- GIVEN un usuario con `rrhh.ver_horas_extras` y nada más
- WHEN invoca `GET /rrhh/horas-extras?estado=detectada`
- THEN recibe la lista de bloques `detectada`
- AND si intenta `POST /rrhh/horas-extras/{id}/aprobar` recibe `403`

#### Scenario: Usuario con gestionar pero sin aprobar

- GIVEN un usuario con `rrhh.gestionar_horas_extras` pero SIN `rrhh.aprobar_horas_extras`
- WHEN invoca "Completar fichada" sobre un bloque `error_fichadas`
- THEN la operación tiene éxito y el bloque pasa a `detectada`
- AND si invoca "Aprobar" sobre el mismo bloque (ya `detectada`) recibe `403`

---

### Requirement: Modelo de datos `rrhh_horas_extras` con audit fields

El sistema MUST persistir bloques en tabla `rrhh_horas_extras` con los campos definidos en el proposal (sección 4.1) **más** los campos de revisión 1:

- `error_tipo` (varchar(50), nullable) — para `estado='error_fichadas'`
- `reabierto_por_id` (FK `usuarios.id`, nullable)
- `reabierto_at` (timestamp tz, nullable)
- `motivo_reapertura` (text, nullable)

El sistema MUST mantener el constraint único `uq_rrhh_he_empleado_fecha_tipo (empleado_id, fecha, tipo_dia)` para evitar duplicados en reprocesos.

Los estados válidos en `estado` MUST ser exactamente: `pendiente_asignacion_turno`, `detectada`, `error_fichadas`, `aprobada`, `rechazada`, `liquidada`.

#### Scenario: Insert con estado inválido falla

- GIVEN una operación intenta crear un bloque con `estado='foo'`
- WHEN el ORM/DB valida
- THEN la operación falla (constraint check o validación Pydantic)

#### Scenario: Reproceso del mismo día no duplica filas

- GIVEN un bloque existente para `(empleado_id=10, fecha=2026-04-15, tipo_dia='habil_50')`
- WHEN el cron reprocesa esa fecha y el bloque está en `detectada`
- THEN la fila existente se actualiza in-place
- AND NO se crea una segunda fila (constraint único lo impediría de todos modos)

---

### Requirement: Modelo de configuración singleton `rrhh_horas_extras_config`

El sistema MUST persistir la configuración global en una tabla `rrhh_horas_extras_config` con `id=1` (constraint check para singleton), conteniendo: `porcentaje_dia_habil`, `porcentaje_sabado_pm`, `porcentaje_domingo`, `porcentaje_feriado`, `hora_corte_sabado`, `tolerancia_extras_minutos`, `requiere_aprobacion`, `actualizado_por_id`, `updated_at`. La migración Alembic MUST hacer seed con valores default (50, 100, 100, 100, 13:00, 15, true).

Modificar la config NO MUST recalcular bloques en estado `aprobada` o `liquidada`. Cambios solo afectan nuevas detecciones y reprocesos de bloques en `detectada`/`pendiente_asignacion_turno`.

#### Scenario: Migración seedea singleton

- GIVEN la migración `YYYYMMDD_rrhh_horas_extras.py` se ejecuta
- WHEN finaliza
- THEN existe una fila en `rrhh_horas_extras_config` con `id=1` y los valores default

#### Scenario: Update de config no toca bloques liquidados

- GIVEN bloques en `estado='liquidada'` con `porcentaje_recargo=100.00` para `tipo_dia='domingo_100'`
- AND el admin cambia `porcentaje_domingo` a `120.00`
- WHEN se persiste el cambio
- THEN los bloques liquidados conservan `porcentaje_recargo=100.00`
- AND nuevos bloques de `tipo_dia='domingo_100'` se crean con `porcentaje_recargo=120.00`

---

### Requirement: Tabla de alertas `rrhh_horas_extras_alertas`

El sistema MUST persistir alertas en tabla `rrhh_horas_extras_alertas` con campos: `id`, `he_bloque_id` (FK), `fichada_id` (FK nullable), `tipo_alerta` (varchar), `mensaje` (text), `leida` (boolean default false), `leida_por_id` (FK usuarios nullable), `leida_at` (timestamp tz nullable), `created_at`. Las alertas se generan automáticamente cuando una fichada vinculada a un bloque congelado es modificada/eliminada.

Un usuario con `rrhh.gestionar_horas_extras` MAY marcar alertas como leídas (set `leida=true`, `leida_por_id`, `leida_at`).

#### Scenario: Marcar alerta como leída

- GIVEN una alerta con `leida=false`
- AND un usuario con `rrhh.gestionar_horas_extras`
- WHEN invoca "Marcar como leída"
- THEN la alerta queda `leida=true`, `leida_por_id={user.id}`, `leida_at={now}`

---

### Requirement: Tabla de historial append-only `rrhh_horas_extras_historial`

El sistema MUST persistir el historial de transiciones en tabla `rrhh_horas_extras_historial` con campos: `id`, `he_bloque_id` (FK), `estado_anterior` (varchar), `estado_nuevo` (varchar), `usuario_id` (FK nullable, NULL si la transición fue automática), `motivo` (text nullable), `datos_snapshot` (JSONB con los campos relevantes del bloque antes del cambio), `created_at`.

La tabla MUST ser append-only: cualquier UPDATE o DELETE MUST ser rechazado (vía trigger DB, constraint o convención estricta del servicio — la elección queda para design).

#### Scenario: Cada transición de estado escribe historial

- GIVEN un bloque que pasa por: `pendiente_asignacion_turno → detectada → aprobada → liquidada`
- WHEN concluyen las cuatro transiciones
- THEN existen 4 filas en `rrhh_horas_extras_historial` para ese `he_bloque_id`

---

### Requirement: Endpoint de consumo para `RRHHSueldos`

El sistema MUST exponer un endpoint que devuelva las HE liquidadas de un período `YYYYMM` en formato JSON consumible por `RRHHSueldos.jsx`, conteniendo: `empleado_id`, `legajo`, `nombre`, `fecha`, `tipo_dia`, `extras_minutos`, `porcentaje_recargo`. Este endpoint MUST requerir `rrhh.ver_horas_extras`.

#### Scenario: Sueldos consume HE del período

- GIVEN existen bloques liquidados con `liquidacion_periodo='202604'`
- AND un usuario con `rrhh.ver_horas_extras`
- WHEN `RRHHSueldos.jsx` invoca `GET /rrhh/horas-extras/liquidadas?periodo=202604`
- THEN recibe array JSON con un objeto por bloque liquidado conteniendo los campos requeridos

---

### Requirement: Idempotencia y atomicidad de operaciones bulk

El sistema MUST procesar las operaciones bulk (aprobar selección, rechazar selección, liquidar lote) de forma que cada item se procese en su propia transacción lógica. Un fallo en un item NO MUST hacer rollback de los items ya procesados exitosamente. La respuesta MUST contener un detalle por item: `{id, status: 'ok' | 'error', detail?}`.

#### Scenario: Bulk con errores parciales devuelve detalle por item

- GIVEN un lote de 4 bloques: 2 válidos para la operación, 2 inválidos
- WHEN se invoca la operación bulk
- THEN los 2 válidos cambian de estado y persisten
- AND los 2 inválidos NO cambian
- AND la respuesta lista los 4 con su `status` individual
