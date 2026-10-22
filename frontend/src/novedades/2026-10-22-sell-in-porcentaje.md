# Sell in: cargar un porcentaje de lo facturado

Área: Productos

## Resumen ejecutivo

En **Nuevo sell in → Por compra** ahora se puede cargar el beneficio como **un porcentaje de lo facturado**, por ejemplo **2 % de la compra**, en lugar de un monto fijo.

- **Cómo se calcula:** cada producto recibe ese porcentaje de lo que se le facturó en las operaciones elegidas, con descuentos y notas de crédito ya aplicados. El total es la suma de los productos y lo calcula el sistema.
- **Se toma lo facturado al momento de cargar:** si después llega una devolución, el sell in no cambia solo.
- **Lo facturado se ve en el panel:** cada producto muestra **Facturado** con su importe, o **Sin facturado** si todavía no tiene factura. La vista previa agrega la columna **Base facturada**, con lo facturado de cada producto.
- **Necesita al menos una operación de compra**, porque lo facturado sale de ahí.
- **La moneda de la compra tiene que ser la de lo facturado.** Si no coincide, el sistema avisa y no guarda.
- **No se puede guardar si** un producto no tiene facturado o si su factura mezcla monedas. El aviso indica qué producto es.
- **Los sell in por monto fijo no cambian.**
- **En el detalle,** un sell in por porcentaje muestra **2,5 % de lo facturado** y el reparto **Según lo facturado de cada producto**.

## Cómo se usa

1. Abrir **Productos → Sell in** y hacer clic en **Nuevo sell in**.
2. Elegir la operación (o las operaciones) en **Pedido de compra (N°)**: se cargan el proveedor y los productos con lo que se les facturó.
3. En **Monto**, elegir **% de lo facturado** y escribir el **Porcentaje**.
4. Revisar la moneda (y el **Tipo de cambio** si es en USD).
5. Hacer clic en **Calcular vista previa**, revisar el monto de cada producto y su **Base facturada**, y hacer clic en **Guardar sell in**.
