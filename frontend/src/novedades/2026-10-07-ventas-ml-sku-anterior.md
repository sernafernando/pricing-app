# Ventas ML: SKU actual, "ex SKU" y búsqueda por SKU

Área: Ventas ML

## Resumen ejecutivo

Ventas ML muestra siempre el **SKU actual** de MercadoLibre. Si el SKU cambió después de la venta, ahora también se ve el anterior como **"ex 1214"**, al lado del nuevo. Y la búsqueda encuentra la venta por **cualquiera de los dos SKU**, también si es un número (por ejemplo `1215` o un EAN).

## Cómo se usa

- En cada fila y en el detalle de la venta, el SKU nuevo es el principal. Si hubo un cambio, aparece al lado, en gris, **ex** seguido del SKU con el que se vendió.
- En el buscador, escribí el SKU completo (actual o viejo) y listo. Con números la coincidencia es **exacta**: `1215` trae las ventas de ese SKU, no las de `12150`. Con texto (por ejemplo `ABC-9`) sigue buscando por coincidencia parcial.
- Si el número coincide con un número de venta o de pack, también se muestran esas ventas.

> El SKU viejo se guarda desde ahora. Las ventas cuyo SKU ya había cambiado antes de este cambio muestran solo el actual: lo anterior no se puede recuperar.
