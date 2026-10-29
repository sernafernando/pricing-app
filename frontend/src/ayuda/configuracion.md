# Configuración

Área: Operaciones
Ruta: Operaciones → Configuración
Permiso: Pedile a un administrador el permiso para configurar los envíos Flex.

## Para qué sirve

Sirve para configurar todo lo que rodea a los envíos Flex: los operadores que se identifican con PIN, los costos de envío por logística y cordón, el recargo por lluvia, las logísticas disponibles y los transportes interprovinciales.

Al entrar ves el título **Config Operaciones** y cuatro pestañas: **Operadores**, **Costos Envío**, **Logísticas** y **Transportes**.

Esta pantalla no oculta botones según permisos: quien tiene acceso ve todas las acciones.

## Cómo se usa

### Operadores

La sección **Operadores** sirve para dar de alta a las personas que van a identificarse con un PIN.

- La casilla **Mostrar inactivos** incluye a los operadores dados de baja.
- El botón de actualizar (con el ícono de flechas) vuelve a cargar la lista.
- Para crear uno completá **PIN (4 dígitos)** (por ejemplo, **0000**) y **Nombre** (por ejemplo, **Nombre del operador**), y usá **Crear**.
- La tabla muestra **PIN**, **Nombre**, **Estado** y **Acciones**. El estado puede ser **Activo** o **Inactivo**.
- En acciones podés editar con el ícono de guardar o cambiar el estado con el interruptor. Al editar aparecen los botones para **Guardar** y **Cancelar**.
- Si no hay operadores, dice "No hay operadores activos" o "No hay operadores", según esté o no tildada la casilla.

Debajo está la sección **Tabs con PIN**, que sirve para elegir qué pestañas de la aplicación piden que el operador se identifique con su PIN. El texto de la pantalla explica: Configurá qué tabs de la app requieren que el operador se identifique con PIN. El timeout define cuántos minutos de inactividad antes de pedir el PIN de nuevo.

Para agregar una configuración elegí una **Página**, después un **Tab** y definí el **Timeout (min)**. El selector de tab avisa Elegí una página primero... si todavía no elegiste página, o **Todas las tabs ya están configuradas** si ya no quedan tabs disponibles. Confirmá con **Agregar**.

La tabla muestra **Página**, **Tab**, **Timeout** (por ejemplo, **15 min**), **Estado** y **Acciones**. En acciones podés activar o desactivar la configuración y eliminarla. Si no hay ninguna, dice **No hay tabs configurados**.

### Costos Envío

La sección **Costos por Logística y Cordón** permite editar los costos de cada logística para los cordones **CABA**, **Cordon 1**, **Cordon 2** y **Cordon 3**. El texto de la pantalla aclara: Editá los costos para cada logística y cordón. Cada logística tiene su propia fecha de vigencia. Al guardar se crea un nuevo registro histórico.

Cada fila tiene el nombre de la logística, su color, una fecha de vigencia (con la leyenda **Fecha de vigencia para esta logística**) y, si hay cambios, un botón **Guardar** con la leyenda **Guardar esta logística (o Enter)**. En cada cordón ves dos campos: el de prefijo **$** es el costo normal del envío y el de prefijo **T$** es el costo **turbo**, el que se usa cuando el envío sale como turbo. El turbo se puede dejar vacío. Cuando ya hay un costo cargado, abajo dice **desde** y la fecha.

Podés guardar una fila con su botón **Guardar** o presionando **Enter** en cualquiera de sus campos. Si hay cambios en varias logísticas, aparece **Guardar todo**. Al guardar bien muestra un aviso como **N cordón(es) guardado(s)** o **N logística(s) guardada(s)**. Si un valor no es válido, avisa **Costo inválido en {cordón}** o **Costo turbo inválido en {cordón}**.

Si no hay logísticas activas, dice No hay logísticas activas. Crealas primero en la pestaña Logísticas.

Más abajo está **Offset por Lluvia**, que define un recargo adicional sobre el costo turbo cuando llueve. El texto aclara: Recargo adicional sobre el costo turbo cuando hay lluvia. Solo se aplica a envíos marcados como turbo + lluvia.

Elegí el **Tipo:** **Fijo ($)** o **Porcentaje (%)**, cargá el **Valor:** y, si es mayor que cero, la pantalla muestra un ejemplo con Ej: turbo $3400 → $.... Cuando hay cambios aparece **Guardar**. Al guardar bien muestra **Offset lluvia guardado**; si el valor no es válido, avisa **Valor de lluvia inválido**.

### Logísticas

