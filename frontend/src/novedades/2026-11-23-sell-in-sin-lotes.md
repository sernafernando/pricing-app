# Sell in sin lotes: el costo es el costo SI

Área: Sell in / Sell out, Compras

## Resumen ejecutivo

El sell in ya no se reparte por lotes ni se descuenta venta por venta. Lo descuenta el **costo SI**, que pondera cada factura con su sell in. Por eso:

- una compra nueva ya no asigna ventas a sus lotes;
- un bono sobre el costo de la venta ya no se aplica a cada venta (así el sell in no se descuenta dos veces);
- el modo de costo de un producto ya no se puede cambiar;
- el cobro de un tactical en USD al cobro ya no pide el tipo de cambio del cobro;
- por ahora no se puede cargar un sell in por **monto total** sobre productos, marca o categoría.

Lo que ya estaba guardado (lotes, ventas consumidas, bonos) queda igual, solo para consulta.

## Cómo se usa

- Cargá y anulá compras como siempre: el costo SI del producto se recalcula solo.
- Un monto que se reparte sobre las ventas cargalo como campaña de **sell out**.
- Los lotes de un producto se ven como **Historial de lotes sell in**: ya no dicen qué descontaría la próxima venta, y un lote al que le quedaban unidades figura **Cerrado**.
- La sección **Modo de costo** muestra el modo actual y el historial, sin opción de cambiarlo. El **Modo por defecto** ya no se muestra ni se cambia.
- Un bono nuevo sobre el costo de la venta va siempre como **% del costo de la venta**; un bono que ya era por monto total se sigue editando.

## A tener en cuenta

- En un tactical, una línea de sell in nueva sobre productos, marca o categoría ofrece solo **por unidad** y **%**: un monto total nuevo no se puede cargar por ahora (si es sobre las ventas, va como sell out). Al editar, una línea que ya era por monto total lo sigue siendo mientras alcance a lo mismo. Una línea de factura por monto total sigue igual.
