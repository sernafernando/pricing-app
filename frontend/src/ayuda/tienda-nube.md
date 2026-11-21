# Tienda Nube

Área: Reportes
Ruta: Reportes → Tienda Nube
Permiso: Pedile a un administrador acceso al tablero de Tienda Nube (ventas_tn.ver_dashboard).

## Para qué sirve

Muestra las métricas de ventas de Tienda Nube: resumen con KPIs, detalle de operaciones y rentabilidad.

## Cómo se usa

Arriba dice **Tienda Nube** con tres pestañas: **Resumen**, **Detalle de Operaciones** y **Rentabilidad**.

La barra de filtros permite elegir rango de fechas, filtrar por vendedores y recargar. En **Resumen** se ven KPIs y gráficos. En **Detalle de Operaciones** se listan las operaciones con búsqueda. En **Rentabilidad** se muestra la rentabilidad.

Si hay productos sin costo, se muestra un aviso en la pestaña Resumen.

## Filtros y columnas

Una marca sin ningún producto en stock no aparece en el filtro de marca, salvo que esté en **Admin → Marcas sin stock**. Si ya la tenías elegida, el filtro sigue funcionando y la marca se ve tildada.

Filtros: fecha, vendedores y, en Detalle de Operaciones, solo sin costo.

Columnas de operaciones: fecha y comprobante, sucursal y vendedor, cliente, código, producto, marca, categoría y subcategoría, cantidad, precio unitario, IVA, total sin IVA, método de pago, comisión de Tienda Nube (con su % debajo), costo, ganancia y markup. Los montos se ven en pesos con separador de miles.

El costo sale del costo SI del producto en el día de la venta (si no tiene, del costo de lista), pasado a pesos con el dólar de ese día, × 1,065. Si no hay costo (por ejemplo, falta el dólar del día), la columna Costo dice **Sin costo** y la ganancia y el markup se ven como **—**: no se pueden calcular. Si después cambia el costo SI de un producto (por ejemplo, se corrige un sell in o una factura de compra), las operaciones de ese producto desde esa fecha se recalculan solas (los demás productos de la misma venta no se tocan; un costo cargado a mano en las líneas de ese producto se reemplaza por el recalculado).

## Botones y acciones

- **Recargar**: actualiza datos.

## Preguntas frecuentes

**¿Por qué veo un aviso de productos sin costo?**
Hay productos vendidos en Tienda Nube que no tienen costo cargado; conviene revisarlos.
