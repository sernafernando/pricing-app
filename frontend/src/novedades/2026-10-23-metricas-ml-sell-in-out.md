# Métricas ML: costo, Total Gauss y markup con sell in y sell out

Área: Reportes

## Resumen ejecutivo

En **Métricas ML**, el grupo **Sell-in / Sell-out** de la tabla ya muestra cifras reales. Cada producto y cada publicación muestran cuánto sell in y sell out les tocó, y cómo quedan el costo, el Total Gauss y el markup con esos montos.

- **Costo** y **Costo c/ sell in:** el costo de siempre y el costo menos el descuento de sell in.
- **Sell in** y **Sell out:** los montos que se aplicaron a las ventas del período, en pesos.
- **Total c/ sell in/out:** el Total Gauss sumando el sell in y el sell out.
- **Markup c/ sell in/out:** el markup sumando a la ganancia el sell in y el sell out, sobre el costo con sell in.
- Las columnas **Total Gauss** y **Markup** no cambian: siguen siendo las cifras sin sell in ni sell out.
- El ícono de advertencia con un número en **Sell out** indica cuántas ventas tienen un sell out en dólares sin tipo de cambio. Esos montos no se suman hasta que el tipo de cambio esté definido.
- Una venta que todavía no tiene Total Gauss calculado no suma su sell in ni su sell out: entra cuando se calcula, igual que en Total Gauss.
- **≈** con un número indica cuántas ventas tienen un sell out con tipo de cambio estimado.
- Las tarjetas **Total Gauss** y **Markup promedio** muestran debajo el valor **C/ sell in/out** del período.
- Con **Costos TP** activado, **Costo c/ sell in** y **Markup c/ sell in/out** quedan vacíos, porque el sell in se calcula sobre el costo Gauss. **Total c/ sell in/out** se sigue mostrando. Mientras Costos TP está activado no se puede ordenar por **Markup c/ sell in/out**: si la tabla estaba ordenada por esa columna, pasa a ordenarse por Facturado.
- Las columnas y las tarjetas solo se ven con el permiso de ver ganancia. Se pueden ordenar por **Sell in**, **Sell out**, **Total c/ sell in/out** y **Markup c/ sell in/out**.
- **Exportar CSV** agrega las columnas de sell in y sell out.

## Cómo se usa

1. Abrir **Reportes → Métricas ML**.
2. Desplazar la tabla hacia la derecha hasta el grupo **Sell-in / Sell-out**.
3. Comparar **Costo** con **Costo c/ sell in**, y **Total Gauss** con **Total c/ sell in/out**.
4. Pasar el mouse sobre el ícono de advertencia o sobre **≈** para ver cuántas ventas están pendientes o estimadas.
5. Con **Columnas** se pueden ocultar o mostrar estas columnas.
