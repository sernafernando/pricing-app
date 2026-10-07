# Ventas ML: el % de varios ahora se calcula también sobre el envío

Área: Ventas

## Resumen ejecutivo

El **% de varios** de **Ventas ML** se aplicaba solo sobre el precio de la operación sin IVA. Ahora se aplica sobre esa base **más todo el envío que entra, sin IVA**: lo que pagó el comprador y la bonificación por envío Flex que paga Mercado Libre.

Qué tenés que saber:

- **Cuenta el envío bruto.** Si el comprador pagó el envío y ML después nos lo cobra de vuelta (por ejemplo +$ 990 y -$ 990), el envío igual entra en la base: lo facturamos, y sobre lo que facturamos pagamos IIBB. El cargo de envío se sigue restando como siempre.
- **Sin IVA.** Una operación de $ 10.000 con $ 5.000 de envío paga el % sobre $ 8.264,46 + $ 4.132,23 = $ 12.396,69. El IVA del envío se muestra aparte, **solo como dato**: no se resta como gasto.
- **Se cuenta una sola vez.** El envío del comprador sale de lo que realmente entró en esa orden. Si Mercado Libre anuló el cargo de envío al comprador, no suma.
- **La bonificación Flex es la que muestra el panel de ML.** Se toma del descuento al vendedor del envío; el subsidio que ML le da al comprador no es ingreso nuestro.
- **El historial se recalcula.** Las ventas anteriores se recalculan solas, en segundo plano, con esta regla y la de la bonificación. Mientras dura vas a ver ventas con el Total Gauss viejo y otras con el nuevo.

## Cómo se usa

1. Abrí una venta en **Reportes → Ventas ML** (clic en la fila, se abre el panel al costado).
2. En la tarjeta **Total Gauss**, la línea **% de varios** ya trae el monto sobre la base nueva.
3. En **IVA por alícuota** ves el envío que pagó el comprador con su base y su IVA al 21%.

> Si una venta recién cargada todavía no muestra la bonificación o el envío, es probable que el costo del envío no haya llegado desde Mercado Libre: se actualiza sola cuando llega.
