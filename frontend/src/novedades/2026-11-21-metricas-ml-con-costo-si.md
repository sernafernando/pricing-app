# Métricas de ventas ML con costo SI

Área: Reportes

## Resumen ejecutivo

El costo de cada venta de Mercado Libre en el **Dashboard de Métricas ML**, **Rentabilidad**, el listado de **operaciones de Ventas ML** y su exportación a Excel ahora es el **costo SI** (promedio ponderado con los sell in de las facturas de compra) vigente el día de la venta. Antes era el costo de lista. Por eso cambian el costo, la ganancia y el markup de esas ventas, y los offsets que se calculan como porcentaje del costo.

## Cómo se usa

No hay que hacer nada: los reportes toman el costo nuevo solos. Si se corrige un sell in, una factura o un loyalty, las ventas afectadas se recalculan desde la fecha del cambio.

## A tener en cuenta

- Un producto sin costo SI sigue usando su costo de lista.
- Si no se conoce el costo de una venta (no tiene costo SI ni de lista, o el costo es en dólares y no hay cotización de ese día), la venta queda sin costo, ganancia ni markup en vez de figurar con costo 0, y no suma offsets por porcentaje del costo. En el Detalle de Operaciones esas celdas muestran "—" (sin costo) y en la exportación a Excel quedan vacías.
- Un combo vale la suma de sus componentes por la cantidad de cada uno.
- Los productos con costo en pesos se calculan en pesos; los de costo en dólares, al dólar del día de la venta.
- El precio de las ventas no cambia.
- El dashboard de TP-Link sigue con su lista de costos propia.
- Al recalcular el consumo de un offset por porcentaje del costo, las ventas sin costo conocido ya no cuentan como consumo de 0: se saltean y quedan registradas en el log.
- En tema claro, el panel de filtros (marcas, categorías, tiendas y PMs) usa los colores del tema y sus textos se leen bien.
- Con todos los resultados cargados, la barra de Scroll Infinito ya no queda diciendo "Cargando...".
