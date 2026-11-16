# Ventas por Fuera

Área: Reportes
Ruta: Reportes → Ventas por Fuera
Permiso: Pedile a un administrador acceso al tablero de ventas por fuera (ventas_fuera.ver_dashboard; ver ganancia pide ventas_fuera.ver_ganancia).

## Para qué sirve

Muestra las ventas realizadas por fuera de Mercado Libre (ventas manuales), con resumen, detalle de operaciones, rentabilidad y administración. Incluye KPIs, rankings y ganancia (si tenés permiso).

## Cómo se usa

Arriba dice **Ventas por Fuera** con cuatro pestañas: **Resumen**, **Detalle de Operaciones**, **Rentabilidad** y **Admin**.

La barra de filtros permite elegir rango de fechas (filtros rápidos), sucursales, vendedores y recargar.

En **Resumen** se ven KPIs, rankings y gráficos. En **Detalle de Operaciones** se listan las operaciones con paginación. En **Rentabilidad** se muestra la rentabilidad. En **Admin** se gestionan las ventas por fuera (la pestaña solo aparece para administradores).

La ganancia se muestra como *** si no tenés permiso.

## Filtros y columnas

Una marca sin ningún producto en stock no aparece en el filtro de marca, salvo que esté en **Admin → Marcas sin stock**. Si ya la tenías elegida, el filtro sigue funcionando y la marca se ve tildada.

Filtros: fecha, sucursales, vendedores.

Columnas de operaciones: fecha, código, producto, vendedor, cantidad, precios, costos, markup.

## Botones y acciones

- Recargar: actualiza datos.

## Preguntas frecuentes

¿Qué es una venta por fuera?
Una venta realizada fuera de Mercado Libre, cargada manualmente.

¿Por qué veo \*\*\* en la ganancia?**
No tenés el permiso para ver ganancias.

¿Por qué **Costo c/ sell in** y **Markup c/ sell in/out** muestran **-** en **Detalle de Operaciones**?
Desde que las ventas por fuera se cargan con los reportes PDF de GBP, el sell in, el sell out y los offsets de ganancia se calculan sobre esas operaciones cargadas y ya no sobre las ventas sincronizadas que lista esta pestaña. Por eso esas dos columnas quedan en **-**.

¿Cómo cuenta una nota de crédito en los offsets de ganancia?
Resta: descuenta sus unidades y su monto del offset del grupo, también cuando el offset es un monto fijo.
