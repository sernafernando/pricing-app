# Tienda muestra el sell in y el sell out

Área: Tienda

## Resumen ejecutivo

Tienda ahora muestra el sell in y el sell out como Productos, pero con sus propias cuentas (no las de Mercado Libre):

- En **Costo**, al lado y más chico, **c/ sell in** con el costo que queda, en la misma moneda que el costo.
- Debajo del markup de **Sugerido**, **Gremio** y **Web Transf.**, el markup **c/ sell in** y el markup **c/ sell in + sell out** (o **c/ sell out** si no hay sell in).

## Qué cambia

- Los markups con sell in y sell out usan el neto de cada precio de Tienda: en Sugerido y Gremio, el precio sin IVA sin el % de varios; en Web Transf., el precio sin IVA menos la comisión de Tienda Nube y el % de varios. No se usan comisiones ni envíos de Mercado Libre.
- El sell out depende del canal de cada precio: Sugerido y Gremio toman los tacticals que aplican a ventas **por fuera**; Web Transf. los que aplican a **Tienda Nube**. Un tactical que aplica a todos los canales suma en los tres; uno solo para tiendas oficiales de Mercado Libre no suma acá.
- Un sell out que es un % del precio usa el precio con IVA de esa misma columna.
- El sell in no depende de la tienda: es el mismo en todas las columnas.
- Los productos sin sell in ni sell out se ven igual que antes. Las columnas de cuotas no cambian.
