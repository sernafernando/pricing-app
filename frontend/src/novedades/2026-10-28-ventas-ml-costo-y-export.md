# Ventas ML: costo de cada venta y más columnas en el CSV

Área: Ventas ML

## Resumen ejecutivo

En **Ventas ML**, debajo del **Total Gauss** de cada venta ahora figura su **costo** (sin IVA). Es el mismo costo sobre el que se calcula el markup que aparece al lado. En un pack se ve la suma de sus órdenes.

El **Exportar CSV** suma cinco columnas al final, con lo que tenía la vieja pestaña de operaciones de Métricas ML:

- **costo_unitario**: el costo de cada producto de la venta, separado con `|` como en `producto`. Queda vacío si el producto no tiene costo cargado.
- **costo_total**: el costo de la venta.
- **neto_sin_iva**: lo que deja la venta sin IVA, antes de restar el costo.
- **bonificacion_envio**: lo que pagó Mercado Libre por el envío Flex.
- **tipo_publicacion**: Clásica o Premium, por producto.

El CSV del modo TP-Link no cambia.

## Lo que no volvió

La comisión y el envío de cada venta siguen en el panel de detalle (al tocar la venta), pero todavía no en el listado ni en el CSV. El "Offset Flex" y el "Lista" en cuotas de la pestaña vieja eran valores de configuración que ya no se usan, así que no se muestran.
