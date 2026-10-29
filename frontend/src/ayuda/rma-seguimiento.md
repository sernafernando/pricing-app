# RMA Seguimiento

Área: Soporte
Ruta: Soporte → RMA Seguimiento
Permiso: Pedile a un administrador acceso a RMA.

## Para qué sirve

Es el tablero de los casos RMA (devoluciones y reclamos de productos). Desde acá se crean los casos, se sigue cada equipo paso a paso (recepción, revisión, reclamo en MercadoLibre, proveedor y proceso final) y se arman los envíos al proveedor y al cliente.

## Cómo se usa

La cabecera muestra el título **RMA Seguimiento** y chips con la cantidad de casos por estado (por ejemplo, **3 abiertos**).

Las pestañas son **Casos**, **Envios a Proveedor**, **Envios a Cliente** y **Métricas**. **Casos** y **Métricas** las ve cualquiera que puede entrar a la pantalla, porque entrar ya requiere acceso a RMA. Las dos de envíos solo aparecen si además tenés permiso para gestionar RMA.

### Casos

Es el listado principal. Cada fila es un caso y al tocarla se abre su ficha. Arriba tenés el buscador y el filtro por estado.

### Nuevo caso

El botón **Nuevo Caso** abre la ficha **Nuevo Caso RMA**. Ahí podés:

