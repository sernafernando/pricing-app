# Turbo

Área: Operaciones
Ruta: Operaciones → Turbo
Permiso: Pedile a un administrador el permiso para gestionar el ruteo Turbo.

## Para qué sirve

Sirve para organizar los envíos Turbo, que son los que se entregan en 1 hora. Desde acá podés ver los envíos pendientes, asignarlos a un motoquero, administrar motoqueros, dibujar zonas de reparto, mirar el mapa y consultar estadísticas.

Si no tenés el permiso, la pantalla muestra **Sin permiso** y el mensaje **No tenés acceso a Turbo Routing**. En ese caso no vas a ver las pestañas ni los botones.

## Cómo se usa

Arriba de todo ves el título **🏍️ Turbo Routing** y dos botones:

- **⚡ Refrescar Cache**: fuerza una actualización desde el ERP y después recarga los datos. Al terminar muestra **✅ Cache invalidado**.
- **🔄 Actualizar**: vuelve a cargar la información de la pestaña que estés mirando.

Debajo están las pestañas: **📦 Envíos Pendientes**, **📋 Asignaciones**, **🏍️ Motoqueros**, **🗺️ Mapa**, **📍 Zonas**, **📊 Estadísticas** y **🚫 Banlist**. Algunas muestran un número con la cantidad de registros.

### 📦 Envíos Pendientes

Es la pestaña para ver y asignar los envíos que todavía no tienen motoquero.

1. Buscá un envío por ID, destinatario o dirección con el buscador **Buscar por ID, destinatario, dirección...**.
2. Podés filtrar por estado con el selector **Todos los estados**, **ready_to_ship** o **not_delivered**.
3. Marcá **Mostrar asignados** si también querés ver los envíos que ya tienen motoquero.
4. Tildá uno o varios envíos con la casilla de cada fila. La casilla del encabezado selecciona todos los envíos que se están mostrando.
5. Cuando hay envíos seleccionados aparece **N seleccionados** y el botón **➡️ Asignar a Motoquero**.
6. En la ventana **Asignar Envíos a Motoquero** elegí un motoquero en **Seleccionar Motoquero:** y confirmá con **Confirmar Asignación**. Si no elegís ninguno, el botón queda deshabilitado.

Si intentás asignar sin seleccionar envíos, el sistema avisa **Seleccioná al menos un envío**. Al confirmar correctamente muestra **✅ N envíos asignados correctamente**.

Los otros dos botones de la barra superior son:

- **🗺️ Geocodificar Todos**: busca las coordenadas de todos los envíos Turbo pendientes. Antes de ejecutar pide confirmación y aclara que usa la API de webhook de MercadoLibre, que es necesario para generar zonas automáticamente y que puede tardar unos segundos. Al terminar informa el total, cuántos se geocodificaron, el porcentaje de éxito y cuántos quedaron sin coordenadas.
- **🤖 Asignar Automático**: asigna los envíos a cada motoquero según la zona en la que caen. Solo toma envíos que tengan coordenadas geocodificadas. Al terminar informa cuántos procesó, cuántos asignó y cuántos quedaron sin zona.

### 📋 Asignaciones

Muestra las asignaciones del día. Arriba ves **Asignaciones del Día**, la fecha, la cantidad de envíos, cuántos están entregados y cuántos pendientes. El botón **Actualizar** recarga la lista.

Si todavía no hay asignaciones para hoy, aparece **No hay asignaciones para hoy** y la sugerencia **Ejecutá la asignación automática en el tab de Envíos**.

La tabla **Resumen por Motoquero** muestra una fila por motoquero con su total, entregados, en camino y pendientes. El estado general puede ser **Completado** (cuando entregó todo) o **En progreso**. Si un motoquero está inactivo, al lado del nombre dice **(inactivo)**.

Hacé clic en una fila para desplegar **Envíos de {nombre} ({cantidad})**. Ahí ves cada envío con su código, dirección, zona, destinatario, teléfono, estado (**Entregado**, **En camino** o **Pendiente**), horario de asignación y de entrega. El botón **Reasignar** aparece solo para los envíos que todavía no están entregados.

Al reasignar se abre la ventana **Reasignar Envío** con los datos del envío y el motoquero actual. Elegí el nuevo motoquero en **Seleccionar nuevo motoquero:** (el actual no aparece en la lista) y confirmá con **Confirmar**. Si sale bien muestra **Envío reasignado correctamente**.

