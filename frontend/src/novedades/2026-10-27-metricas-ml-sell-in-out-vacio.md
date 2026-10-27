# Métricas ML: sell in / sell out vacío donde no aplica

Área: Métricas ML

## Resumen ejecutivo

En **Métricas ML**, las columnas de sell in / sell out quedan **vacías** en las filas que no tienen ninguno: antes mostraban **$ 0** y repetían el Total Gauss y el markup sin sell in. El **Costo** se sigue viendo siempre. Lo mismo pasa en el resumen de arriba y en el CSV exportado.

## Cómo se usa

1. En **Métricas ML**, mirar el grupo **Sell-in / Sell-out** de la tabla.
2. Una fila con celdas vacías no tiene sell in ni sell out en el período; si solo tiene sell out, queda vacío el sell in y su costo.
