# RMA: la traza ML usa las ventas de Ventas ML

Área: RMA Seguimiento

## Resumen ejecutivo

Al cargar un caso nuevo y buscar por la venta de Mercado Libre, la venta y sus productos salen de las ventas que ya guardamos (las mismas que muestra **Ventas ML**), aunque el ERP todavía no tenga la venta, el pedido o la factura.

- Sirve con el número de venta, el número de compra (paquete) o el número de envío.
- Cada producto aparece con su código y la cantidad vendida (por ejemplo, CART-NEGRO · Cant. 2), aunque no tenga número de serie, y se agrega con **Agregar**.
- El producto se reconoce con el mismo vínculo que usa el costeo de Ventas ML.
- Si el ERP tiene la venta, siguen apareciendo sus números de serie, el pedido, la factura y los RMA, como antes.
