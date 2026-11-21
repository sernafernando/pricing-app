# Tienda Nube

Área: Reportes
Ruta: Reportes → Tienda Nube
Permiso: Pedile a un administrador acceso al tablero de Tienda Nube (ventas_tn.ver_dashboard).

## Para qué sirve

Muestra las métricas de ventas de Tienda Nube: resumen con KPIs, detalle de operaciones y rentabilidad.

## Cómo se usa

Arriba dice **Tienda Nube** con tres pestañas: **Resumen**, **Detalle de Operaciones** y **Rentabilidad**.

La barra de filtros permite elegir rango de fechas, filtrar por vendedores y recargar. En **Resumen** se ven KPIs y gráficos. En **Detalle de Operaciones** se listan las operaciones con búsqueda. En **Rentabilidad** se muestra la rentabilidad. Las ventas de productos sin costo conocido suman al monto, la comisión y el monto limpio, pero no al costo, la ganancia ni el markup; la tarjeta (y el total) avisa cuántas son con «N ventas sin costo». Si ninguna venta de la tarjeta tiene costo, Costo, Ganancia y Markup dicen «Sin costo» en lugar de $0.

Si hay productos sin costo, se muestra un aviso en la pestaña Resumen.

## Filtros y columnas

Una marca sin ningún producto en stock no aparece en el filtro de marca, salvo que esté en **Admin → Marcas sin stock**. Si ya la tenías elegida, el filtro sigue funcionando y la marca se ve tildada.

Filtros: fecha, vendedores y, en Detalle de Operaciones, solo sin costo.

Columnas de operaciones: fecha, producto, cantidad, precios, costos, markup.

## Botones y acciones

- **Recargar**: actualiza datos.

## Preguntas frecuentes

**¿Por qué veo un aviso de productos sin costo?**
Hay productos vendidos en Tienda Nube que no tienen costo cargado; conviene revisarlos.