La sección **Logísticas de Envío** sirve para gestionar las logísticas que se pueden asignar a los envíos flex. El texto aclara: Gestioná las logísticas disponibles para asignar a envíos flex. Cada logística tiene un color que se muestra en las etiquetas.

Para crear una completá **Nombre** (por ejemplo, **Ej: Andreani**) y elegí un **Color**, después usá **Crear**.

La tabla muestra **Color**, **Nombre**, **Estado** y **Acciones**. El estado puede ser **Activa** o **Inactiva**. En acciones podés editar con el lápiz, activar o desactivar con el interruptor, y desactivar con el tacho (este último solo aparece si la logística está activa). Si no hay ninguna, dice **No hay logísticas creadas**.

La ventana **Editar logística** permite cambiar **Nombre** y **Color**, con **Cancelar** y **Guardar**.

### Transportes

La sección **Transportes Interprovinciales** sirve para gestionar los transportes que se pueden asignar a los envíos flex. El texto aclara: Gestioná los transportes interprovinciales disponibles para asignar a envíos flex. Incluyen dirección de terminal, teléfono y horario de recepción.

Para crear uno completá **Nombre** (por ejemplo, **Ej: Cruz del Sur**), **CUIT** (por ejemplo, **30-12345678-9**), **Dirección** (por ejemplo, **Terminal/depósito**), **CP** (por ejemplo, **1234**), **Localidad** (por ejemplo, **Ciudad/localidad**), **Teléfono** (por ejemplo, **011-4444-5555**), **Horario** (por ejemplo, **Lun-Vie 8-17**) y **Color**. Después usá **Crear**.

La tabla muestra **Color**, **Nombre**, **CUIT**, **Dirección**, **CP**, **Localidad**, **Teléfono**, **Horario**, **Estado** y **Acciones**. El estado puede ser **Activo** o **Inactivo**. En acciones podés editar con el lápiz, activar o desactivar con el interruptor, y desactivar con el tacho (este último solo aparece si el transporte está activo). Si no hay ninguno, dice **No hay transportes creados**.

La ventana **Editar transporte** permite cambiar todos esos datos, con **Cancelar** y **Guardar**.

## Filtros y columnas

| Pestaña | Filtros | Columnas o tablas |
|---|---|---|
| Operadores | Casilla **Mostrar inactivos** | PIN, Nombre, Estado, Acciones |
| Operadores (Tabs con PIN) | Sin filtros | Página, Tab, Timeout, Estado, Acciones |
| Costos Envío | Sin filtros; fecha de vigencia por logística | Logística, CABA, Cordon 1, Cordon 2, Cordon 3 |
| Costos Envío (Offset por Lluvia) | Sin filtros | Tipo y Valor del recargo |
| Logísticas | Sin filtros | Color, Nombre, Estado, Acciones |
| Transportes | Sin filtros | Color, Nombre, CUIT, Dirección, CP, Localidad, Teléfono, Horario, Estado, Acciones |

## Botones y acciones

- **Crear** en Operadores, Logísticas y Transportes: da de alta un registro nuevo.
- **Agregar** en Tabs con PIN: guarda la configuración de una pestaña.
- **Guardar** y **Cancelar** en las ediciones de operadores, logísticas y transportes.
- **Guardar** y **Guardar todo** en Costos Envío: guardan una fila o todas las logísticas con cambios.
- **Guardar** en Offset por Lluvia: guarda el recargo por lluvia.
- Interruptores de estado: activan o desactivan operadores, tabs con PIN, logísticas y transportes.
- El ícono de tacho en Tabs con PIN, Logísticas y Transportes: elimina la configuración o desactiva el registro.

## Preguntas frecuentes

**¿Cómo hago para que una pestaña pida PIN?**
En la pestaña **Operadores**, dentro de **Tabs con PIN**, elegí la página y el tab, definí el timeout y usá **Agregar**.

**¿Qué pasa cuando guardo un costo?**
Se crea un nuevo registro histórico con la fecha de vigencia de esa logística y se recarga la tabla.

**¿Tengo que guardar cada fila por separado?**
Podés guardar una fila con su botón **Guardar** o con **Enter**, o usar **Guardar todo** si cambiaste varias logísticas.

**¿Para qué sirve la fecha de vigencia?**
Cada logística tiene su propia fecha y define desde cuándo rige el costo que estás guardando.

**¿Puedo volver a activar una logística o un transporte desactivado?**
Sí. En la misma tabla, el interruptor cambia entre **Activar** y **Desactivar**.

**¿A qué envíos se les aplica el offset por lluvia?**
Solo a los envíos marcados como turbo + lluvia, según aclara la propia sección.
