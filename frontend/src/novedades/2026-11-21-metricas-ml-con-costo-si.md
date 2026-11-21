# Métricas de ventas ML con costo SI

Área: Reportes

## Resumen ejecutivo

El costo de cada venta de Mercado Libre en el **Dashboard de Métricas ML**, **Rentabilidad**, el listado de **operaciones de Ventas ML** y su exportación a Excel ahora es el **costo SI** (promedio ponderado con los sell in de las facturas de compra) vigente el día de la venta. Antes era el costo de lista. Por eso cambian el costo, la ganancia y el markup de esas ventas, y los offsets que se calculan como porcentaje del costo.

## Cómo se usa

No hay que hacer nada: los reportes toman el costo nuevo solos. Si se corrige un sell in, una factura o un loyalty, las ventas afectadas se recalculan desde la fecha del cambio.

## A tener en cuenta

- Un producto sin costo SI sigue usando su costo de lista.
- Un combo vale la suma de sus componentes por la cantidad de cada uno.
- Los productos con costo en pesos se calculan en pesos; los de costo en dólares, al dólar del día de la venta.
- El precio de las ventas no cambia.
- El dashboard de TP-Link sigue con su lista de costos propia.