- Buscar el artículo por número de serie o por la venta de MercadoLibre, con el texto Ingresar serie o ID de venta ML... y el botón **Buscar**. Los resultados aparecen bajo **Resultados de traza:** con la venta (Venta ML #...), el pedido, los datos del cliente, la fecha, el envío, la factura (**Sin documento** si no tiene, y hace cuántos días es) y los reclamos de MercadoLibre asociados. Cada artículo encontrado tiene su botón **Agregar**.
- Buscar por producto con el texto Escribí un EAN, código o parte de la descripción.... Cada resultado muestra código, marca, stock (**Stock: N** o **Sin stock**) y precio; al tocarlo se agrega al caso.
- Agregar un artículo que no está en el sistema con el botón **Manual**. Se abre el formulario **Agregar artículo que no está en el sistema:** con **Descripción del producto *** (obligatoria), **Precio**, **EAN / Código** y Nro. Serie (opcional). Se agrega con **Agregar** o se descarta con **Cancelar**.

Después completás **Datos del caso**: **Cliente**, **DNI / CUIT**, **N° Cliente (ERP)**, **Teléfono de contacto**, **ML ID** y **Origen** (**MercadoLibre**, **Tienda Nube** o **Mostrador**).

La sección **Artículos (N)** lista lo que agregaste. Si está vacía, dice No hay artículos. Usá la búsqueda de traza para agregar. En cada artículo ves la serie, el precio y el estado de facturación, podés abrir la venta con **Ver en ML** y quitarlo con **Quitar**.

### Editar un caso

Al abrir un caso existente, la ficha se llama **Caso <número>** y muestra el nombre del cliente debajo del título. Tiene estas pestañas:

- **Información**: los datos del caso, los artículos, **Observaciones** y **Auditoría** (con **Corroborar NC** y **Fecha**).
- **Recepción**: por cada artículo, **Estado de recepción**, **Costo de envío** y **Causa de devolución**.
- **Revisión**: por cada artículo, **Apto para la venta**, la casilla **Requirió reacondicionamiento**, **Estado (ERP)** y **Descripción de falla**.
- **Reclamo ML**: **Estado del reclamo**, **ML cubrió el producto** y **Monto cubierto**, más las tarjetas del reclamo de MercadoLibre cuando el caso tiene venta asociada.
- **Proveedor**: por cada artículo, **Proveedor**, **Estado proveedor**, las casillas **Listo para envio** y **Enviado a proveedor**, **NC Proveedor**, **Monto NC Proveedor**, **Fecha envío** y **Fecha respuesta**.
- **Proceso**: **Estado del caso** y la casilla **Marcado para borrar pedido**; por cada artículo, **Estado proceso**, **Depósito destino**, **Enviado físicamente**, **Corroborar NC**, **Requirió RMA Interno**, **Requiere nota de crédito**, **Otros items deben facturarse**, **Listo para envio a cliente**, **Enviado a cliente** y **Observaciones**.
- **Historial**: los cambios registrados, con fecha, usuario, campo y el valor anterior y el nuevo. Si no hay nada, dice **Sin cambios registrados**.

Los campos de las pestañas se guardan a medida que los cambiás. Los botones **Guardar** y **Cancelar** del pie guardan los datos generales del caso.

### Envíos a Proveedor

Agrupa los artículos pendientes de mandar a cada proveedor. Cada grupo se puede abrir o cerrar, muestra los datos de contacto del proveedor y la tabla de artículos. Solo se pueden seleccionar los artículos marcados como **Listo para envio**; el resto aparece bloqueado con el texto **Marcar como 'Listo para envio' en el caso**.

Con los artículos seleccionados se arma el envío con **Crear Envio (N)**. Abajo se listan los **Items en proceso (N)** con su número de envío.

### Envíos a Cliente

Igual que la anterior, pero agrupado por cliente y con los artículos marcados como **Listo para envio a cliente** en el caso. También se arma el envío con **Crear Envio (N)**.

### Métricas

Muestra indicadores y gráficos de los casos. Podés elegir si filtrás por **Fecha Caso** o por **Fecha Recepción**, y definir el rango con **Desde** y **Hasta**. Los gráficos son **Estado Recepción**, **Causa Devolución**, **Apto para Venta**, **Estado Proceso**, **Estado Proveedor** y **Proveedor**. Al tocar un sector de un gráfico se abre el detalle de los equipos de esa categoría.

### Proveedores RMA

Panel que se abre desde el ícono de camión de la cabecera. Lista los proveedores con búsqueda, la casilla **Solo activos** y la tabla de datos. Cada proveedor se edita en el panel **Editar Proveedor**, con las secciones **Datos base**, **Direccion**, **Contacto** y **Config RMA**.

### Opciones de Dropdowns

Panel que se abre desde el ícono de engranaje de la cabecera. Sirve para mantener los valores que aparecen en los desplegables del módulo: **Estado del Caso**, **Estado de Recepción**, **Causa de Devolución**, **Apto para la Venta**, **Estado de Revisión**, **Estado Reclamo ML**, **Cobertura ML**, **Estado del Proceso**, **Depósito Destino** y **Estado Proveedor**. Podés crear una opción nueva, editar su valor, cambiar el orden, elegir un color y activarla o desactivarla.

## Filtros y columnas

### Casos

- Buscador con el texto Buscar por caso, cliente, ML ID, serie....
- Selector de estado con **Todos los estados** y la lista de estados cargados.

Columnas: **Caso**, **Fecha**, **Cliente** (con el número de cliente debajo, si existe), **ML ID**, **Items**, **Estado**, **Reclamo ML**, **Observaciones** (recortadas a 60 caracteres) y una columna final con el botón de PDF cuando tenés permiso para imprimir documentos.

Si no hay resultados dice **No se encontraron casos RMA** y, mientras carga, Cargando.... Cuando hay más de una página, abajo figura **Pagina X de Y (N casos)** con las flechas para moverte.

### Envíos a Proveedor

Arriba de todo: **N pendientes, N en proceso en N proveedores**. Cada grupo muestra **N items**, **N listos**, **N en proceso** y, cuando se alcanzó el mínimo configurado del proveedor, **Listo para enviar**; si todavía no llegó, **Min: N**.

Columnas de la tabla de pendientes: **Caso**, **Serie**, **Producto**, **EAN**, **Falla** y Estado Prov..

Columnas de **Items en proceso**: **Caso**, **Serie**, **Producto**, **Envio** y Estado Prov..

Si no hay nada pendiente: **No hay items pendientes de envio a proveedor**, con la aclaración **Los items aparecen aqui cuando tienen proveedor asignado y no fueron enviados**.

### Envíos a Cliente

Arriba: **N items pendientes en N clientes**. Columnas de la tabla: **Caso**, **Serie**, **Producto**, **EAN**, **Falla** y **Estado**.

Si no hay nada pendiente: **No hay items pendientes de envio a cliente**, con la aclaración **Los items aparecen aqui cuando se marcan como "Listo para envio a cliente" en el caso**.

### Proveedores RMA

- Buscador con el texto Buscar por nombre, CUIT, ciudad o representante....
- Casilla **Solo activos**.

Columnas: **Nombre**, **CUIT**, **Ciudad**, **Representante**, **Telefono**, **Uds Min**, **Activo** y **Acciones**. Si no hay resultados: **No se encontraron proveedores**. La paginación dice **Pagina X de Y (N proveedores)**.

En **Editar Proveedor** los campos son: **Nombre**, **CUIT**, **Estado**; **Direccion**, **Ciudad**, **CP**, **Provincia**; **Representante**, **Telefono**, **Email**; **Horario de recepcion**, **Unidades minimas RMA** y **Notas**.

### Métricas

Arriba ves las tarjetas **Items**, **Casos**, **Abiertos** y **Cerrados**. Mientras se actualizan los datos aparece Actualizando....

Cada gráfico muestra el total en items, los porcentajes por sector y una leyenda que también abre el detalle al tocarla. Si una dimensión no tiene datos, dice **Sin datos en el período**.

### Opciones de Dropdowns

La tabla de cada categoría tiene las columnas **Orden**, **Valor**, **Color**, **Estado** y **Acciones**. Si la categoría no tiene opciones: **No hay opciones en esta categoría**.

## Botones y acciones

### Cabecera de la pantalla

- **Nuevo Caso**: abre la ficha para crear un caso. Solo aparece si tenés permiso para gestionar RMA.
- Ícono de camión (**Gestionar proveedores RMA**): abre el panel de proveedores. Solo con permiso para gestionar RMA.
- Ícono de engranaje (**Gestionar opciones de dropdowns**): abre el panel de opciones. Solo si tenés permiso para administrar las opciones de los desplegables.

### Dentro de un caso

- **Crear Caso** guarda un caso nuevo. Necesita al menos un artículo: si no hay ninguno, avisa Agregá al menos un artículo antes de guardar el caso. Al crearlo, la ficha se cierra y aparece Creando caso RMA...; cuando termina, **Caso RMA creado correctamente** o Error al crear el caso RMA. Intentá de nuevo.
- **Guardar** guarda los cambios de un caso existente. Si falla, avisa Error al guardar el caso. Intentá de nuevo.
- **Cancelar** cierra la ficha sin guardar los cambios generales.
- **Eliminar caso** (solo en casos existentes y con permiso para eliminar): abre la confirmación **Eliminar caso RMA** con el texto **¿Eliminar el caso <número>? El caso quedará inactivo y no se mostrará en el listado.** Hay que escribir el número del caso en **Escribí <número> para confirmar:** y se puede dejar un **Motivo (opcional):**. El botón **Confirmar eliminación** queda bloqueado hasta que el número coincida; **Cancelar** cierra sin borrar. Si falla, avisa Error al eliminar el caso.
- El ícono de PDF de la fila (texto **Generar documento PDF**) abre el generador de documentos del caso. Solo aparece con permiso para imprimir documentos.

El pie con **Guardar**, **Cancelar** y **Eliminar caso** solo aparece si tenés permiso para gestionar RMA. Sin ese permiso podés mirar la ficha y cerrarla con la X.

Si al actualizar un artículo algo falla, el pie avisa Error al actualizar item #N.

### Proveedores RMA

- **Sync ERP** (texto **Sincronizar proveedores nuevos desde ERP**) trae los proveedores nuevos del sistema. Mientras trabaja dice Sincronizando... y después **Sync completado: N nuevos, N actualizados**.
- **Editar** (lápiz) abre el panel de edición. **Guardar** confirma los cambios y **Cancelar** los descarta. Si algo falla: **Error al guardar proveedor**.
- La paginación usa las flechas de página anterior y siguiente.

### Opciones de Dropdowns

- **Nueva opción** abre el formulario. Podés elegir **Categoría** (incluida la opción + Nueva categoría...), escribir **Nombre categoría** si es nueva, el **Valor**, el **Orden** y el **Color**. Se confirma con **Agregar** o se descarta con **Cancelar**.
- En cada fila, el lápiz (**Editar**) permite cambiar **Orden**, **Valor** y **Color**; se confirma con el tilde (**Guardar**) o se descarta con la cruz (**Cancelar**).
- El interruptor (**Activar** / **Desactivar**) cambia si la opción aparece disponible en los desplegables.

### Métricas

- **Fecha Caso** / **Fecha Recepción**: cambia el campo con el que se filtra.
- **Desde** y **Hasta**: definen el rango.
- Al tocar un sector o una entrada de la leyenda se abre el detalle: título **<Dimensión>: <valor>**, la cantidad de equipos en el período y la tabla **Serie**, **EAN**, **Producto**, **Caso**. Cada fila con historial se despliega y muestra la línea de tiempo de estados. Se cierra con la X o con **Cerrar**.

## Preguntas frecuentes

**¿Puedo crear un caso sin artículos?**
No. Tenés que agregar al menos uno; si no, aparece Agregá al menos un artículo antes de guardar el caso.

**¿Por qué la ficha se cerró sola al crear el caso?**
Es el comportamiento normal: el caso se guarda en segundo plano. Arriba aparece Creando caso RMA... y después el aviso de que se creó bien. Si falla, el aviso te pide reintentar.

**¿Se puede recuperar un caso eliminado?**
Eliminar deja el caso inactivo y lo saca del listado. Desde esta pantalla no hay una acción para reactivarlo.

**¿Por qué un campo está gris?**
Porque no tenés permiso para gestionar RMA. Podés consultar el caso, pero no modificarlo.

**No veo el botón Guardar ni Cancelar en el caso, ¿cómo lo cierro?**
Sin permiso para gestionar RMA el pie no aparece. Cerrá la ficha con la X.

**¿Qué significa que un artículo esté bloqueado en Envíos a Proveedor?**
Que todavía no está marcado como **Listo para envio** en el caso. Primero marcalo en la pestaña **Proveedor**.

**¿Por qué no puedo destildar Enviado a proveedor o Enviado a cliente?**
Porque el artículo ya tiene un envío generado. La casilla queda bloqueada y al pasar el mouse muestra el número de envío.

**¿Qué pasa si el rango de Métricas no trae datos?**
Los gráficos muestran **Sin datos en el período** y las tarjetas quedan en cero. Si filtrás por **Fecha Recepción**, tené en cuenta el aviso: Items sin fecha de recepción no se incluyen al filtrar por Fecha Recepción.