### 🏍️ Motoqueros

Acá se administran los motoqueros. El buscador dice **Buscar motoquero...** y el botón **➕ Nuevo Motoquero** abre la ventana **Crear Motoquero**.

La tabla muestra **ID**, **Nombre**, **Teléfono**, **Estado**, **Fecha Creación** y **Acciones**. En acciones tenés el lápiz para editar y el tacho para desactivar, que solo aparece si el motoquero está activo. Si no hay ninguno, dice **No hay motoqueros registrados**.

En la ventana de creación o edición completá **Nombre \*** (por ejemplo, **Ej: Juan Pérez**) y **Teléfono** (por ejemplo, **Ej: +54 9 11 1234-5678**). Al editar también podés tildar **Activo**. El nombre es obligatorio: si lo dejás vacío, avisa **El nombre es obligatorio**. Al guardar muestra **✅ Motoquero creado** o **✅ Motoquero actualizado**. Para desactivar pide confirmación con **¿Desactivar este motoquero?** y después muestra **✅ Motoquero desactivado**.

### 🗺️ Mapa

Muestra los envíos sobre un mapa. La leyenda **Leyenda** indica el color de cada marcador: rojo para **Pendiente**, azul para **Asignado** y verde para **Entregado**. Al hacer clic en un envío ves su número, destinatario, dirección, estado y, si corresponde, el motoquero asignado.

Si ningún envío tiene coordenadas, aparece **⚠️ No hay envíos con coordenadas geocodificadas**. Si solo una parte tiene, aparece **ℹ️ N de M envíos sin geocoding**.

### 📍 Zonas

Sirve para crear y administrar las zonas de reparto. A la izquierda está el formulario **Crear Nueva Zona** y a la derecha el mapa.

Para dibujar una zona seguí las instrucciones **📍 Cómo dibujar una zona:**:

1. Hacé clic en **🔷 Draw Polygon**, arriba a la derecha del mapa.
2. Hacé clic en el mapa para agregar cada punto del polígono.
3. Agregá todos los puntos que necesites (mínimo 3).
4. Hacé clic en el último punto otra vez para cerrar el polígono.
5. Completá **Nombre \*** (por ejemplo, **Ej: Zona Centro**), la **Descripción** (opcional) y el **Color**.
6. Guardá con **💾 Guardar Zona**.

Cuando el polígono está dibujado aparece **✅ Polígono dibujado (N puntos)**. Si intentás guardar sin nombre avisa **El nombre es obligatorio**; si no dibujaste el polígono avisa **Dibujá un polígono en el mapa**. Al guardar bien muestra **✅ Zona creada correctamente**.

El botón **🤖 Auto-generar N Zonas** crea zonas automáticamente según la cantidad de motoqueros activos. Está deshabilitado si no hay motoqueros activos y su leyenda explica que no hay motoqueros activos. Antes de generar pide confirmación y aclara que se agrupan los envíos pendientes, que se desactivan las zonas automáticas anteriores y que se necesita al menos el 70% de los envíos geocodificados. No permite más de 6 zonas: si tenés más motoqueros activos, avisa **⚠️ Máximo 6 zonas permitidas. Tenés N motoqueros activos.**

En **Zonas Creadas (N)** ves cada zona con su color, nombre, descripción, cantidad de puntos y estado **● Activa** o **● Inactiva**. El botón de lupa (**Ver en mapa**) acerca el mapa a esa zona. El botón ✅ o ❌ activa o desactiva la zona, siempre pidiendo confirmación. Si no hay zonas, dice **📍 No hay zonas creadas aún** y **Dibujá tu primera zona en el mapa**.

### 📊 Estadísticas

Muestra tres tarjetas: **Envíos Pendientes**, **Motoqueros Activos** y **Envíos Asignados Hoy**. Debajo, la tabla **Resumen por Motoquero** lista **Motoquero**, **Envíos Asignados** y **Última Asignación**. Si no hay datos, dice **No hay asignaciones registradas**.

### 🚫 Banlist

La banlist contiene envíos que se excluyen del sistema por estados trabados o inconsistencias. Arriba dice **🚫 Banlist de Envíos Turbo** y, si hay registros, muestra el total.

