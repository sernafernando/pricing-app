# Ventas por Fuera y Tienda Nube: el costo pasa a ser el costo SI

Área: Reportes

## Resumen ejecutivo

El costo de las ventas por fuera y de Tienda Nube ahora es el **costo SI** (el costo promedio que ya descuenta los sell in de cada factura de compra y el loyalty de la marca) del día de la venta. El **Costo D** sigue sumando el 6,5 % encima, igual que antes. Los markups y la ganancia de esas ventas cambian porque cambió el costo; los precios no se tocan.

Vale para **Operaciones por Fuera**, **Ventas por Fuera (anterior)**, **Tienda Nube** y **Métricas** con el canal **Por fuera**.

## Cómo se usa

No hay que hacer nada. Cada venta toma el costo SI vigente en su fecha:

- Si el producto se compra en dólares, el costo SI está en dólares y se pasa a pesos con el dólar del día de la venta.
- Si el producto se compra en pesos, el costo SI ya está en pesos.
- Si el producto todavía no tiene costo SI, se usa el costo de lista, como hasta ahora.
- Si no se puede saber el costo (por ejemplo, un producto en dólares sin dólar cargado para ese día), la venta se muestra **Sin costo** y la ganancia y el markup quedan en **—**, en lugar de contar toda la venta como ganancia.

## A tener en cuenta

- **Combos:** si la venta trae el desglose del combo (**todos** sus componentes como líneas), el combo no suma costo y lo ponen sus componentes. Si no lo trae, o trae solo algunos componentes, el combo cuesta lo que suman sus componentes.
- Cuando se corrige un sell in, un loyalty o una factura que cambia el costo SI de un producto, las operaciones por fuera de ese producto desde esa fecha se recalculan solas. Las correcciones manuales de costo siguen mandando.
- Ventas por Fuera (anterior) y Tienda Nube se recalculan con su proceso de siempre (los últimos 30 días).
- En **Tienda Nube → Detalle de Operaciones** la tabla entra completa en pantalla con el menú abierto: algunas columnas se ven de a dos (fecha y comprobante, sucursal y vendedor, categoría y subcategoría), el % de comisión va debajo del monto y el costo y el precio unitario se ven en pesos.
