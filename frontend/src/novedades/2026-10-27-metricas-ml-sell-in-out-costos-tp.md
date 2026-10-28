# Métricas ML: sell in / sell out con Costos TP y en el CSV

Área: Métricas ML

## Resumen ejecutivo

Esta nota aclara cómo se ve el grupo **Sell-in / Sell-out** de **Métricas ML** con **Costos TP** activado, y reemplaza lo que decían sobre eso las novedades del 23/10 y del 27/10.

- Con **Costos TP** activado, **Costo** y **Markup c/ sell in/out** muestran **—**: el markup usa el costo TP, y el sell in se descuenta del costo Gauss, así que no hay un costo ni un markup con sell in que mostrar. **Costo c/ sell in** queda vacío. **Sell in**, **Sell out** y **Total c/ sell in/out** se siguen viendo.
- Con **Costos TP** desactivado, el **Costo** se ve siempre, como antes.
- En **Exportar CSV**, la columna **Sell out pendientes** queda vacía en las filas sin sell out, igual que en la pantalla. Antes mostraba **0**.

## Cómo se usa

1. En **Métricas ML**, activar **Costos TP**.
2. En el grupo **Sell-in / Sell-out**, el **—** en **Costo** y en **Markup c/ sell in/out** indica que esa cifra no existe con costos TP; no es un error ni un cero.
