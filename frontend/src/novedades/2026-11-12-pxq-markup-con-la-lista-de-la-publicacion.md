# PxQ: el markup de cada precio mayorista usa los datos de la publicación

Área: Publicaciones ML

## Resumen ejecutivo

El markup de cada escalón de **PxQ** (precios mayoristas) ahora se calcula con los mismos datos que el markup de la cabecera de esa publicación:

- La lista de precios es la que Mercado Libre le cobra a la publicación (Clásica, 3, 6, 9 o 12 cuotas). Antes usaba una lista guardada que podía no coincidir.
- El producto (costo, IVA y grupo de comisión) es el que tiene vinculado la publicación, el mismo que usa la cabecera.

El costo de envío de cada escalón no cambia: sigue siendo el envío del pedido completo de ese escalón.

## Qué cambia

- Algunos escalones van a mostrar un markup distinto al de antes: el nuevo es el correcto.
- Cuando no se puede calcular, el escalón dice por qué, con el mismo motivo que la cabecera: la publicación no está vinculada a un producto, el producto no tiene costo, no hay comisión para la lista, las cuotas son cofinanciadas por Mercado Libre o el tipo de publicación no tiene lista nuestra.
- Una publicación que todavía no está en la tienda sincronizada ahora se muestra sin markup en PxQ, con ese motivo, en vez de un markup calculado con la lista guardada.
