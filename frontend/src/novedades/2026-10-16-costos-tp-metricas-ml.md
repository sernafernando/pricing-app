# Métricas ML: ver el resultado con los costos TP

Área: Métricas ML

## Resumen ejecutivo

El tablero de **Métricas ML** tiene un interruptor nuevo, **Costos TP**, al lado de **Publicidad**. Al encenderlo, las operaciones de la tienda **TP-Link** se calculan con el **costo TP** (lista 8), y aparece el **Total TP** junto al **Total Gauss**.

- **Quién lo ve:** solo los usuarios que ya ven ganancias.
- **Arranca apagado:** está apagado al abrir el tablero y vuelve a apagarse al recargar la página.
- **Markup con costo TP:** con el interruptor encendido, el markup de las operaciones de la tienda TP-Link usa el costo TP. Las demás tiendas no cambian.
- **Tarjeta y columna Total TP:** aparece la tarjeta **Total TP** al lado de **Total Gauss**, y la columna **Total TP** en la tabla, en todos los niveles. El **Total Gauss** sigue estando.
- **Ventas sin costo TP:** si hay ventas de la tienda TP-Link sin costo TP, aparece un aviso con la cantidad ("sin costo TP" en la tarjeta). Si el costo falta solo en algunas, el Total TP muestra lo que se pudo calcular, junto con el aviso. Si falta en todas, se muestra **—** con la palabra **incompleto**. Una venta sin costo TP nunca se cuenta como 0.
- **Sin ventas de TP-Link:** el Total TP muestra **—** y, al pasar el mouse, "Sin ventas de la tienda TP-Link".
- **Exportar CSV:** con el interruptor encendido, el archivo incluye las columnas **Total TP** y **TP incompletas**, después de **Total Gauss** y de la columna de publicidad.
- **Ventas anteriores al 26/06/2026:** la lista 8 se empezó a usar ese día. Para las ventas anteriores, el costo TP es el primer precio de lista 8 cargado, así que es un valor aproximado.

## Cómo se usa

1. Abrir **Métricas ML**.
2. En la barra del tablero, encender **Costos TP**.
3. Comparar la tarjeta **Total TP** con **Total Gauss**, y revisar la columna **Total TP** en la tabla.
4. Si aparece el aviso de ventas sin costo TP, pasar el mouse por encima para ver cuántas son.
5. Para llevarlo a una planilla, hacer clic en **Exportar CSV** con el interruptor encendido.

> El Total TP de un período con ventas anteriores al 26/06/2026 es aproximado: usa el primer precio de lista 8 cargado.