Para agregar un envío completá **ID Envío ML \*** (por ejemplo, **Ej: 45335511237**), elegí un **Motivo \*** entre **Estado Buggeado**, **Duplicado**, **Inconsistencia ML**, **Error de Sincronización** u **Otro**, y podés sumar **Notas Adicionales (opcional)**. Confirmá con **🚫 Agregar a Banlist**. Si falta el ID o el motivo, avisa **Completá ID del envío y motivo**.

La tabla **Envíos Baneados** muestra **ID Envío ML**, **Motivo**, **Notas**, **Baneado Por**, **Fecha** y **Acciones**. Si no hay registros, dice **✅ No hay envíos en banlist.** y **Los envíos baneados aparecerán aquí.** El botón **✅ Desbanear** pide confirmación y avisa que el envío volverá a aparecer en el sistema.

## Filtros y columnas

| Pestaña | Búsqueda y filtros | Columnas principales |
|---|---|---|
| Envíos Pendientes | Buscador por ID, destinatario o dirección; estado; casilla **Mostrar asignados** | Shipment ID, Estado, Destinatario, Dirección, Fecha Promesa, Orden ML |
| Asignaciones | Sin filtros; botón **Actualizar** | Motoquero, Total, Entregados, En camino, Pendientes, Estado |
| Motoqueros | Buscador **Buscar motoquero...** | ID, Nombre, Teléfono, Estado, Fecha Creación, Acciones |
| Mapa | Sin filtros; leyenda de colores | Marcadores por estado y datos del envío en cada globo |
| Zonas | Sin filtros; lista de zonas y buscador visual en el mapa | Nombre, descripción, puntos, estado |
| Estadísticas | Sin filtros | Motoquero, Envíos Asignados, Última Asignación |
| Banlist | Sin filtros; formulario para agregar envíos | ID Envío ML, Motivo, Notas, Baneado Por, Fecha, Acciones |

## Botones y acciones

- **⚡ Refrescar Cache**: actualiza desde el ERP y recarga. Avisa **✅ Cache invalidado** o **Error al invalidar cache**.
- **🔄 Actualizar**: recarga los datos de la pestaña actual.
- **🗺️ Geocodificar Todos**: calcula coordenadas de los envíos pendientes. Pide confirmación y muestra un resumen al terminar.
- **🤖 Asignar Automático**: asigna por zona los envíos que ya tienen coordenadas. Pide confirmación y muestra un resumen.
- **➡️ Asignar a Motoquero**: abre la ventana para elegir el motoquero de los envíos seleccionados.
- **➕ Nuevo Motoquero**: abre la ventana de creación.
- **✏️ / 🗑️** en Motoqueros: editar o desactivar un motoquero.
- **Reasignar** en Asignaciones: cambia el motoquero de un envío que todavía no fue entregado.
- **🔍** en Zonas: lleva el mapa a la zona elegida.
- **✅ / ❌** en Zonas: activa o desactiva una zona.
- **🤖 Auto-generar N Zonas**: crea zonas automáticamente con los motoqueros activos.
- **💾 Guardar Zona**: guarda la zona dibujada.
- **🚫 Agregar a Banlist** y **✅ Desbanear**: suman o quitan envíos de la banlist.

Todas estas acciones dependen del mismo permiso de Turbo. Si no lo tenés, no ves la pantalla y no podés usar ninguna.

## Preguntas frecuentes

**¿Por qué el mapa no muestra envíos?**
Porque los envíos todavía no tienen coordenadas. Primero usá **🗺️ Geocodificar Todos** en la pestaña **📦 Envíos Pendientes**.

**¿Cuántas zonas puedo generar automáticamente?**
Hasta 6, y necesitás al menos un motoquero activo. Además, el sistema pide que al menos el 70% de los envíos estén geocodificados.

**¿Puedo reasignar un envío ya entregado?**
No. El botón **Reasignar** solo aparece para envíos que no están entregados.

**¿Qué pasa si saco un envío de la banlist?**
Vuelve a aparecer en el sistema, tal como avisa la confirmación antes de desbanearlo.

**¿Qué diferencia hay entre Actualizar y Refrescar Cache?**
**Actualizar** vuelve a cargar los datos. **Refrescar Cache** además fuerza una actualización desde el ERP antes de recargar.
