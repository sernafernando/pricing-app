# Costo SI también para los productos sin sell in

Área: Productos, Tienda, Publicaciones ML, Métricas ML, Ventas por fuera

## Resumen ejecutivo

Los productos que nunca tuvieron un sell in ahora también tienen **costo SI**. Hasta ahora usaban el costo de lista. Su costo SI arranca el **1/11/2026 a las 00:00**: el stock disponible de ese momento (principal + Full), valuado al costo de lista vigente ese día. Desde ahí, cada factura de compra entra en el promedio ponderado, sin descuentos (no hay sell in que descontar).

Los productos con sell in siguen igual: su costo SI arranca el día de su primer sell in. Los combos siguen tomando el costo de sus componentes. Las **PC** (categoría 47) también valen la suma de sus componentes (cantidad × costo de cada uno), como los combos: nunca su propio costo de lista. Si una PC incluye otra PC (o un combo), esa también se cuenta por sus componentes.

## Cómo se usa

1. En **Productos**, **Tienda** o **Publicaciones ML**, la columna **Costo SI** de un producto sin sell in muestra su costo SI, ya sin **lista** al lado.
2. Pasar el mouse sobre el valor para ver desde cuándo rige: el 1/11/2026, o la fecha de la última factura de compra que entró en el promedio.

## A tener en cuenta

- Si el costo de lista de un producto sin sell in cambia, su costo SI pasa a ser el nuevo costo de lista desde las 00:00 del día siguiente al cambio, aunque no haya ninguna factura. Las facturas posteriores promedian desde ese valor. En los productos con sell in, el costo de lista no mueve el costo SI.
- Los markups, los costos de las ventas desde el 1/11/2026 y las métricas de esos productos se recalculan sobre el costo SI. Las ventas anteriores al 1/11/2026 no cambian.
- Sin costo de lista ese día y sin facturas desde entonces, no hay costo SI: se sigue viendo el costo de lista actual, o «—» si no hay ninguno. Nunca 0.
- Si un componente de una PC o de un combo no tiene costo, la PC o el combo queda sin costo («—»), nunca una suma parcial ni 0. Lo mismo si su lista de componentes se incluye a sí misma. Una PC sin componentes cargados sigue con su costo de lista.
