# Ventas ML y Métricas ML: el costo es el costo SI y el sell out suma a la ganancia

Área: Reportes

## Resumen ejecutivo

Cada venta de Mercado Libre guarda como costo el **costo SI** vigente el día de la venta: el costo que ya tiene descontado el sell in. Por eso en **Métricas ML** ya no hay columna **Sell in** ni **Costo c/ sell in**: el costo es uno solo. El **sell out** se suma a la ganancia de la venta, nunca se resta del costo: si de ganancia tenés $ 1.000 y el sell out suma 10 %, tenés $ 1.100 de ganancia. Las columnas y los indicadores "c/ sell in/out" pasan a llamarse **c/ SO**.

## Cómo se usa

- **Métricas ML**: el grupo de columnas **Sell out** muestra **Costo**, **Sell out**, **Total c/ SO** (Total Gauss + sell out) y **Markup c/ SO** ((ganancia + sell out) / costo). Las tarjetas **Total Gauss** y **Markup promedio** muestran debajo la línea **C/ SO**, y la tarjeta **Sell out** muestra el sell out del período y el costo.
- **Exportar CSV** de Métricas ML trae las columnas **Sell out**, **Sell out pendientes**, **Total Gauss c/ SO** y **Markup c/ SO %**. Ya no trae **Sell in** ni **Costo c/ sell in**.
- **Ventas ML**: la columna **Sell in / out** ahora se llama **Sell out** y muestra solo el sell out de la venta (≈ si el tipo de cambio es estimado, "a definir" si todavía no tiene).
- En el panel de una venta, el detalle del costo de mercadería dice **Costo SI (por publicación)**, **Costo SI (por SKU)** o **Costo SI (combo)** cuando el costo de esa venta es el costo SI.

## A tener en cuenta

- Una venta cargada antes de este cambio puede mostrar todavía el costo anterior hasta que se recalcule con su costo SI: el panel de la venta lo dice (**ERP** o **Histórico** en vez de **Costo SI**).
- Ordenar por **Total c/ SO** o **Markup c/ SO** usa los mismos números que ves en la fila.
