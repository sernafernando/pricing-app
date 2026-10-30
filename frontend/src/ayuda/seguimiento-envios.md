# Seguimiento Envíos

Área: Consultas
Ruta: Consultas → Seguimiento Envíos
Permiso: Pedile a un administrador acceso a Seguimiento Envíos.

## Para qué sirve

Sirve para mirar cómo vienen los envíos del día (o de un rango de fechas) y para revisar la colecta: qué etiquetas hay, a qué cordón pertenecen, en qué estado están en el sistema y en MercadoLibre, y qué se despachó.

Tiene dos pestañas: **Envíos** y **Check Colecta**. Si no tenés el acceso a Seguimiento Envíos, no vas a ver ninguna de las dos y la pantalla queda vacía.

## Cómo se usa

### Pestaña Envíos

Arriba ves tarjetas con los totales: **Etiquetas**, una tarjeta por cordón (**CABA**, **Cordón 1**, **Cordón 2**, **Cordón 3**), y cuando corresponde **Sin cordón**, **Flaggeadas** y **Retornados**. Cada tarjeta se puede tocar para filtrar la lista; si la volvés a tocar, el filtro se saca.

Debajo están los filtros y el botón **Actualizar**. La tabla se refresca sola cuando cambian los envíos; si la actualización en vivo no está disponible, se refresca cada minuto.

Para trabajar sobre varias etiquetas a la vez, tildá la casilla de cada fila. Si mantenés **Shift** mientras tildás, se selecciona todo el rango entre la última fila que marcaste y la que estás marcando. Con la casilla del encabezado seleccionás todas las filas visibles.

### Pestaña Check Colecta

Muestra las etiquetas de colecta del rango elegido, en dos vistas:

- **Tabla**: una fila por envío. Al tocar una fila se despliega el detalle de los productos que lleva.
- **Calendario**: los envíos agrupados por día, con la cantidad total y el detalle por estado. Podés mirar por **Semana**, **Quincena** o **Mes**, moverte con las flechas y volver con **Hoy**. Si tocás un día, volvés a la vista **Tabla** filtrada por esa fecha.

## Filtros y columnas

### Envíos

Filtros disponibles:

- Botones rápidos de fecha: **Hoy**, **Ayer**, **3d**, **7d**.
- El ícono de calendario abre el rango personalizado (**Desde**, **Hasta** y **Aplicar**); el ícono tiene el texto **Rango personalizado**.
- Buscador con el texto **Buscar (shipping ID, destinatario)...**.
- Selector **Cordón** (CABA, Cordón 1, Cordón 2, Cordón 3).
- Selector **Logística** y selector **Estado ERP**: solo aparecen cuando hay datos para elegir.
- Selector **Estado ML**: Listo para enviar, Enviado, Entregado, Cancelado, No entregado.

Columnas de la tabla:

- **Shipping ID** (si el envío viene de MercadoLibre, el número es un enlace a la venta).
- **Destinatario** (con el usuario de MercadoLibre y el comentario manual, si existen).
- **Dirección** (si el envío va a un transporte, primero muestra la dirección del transporte y debajo la del cliente).
- **CP** (abre Google Maps; si hay ubicación exacta, el texto es **Ver ubicación exacta en Google Maps**).
- **Localidad**, **Cordón**, **Estado ERP**, **Estado ML**, **Fecha Envío**, **Logística**, **Transporte**, **Pistoleado** (hora y operador) y **Caja**.

Además de los datos, en la columna del **Shipping ID** pueden aparecer estas marcas: **Outlet**, **Turbo**, **Lluvia**, el nombre del usuario que creó el pedido (con el texto "Creado por ... desde Pedidos" al pasar el mouse), el flag del envío (**Mal pasado**, **Cancelado**, **Duplicado**, **Otro**, con el motivo como texto al pasar el mouse) y **Retornado** (con el texto **Retornado por ...** si se sabe quién lo marcó).

Si no hay resultados, la tabla avisa **No hay etiquetas para la fecha seleccionada** o **No hay etiquetas flaggeadas** cuando estás filtrando por flag. Abajo de la tabla figura **Mostrando N etiquetas**.

### Check Colecta

Filtros disponibles:

- Botones rápidos de fecha: **Hoy**, **Ayer**, **3D**, **7D**, más el ícono de calendario con el rango personalizado (**Desde**, **Hasta**, **Aplicar**).
- Buscador con el texto **Shipping ID o destinatario...**.
- Selector **Estado ML** y selector **Estado ERP** (aparecen cuando hay datos).
- Botones **Tabla** y **Calendario** para cambiar de vista.

Columnas de la tabla: **Shipping ID**, **Destinatario**, **Estado ERP** y **Estado ML**. Al desplegar una fila ves los productos con su código, descripción y cantidad (**xN**); mientras carga dice **Cargando productos...**, si falla **Error cargando productos** y si no hay **Sin productos vinculados**.

Si el rango no tiene datos, aparece **No hay etiquetas de colecta para este rango de fechas**. Abajo figura **Mostrando N etiquetas**.

En la vista **Calendario**, cada día muestra el total y las etiquetas por estado del sistema y por estado de MercadoLibre. Mientras carga dice **Cargando calendario...** y si falla **Error cargando datos del calendario**.

## Botones y acciones

### Envíos

Al seleccionar al menos una etiqueta aparece una barra con la cantidad seleccionada y estos botones:

- **Flaggear**: abre el cuadro **Flaggear etiquetas**, donde elegís el **Tipo de flag** (**Mal pasado**, **Cancelado**, **Duplicado**, **Otro**) y podés escribir un **Motivo / observación (opcional)**. Se aplica con **Aplicar flag** o se descarta con **Cancelar**.
- **Quitar flag**: solo aparece si entre las seleccionadas hay alguna con flag.
- **Retornado**: marca las seleccionadas como retornadas.
- **Quitar retornado**: solo aparece si entre las seleccionadas hay alguna retornada.
- La **X** limpia la selección.

**Flaggear** y **Quitar flag** solo aparecen si tenés permiso para flaggear envíos; **Retornado** y **Quitar retornado**, si tenés permiso para marcar retornados. Sin esos permisos podés consultar la lista, pero no marcarla.

### Check Colecta

- **Actualizar**: vuelve a traer los datos con los filtros actuales.
- **Tabla** / **Calendario**: cambian la forma de ver la información.
- En el calendario: **Semana**, **Quincena**, **Mes**, las flechas de período anterior y siguiente, y **Hoy**.

Esta pestaña es solo de consulta: no tiene botones para modificar envíos.

## Preguntas frecuentes

**¿Qué pasa si marco un envío como retornado por error?**
Podés seleccionarlo de nuevo y usar **Quitar retornado**.

**¿Por qué no veo el botón Quitar flag?**
Porque solo aparece cuando alguna de las etiquetas seleccionadas ya tiene un flag.

**Si hago clic fuera del cuadro de flag, ¿se guarda algo?**
No. El cuadro se cierra y no se aplica ningún cambio; tenés que volver a abrirlo.

**¿Por qué no aparece el filtro de Logística o de Estado ERP?**
Porque esos selectores se arman con los datos de la lista: si en el rango consultado no hay logísticas o estados cargados, no se muestran.

**No veo ninguna pestaña. ¿Qué pasa?**
Te falta el acceso a Seguimiento Envíos. Pedíselo a un administrador.
