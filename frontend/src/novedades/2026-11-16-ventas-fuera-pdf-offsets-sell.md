# Ventas por Fuera: sell in, sell out y offsets salen de los PDF cargados

Área: Ventas

## Resumen ejecutivo

El sell in, el sell out y los offsets de ganancia de las ventas por fuera se calculan ahora solo con las operaciones cargadas desde los reportes PDF de GBP, no con las ventas sincronizadas de antes.

- El costo que usan es el **Costo D** (Precio Costo × 1,065).
- Una **nota de crédito** resta: devuelve sus unidades y descuenta su monto, también de un offset de monto fijo.
- Un offset en dólares se convierte con el tipo de cambio del día de la venta.
- En **Detalle de Operaciones**, **Costo c/ sell in** y **Markup c/ sell in/out** quedan en **-**: esa pestaña lista las ventas sincronizadas, que ya no reciben sell in ni sell out.

## Cómo se usa

1. Cargá los reportes PDF de ventas por fuera como siempre.
2. Al cargarlos, el sell in y el sell out de los productos de esas operaciones se recalculan solos.
3. Los offsets de ganancia de un grupo se actualizan como siempre, con su recálculo.
4. Para ver cuánto acreditó cada tactical o cada offset, usá **Sell in / Sell out** y **Offsets de ganancia** como hasta ahora.
