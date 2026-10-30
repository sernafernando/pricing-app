# Métricas ML: el monto total sin asignar ya suma al sell out

Área: Métricas ML

## Resumen ejecutivo

Las campañas de sell out por **monto total** ya suman en **Métricas ML** lo que no quedó en la venta de ningún producto: lo **Sin asignar** y lo **Asignado sin ventas**. Cuenta una sola vez, el día que termina la campaña.

- **Dónde se ve:** en el indicador **Sell in / Sell out** de arriba del tablero (su sell out y su total), y en una línea final del CSV. Nunca en la fila de un producto.
- **Cuándo:** si el período elegido incluye el día que termina la campaña.
- **Con filtros:** cuenta solo si la campaña alcanza alguno de los productos filtrados (por ejemplo, filtrando una marca, solo sus campañas).
- **IVA:** con **Incluye IVA** tildado, el IVA se descuenta con el IVA de cada producto al asignarle el monto. Lo sin asignar todavía no es de ningún producto, así que se ve y suma tal como se cargó, con IVA.

## Cómo se usa

1. Abrir **Métricas ML** (hace falta poder ver la ganancia).
2. Elegir un período que incluya el día que termina la campaña de monto total.
3. Mirar el indicador **Sell in / Sell out**: su sell out incluye lo sin asignar de esa campaña.
4. Hacer clic en **Exportar CSV**: la última línea, **Sell out de montos totales sin producto (Sin asignar y Asignado sin ventas)**, muestra ese importe en la columna **Sell out**.
5. En **Productos → Sell in → Campañas de sell out**, abrir la campaña con **Ver campaña** y pasar el mouse sobre **Sin asignar** para ver la regla del IVA.
