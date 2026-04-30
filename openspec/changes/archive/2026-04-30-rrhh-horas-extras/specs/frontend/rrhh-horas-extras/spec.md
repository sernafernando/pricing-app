# Delta Spec: frontend/rrhh-horas-extras

**Change**: `rrhh-horas-extras`
**Domain**: `frontend/rrhh-horas-extras`
**Tipo**: Nueva capability (no existe spec previo) — todas las requirements van bajo `## ADDED Requirements`.

> Este delta incorpora los fixes de Revisión 1 (tabs de Anomalías y Alertas, acciones de completar fichada / descartar día / reabrir bloque).

---

## ADDED Requirements

### Requirement: Página `RRHHHorasExtras.jsx` con cinco tabs

El frontend MUST proveer una nueva página accesible en una ruta dedicada del módulo RRHH (path exacto a definir en design, alineado con `App.jsx` y `Sidebar.jsx`). La página MUST contener cinco tabs con los siguientes contenidos:

| Tab | Filtra por estado | Visible si |
|---|---|---|
| **Pendientes** | `detectada` y `pendiente_asignacion_turno` | usuario tiene `rrhh.ver_horas_extras` |
| **Aprobadas** | `aprobada` | usuario tiene `rrhh.ver_horas_extras` |
| **Liquidadas** | `liquidada` | usuario tiene `rrhh.ver_horas_extras` |
| **Anomalías** | `error_fichadas` | usuario tiene `rrhh.ver_horas_extras` |
| **Alertas** | filas de `rrhh_horas_extras_alertas` con `leida=false` | usuario tiene `rrhh.ver_horas_extras` |

La página MUST seguir el Tesla Design System (CSS Modules + design tokens). Los tabs Anomalías y Alertas MUST mostrar un badge contador con la cantidad de items pendientes.

#### Scenario: Usuario con permiso ve los cinco tabs

- GIVEN un usuario con `rrhh.ver_horas_extras`
- WHEN entra a `RRHHHorasExtras.jsx`
- THEN ve los cinco tabs (Pendientes, Aprobadas, Liquidadas, Anomalías, Alertas)
- AND los tabs Anomalías y Alertas muestran badge con su contador

#### Scenario: Usuario sin permiso ve mensaje de denegación

- GIVEN un usuario sin `rrhh.ver_horas_extras`
- WHEN intenta acceder a la ruta
- THEN ve el componente estándar de "permiso denegado" del proyecto (sin renderizar la página)

---

### Requirement: Filtros disponibles en cada tab

La página MUST exponer los filtros: `empleado` (autocomplete por nombre/legajo), `fecha` (rango con date picker), `estado` (multi-select cuando aplique), `tipo_dia` (multi-select). Los filtros MUST sincronizarse con los query params del endpoint backend correspondiente.

Los filtros MUST persistir en la URL (query string) para permitir compartir y recargar la vista con el mismo contexto.

#### Scenario: Filtrar por rango de fechas

- GIVEN el usuario está en el tab Pendientes
- WHEN selecciona `fecha_desde=2026-04-01` y `fecha_hasta=2026-04-15`
- THEN la lista se actualiza vía request al backend con esos parámetros
- AND la URL refleja `?fecha_desde=2026-04-01&fecha_hasta=2026-04-15`

#### Scenario: Filtrar por empleado mediante autocomplete

- GIVEN el usuario escribe "garcía" en el filtro de empleado
- WHEN aparecen sugerencias y selecciona una
- THEN la lista filtra por ese `empleado_id`
- AND la URL incluye `?empleado_id={id}`

---

### Requirement: Selección múltiple y acciones bulk

Cada tab que muestra bloques MUST permitir seleccionar uno o varios mediante checkbox. Cuando hay selección activa, MUST aparecer una barra de acciones bulk con las operaciones disponibles según el tab y los permisos del usuario:

| Tab | Acciones bulk |
|---|---|
| **Pendientes** | "Aprobar selección" (req `rrhh.aprobar_horas_extras`), "Rechazar selección con motivo" (req `rrhh.aprobar_horas_extras`), "Cambiar % recargo" (req `rrhh.gestionar_horas_extras`) |
| **Aprobadas** | "Liquidar selección" (req `rrhh.liquidar_horas_extras`), "Reabrir selección con motivo" (req `rrhh.aprobar_horas_extras`) |
| **Anomalías** | (sólo acciones por bloque, no bulk) |
| **Alertas** | "Marcar como leídas" (req `rrhh.gestionar_horas_extras`) |

La UI MUST mostrar feedback por-item después de la operación (filas que fallaron quedan resaltadas con su error).

#### Scenario: Aprobación masiva en tab Pendientes

- GIVEN el usuario con `rrhh.aprobar_horas_extras` selecciona 5 bloques en Pendientes
- WHEN hace click en "Aprobar selección"
- THEN el frontend invoca el endpoint bulk del backend
- AND tras la respuesta, los items que pasaron a `aprobada` desaparecen del tab Pendientes
- AND los que fallaron quedan resaltados con tooltip del error

#### Scenario: Rechazo masivo solicita motivo común

