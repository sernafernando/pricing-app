# Métricas ML: dónde quedó el Offset Flex

Área: Métricas ML

## Resumen ejecutivo

El tablero anterior de métricas de Mercado Libre mostraba un **Offset Flex** y un **markup con flex**. **Métricas ML** no los muestra, y no van a volver.

- **Qué era el Offset Flex:** un monto fijo cargado en **Constantes Pricing**. Se sumaba como ganancia estimada a cada venta Flex por debajo de un precio.
- **Dónde quedó:** el **Total Gauss** de **Métricas ML** ya incluye lo que ese monto estimaba, con los valores reales de cada venta: la **Bonificación por envío** de Flex y el envío que paga el comprador, menos el costo propio del envío Flex.
- **Por qué no vuelve:** sumarlo encima del Total Gauss contaría esa plata dos veces.

## Cómo se usa

1. Para ver la bonificación de una venta Flex, abrir **Ventas ML**, abrir la venta y mirar **Bonificación por envío** en el detalle del neto.
2. En **Métricas ML**, el **Total Gauss** y el **Markup promedio** ya la incluyen.
