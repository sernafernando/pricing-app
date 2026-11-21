# Métricas ML (anterior)

Área: Reportes
Ruta: Reportes → Métricas ML (anterior)
Permiso: Pedile a un administrador acceso al tablero de ventas ML (ventas_ml.ver_dashboard).

## Para qué sirve

Es la versión anterior del tablero de métricas de Mercado Libre. Muestra un resumen con KPIs, gráficos por marca, categoría y tipo de envío, y rankings de productos; también un detalle de operaciones y una pestaña de rentabilidad.

## Cómo se usa

Arriba dice **Métricas ML (anterior)** y tiene tres pestañas: **Resumen**, **Detalle de Operaciones** y **Rentabilidad**.

La barra de filtros permite elegir rango de fechas (filtros rápidos), marcas, categorías, tiendas oficiales y PMs. El botón de recargar actualiza los datos.

En **Resumen** se ven KPIs (Total Facturado, Ganancia Neta, Neto después de ML, Ticket Promedio, etc.), un gráfico de ventas por día, rankings de marcas y categorías, métricas por tipo de envío y rankings de top productos por unidades y por facturación (con selector Top 10/25/50).

En **Detalle de Operaciones** se listan las operaciones con paginación y exportación a Excel. Algunas columnas muestran dos datos, uno debajo del otro (por ejemplo, el ML ID debajo de la fecha), para que la tabla entre completa en pantalla con el menú lateral abierto.

El costo de cada venta es el **costo SI** vigente el día de la venta (si el producto no tiene costo SI, su costo de lista). Si no se conoce el costo de una venta (no tiene costo SI ni de lista, o el costo es en dólares y no hay cotización de ese día), Costo Unit, Costo Total y Markup% muestran **—** (sin costo) y en la exportación a Excel esas celdas quedan vacías.

En **Rentabilidad** se muestra la rentabilidad filtrada.

La ganancia se muestra como *** si no tenés permiso de ganancia.

## Filtros y columnas

El filtro de marca ofrece las marcas que vendieron en el período elegido, aunque hoy no tengan stock. En las pestañas de rentabilidad, una marca sin ningún producto en stock solo aparece si está en **Admin → Marcas sin stock** o si ya la tenías elegida.

Filtros: fecha, marcas, categorías, tiendas oficiales, PMs.

Columnas de operaciones: Fecha / ML ID, Producto / Código · Marca, Cant, Precio Unit, Total / IVA, Costo Unit, Costo Total, Comisión / % · Lista, Envío s/IVA, Limpio, Offset Flex, Markup%.

## Botones y acciones

- Recargar: actualiza datos.
- Exportar: descarga las operaciones a Excel.
- Paginación en detalle de operaciones (páginas o scroll infinito).

## Preguntas frecuentes

¿Qué diferencia tiene con Métricas ML?**
Es la versión anterior del tablero; la nueva es **Métricas ML.

¿Por qué veo \*\*\* en la ganancia?**
No tenés el permiso para ver ganancias.

¿Por qué una venta muestra — en el costo y el markup?**
No se conoce su costo: el producto no tiene costo SI ni costo de lista, o su costo es en dólares y no hay cotización de ese día. Esa venta no suma costo, ganancia ni markup.