- GIVEN el usuario selecciona 3 bloques en Pendientes
- WHEN hace click en "Rechazar selección"
- THEN aparece un modal pidiendo motivo
- AND si el motivo está vacío el botón "Confirmar" queda disabled
- AND al confirmar se aplica el mismo `motivo_rechazo` a los 3 bloques

#### Scenario: Cambio masivo de % recargo

- GIVEN el usuario con `rrhh.gestionar_horas_extras` selecciona 4 bloques `detectada`
- WHEN hace click en "Cambiar % recargo" e ingresa `porcentaje=75`
- THEN los 4 bloques se actualizan con `porcentaje_recargo=75.00` y `tipo_dia='manual'`
- AND la lista se refresca

---

### Requirement: Modal de detalle del bloque con fichadas e historial

Al hacer click sobre un bloque (cualquier tab), el frontend MUST abrir un modal con: datos del bloque, fichadas asociadas (`fichada_entrada_id`, `fichada_salida_id` y todas las del día relacionadas), historial completo desde `rrhh_horas_extras_historial` (timeline visual), y datos de auditoría (`aprobado_por`, `liquidado_por`, `reabierto_por` cuando apliquen).

El modal MUST mostrar las acciones disponibles según permisos y estado (aprobar, rechazar, reabrir, liquidar, completar fichada, descartar día, marcar alerta como leída, recalcular manual).

#### Scenario: Click en bloque abre modal con datos completos

- GIVEN un bloque listado en cualquier tab
- WHEN el usuario hace click sobre la fila
- THEN se abre modal con: detalle del bloque, lista de fichadas asociadas, timeline del historial
- AND las acciones visibles dependen de los permisos del usuario y del estado actual del bloque

#### Scenario: Modal de bloque liquidado solo permite ver

- GIVEN un bloque en `estado='liquidada'`
- WHEN el usuario con `rrhh.aprobar_horas_extras` (sin permiso especial) abre el modal
- THEN ve los datos pero NO ve botón "Reabrir"
- AND NO ve botón "Liquidar"

---

### Requirement: Tab Anomalías con CTAs específicos

El tab Anomalías MUST mostrar bloques en `estado='error_fichadas'` con presentación visualmente prioritaria (color de alerta, icono). Cada item MUST mostrar `error_tipo` y `observaciones`. Los CTAs por item MUST ser:

- **"Completar fichada"** (req `rrhh.gestionar_horas_extras`): abre modal pidiendo hora de la fichada faltante (entrada o salida según `error_tipo`) y motivo. Al confirmar, llama al backend que crea la `RRHHFichada(origen='manual')` y reprocesa el bloque.
- **"Descartar día"** (req `rrhh.gestionar_horas_extras`): pide motivo obligatorio. Al confirmar, llama al backend que pasa el bloque a `rechazada`.

#### Scenario: Completar fichada faltante

- GIVEN un bloque en `error_fichadas` con `error_tipo='salida_faltante'`
- AND el usuario con `rrhh.gestionar_horas_extras`
- WHEN hace click en "Completar fichada", ingresa `hora=18:30` y `motivo='se olvidó de fichar'`
- THEN tras la respuesta exitosa el bloque desaparece del tab Anomalías (pasa a Pendientes con `estado='detectada'`)

#### Scenario: Descartar día con motivo

- GIVEN un bloque en `error_fichadas`
- WHEN el usuario hace click en "Descartar día" e ingresa motivo
- THEN el bloque pasa a `rechazada` y desaparece del tab Anomalías

#### Scenario: Descartar día sin motivo bloquea confirm

- GIVEN el modal de "Descartar día" abierto
- WHEN el motivo está vacío
- THEN el botón "Confirmar" está disabled

---

### Requirement: Tab Alertas con CTAs de lectura y reapertura

El tab Alertas MUST listar filas de `rrhh_horas_extras_alertas` con `leida=false`. Cada alerta MUST mostrar: empleado, fecha del bloque vinculado, fichada modificada, mensaje y fecha de la alerta. Los CTAs por alerta MUST ser:

- **"Marcar como leída"** (req `rrhh.gestionar_horas_extras`): cambia `leida=true`. La alerta desaparece del listado por defecto.
- **"Reabrir bloque"** (req `rrhh.aprobar_horas_extras`): abre modal pidiendo motivo. Al confirmar, reabre el bloque vinculado vía endpoint backend (pasa de `aprobada` a `detectada`). La alerta queda marcada como leída como efecto secundario.

El tab Alertas MUST permitir filtrar para mostrar también alertas ya leídas (toggle "Ver leídas").

#### Scenario: Marcar alerta como leída

- GIVEN una alerta visible en el tab Alertas
- WHEN el usuario con `rrhh.gestionar_horas_extras` hace click en "Marcar como leída"
- THEN la alerta desaparece del listado por defecto
- AND el badge contador del tab decrementa

#### Scenario: Reabrir bloque desde alerta

- GIVEN una alerta sobre un bloque `aprobada`
- AND un usuario con `rrhh.aprobar_horas_extras`
- WHEN hace click en "Reabrir bloque" e ingresa motivo
- THEN el bloque pasa a `detectada` (visible en Pendientes)
- AND la alerta queda marcada como leída

