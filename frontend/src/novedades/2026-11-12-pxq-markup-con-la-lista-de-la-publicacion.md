# PxQ: el markup de cada precio mayorista usa la lista de la publicación

Área: Publicaciones ML

## Resumen ejecutivo

El markup de cada escalón de **PxQ** (precios mayoristas) ahora calcula la comisión con la lista de precios que Mercado Libre le cobra a la publicación (Clásica, 3, 6, 9 o 12 cuotas), la misma que usa el markup de la cabecera de esa publicación. Antes usaba una lista guardada que podía no coincidir.

El costo de envío de cada escalón no cambia: sigue siendo el envío del pedido completo de ese escalón.

## Qué cambia

Algunos escalones van a mostrar un markup distinto al de antes: el nuevo es el correcto. Una publicación sin lista nuestra (por ejemplo, con cuotas cofinanciadas por Mercado Libre) queda sin markup en vez de mostrar uno calculado con otra lista.
