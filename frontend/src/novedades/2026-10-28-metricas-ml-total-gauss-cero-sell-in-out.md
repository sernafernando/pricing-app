# Métricas ML: una venta con Total Gauss en cero suma su sell in / sell out

Área: Métricas ML

## Resumen ejecutivo

En **Métricas ML**, una venta cuyo **Total Gauss** es exactamente **$ 0** ahora suma su **Sell in** y su **Sell out**, y entra en **Total c/ sell in/out**. Antes se trataba igual que una venta con el Total Gauss todavía sin calcular, y su sell in / sell out no se mostraba.

Una venta con el Total Gauss sin calcular sigue igual: no suma su sell in / sell out hasta que se calcula.

## Cómo se usa

1. En **Métricas ML**, mirar el grupo **Sell-in / Sell-out** de la tabla.
2. Las ventas con Total Gauss en cero de los días anteriores a este cambio se corrigen solas con el control diario de las ventas. Las ventas nuevas ya se ven bien.