#### Scenario: Toggle "Ver leídas" muestra alertas históricas

- GIVEN existen alertas leídas previamente
- WHEN el usuario activa el toggle "Ver leídas"
- THEN el listado incluye también alertas con `leida=true`

---

### Requirement: Edición inline del `porcentaje_recargo` antes de aprobar

En el tab Pendientes, cada bloque `detectada` MUST permitir editar inline el campo `porcentaje_recargo` antes de aprobar (req `rrhh.gestionar_horas_extras`). Al guardar, el frontend MUST invocar el endpoint backend que actualiza el bloque y setea `tipo_dia='manual'`.

#### Scenario: Editar % inline persiste cambio

- GIVEN un bloque `detectada` con `porcentaje_recargo=50.00` y `tipo_dia='habil_50'`
- AND el usuario tiene `rrhh.gestionar_horas_extras`
- WHEN edita el campo a `75.00` y confirma
- THEN el backend recibe el update
- AND tras refresh el bloque muestra `porcentaje_recargo=75.00` y `tipo_dia='manual'`

---

### Requirement: Botón "Re-detectar día" / "Recalcular rango"

La página MUST exponer un botón para disparar manualmente la detección sobre una fecha o rango (req `rrhh.gestionar_horas_extras`). El frontend MUST invocar el endpoint `POST /rrhh/horas-extras/recalcular?fecha_desde=&fecha_hasta=`.

El botón MUST mostrar feedback de loading durante la operación y un toast con el resumen al finalizar (cantidad de bloques procesados, errores, etc.).

#### Scenario: Recalcular rango de fechas

- GIVEN el usuario con `rrhh.gestionar_horas_extras`
- WHEN hace click en "Recalcular" e ingresa `fecha_desde=2026-04-10`, `fecha_hasta=2026-04-15`
- THEN el frontend invoca el endpoint
- AND muestra loading hasta recibir respuesta
- AND al finalizar muestra toast con resumen

---

### Requirement: Botón "Exportar Excel" del período

El tab Liquidadas (y posiblemente otros tabs) MUST exponer un botón "Exportar Excel" que descargue el XLSX del período activo en el filtro. El frontend MUST invocar el endpoint export del backend y disparar la descarga del archivo en el browser.

#### Scenario: Export descarga XLSX

- GIVEN el usuario está en tab Liquidadas con filtro `periodo=202604`
- AND tiene `rrhh.ver_horas_extras`
- WHEN hace click en "Exportar Excel"
- THEN el browser descarga un archivo `.xlsx` con el nombre conteniendo el período (ej. `horas_extras_202604.xlsx`)

---

### Requirement: Integración con `RRHHSueldos.jsx`

El frontend MUST modificar `RRHHSueldos.jsx` para consumir el endpoint backend de HE liquidadas del período. Las HE MUST mostrarse en la liquidación de cada empleado del período activo, en una sección o columna dedicada.

#### Scenario: Sueldos muestra HE liquidadas del período

- GIVEN existen bloques `liquidada` con `liquidacion_periodo='202604'`
- AND el usuario abre `RRHHSueldos.jsx` con período `202604`
- THEN para cada empleado afectado se muestran los minutos de HE acumulados por `tipo_dia`/`porcentaje_recargo`

---

### Requirement: Visibilidad condicional de acciones según permisos

Todos los botones y CTAs de la página MUST ocultarse o deshabilitarse cuando el usuario no tenga el permiso requerido. El frontend MUST consultar el permiso vía el patrón existente del proyecto (store de permisos / hook).

#### Scenario: Usuario sin aprobar no ve botón "Aprobar"

- GIVEN un usuario con solo `rrhh.ver_horas_extras`
- WHEN entra al tab Pendientes
- THEN puede ver la lista pero NO ve el botón "Aprobar selección"
- AND NO ve el botón "Rechazar selección"

#### Scenario: Usuario sin liquidar no ve botón "Liquidar"

- GIVEN un usuario con `rrhh.ver_horas_extras` y `rrhh.aprobar_horas_extras` pero NO `rrhh.liquidar_horas_extras`
- WHEN entra al tab Aprobadas
- THEN ve la lista y los botones de "Reabrir"
- AND NO ve el botón "Liquidar selección"

---

### Requirement: Estado vacío y feedback de errores

Cada tab MUST manejar el estado vacío con un mensaje informativo (ej. "No hay bloques pendientes en este período"). Los errores de red o de backend MUST mostrarse con toast o banner, sin romper la UI.

#### Scenario: Tab vacío muestra mensaje informativo

- GIVEN no existen bloques que matcheen el filtro activo
- WHEN se carga la lista
- THEN se muestra un mensaje del tipo "No hay registros" en lugar de tabla vacía

#### Scenario: Error de red muestra toast

- GIVEN el endpoint backend retorna `500`
- WHEN el frontend recibe el error
- THEN se muestra un toast con el mensaje de error
- AND la UI conserva el último estado válido (no se rompe)
