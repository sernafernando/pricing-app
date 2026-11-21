# Productos: los markups se calculan sobre el costo SI

Área: Productos

## Resumen ejecutivo

Los markups de **Productos** (Clásica, Rebate, Oferta, Web Transf., cuotas y PVP) y los precios que se calculan a partir de un markup ahora usan el **costo SI** del producto, en su moneda. Si el producto no tiene costo SI, se sigue usando el costo de lista.

## Cómo se usa

No hay que hacer nada. Cuando cambia el costo SI de un producto, sus markups guardados (y los de los combos que lo incluyen) se recalculan solos. Los precios no cambian nunca solos.

## A tener en cuenta

- Si el producto no tiene costo en pesos (no tiene costo, o el costo está en dólares y no hay dólar cargado), el markup se ve vacío en vez de un número inventado. La calculadora de precios avisa «Sin costo en pesos (sin costo, o costo USD sin tipo de cambio): no se calcula».
- Un precio cargado a mano se guarda igual. Las cuotas y el precio web transferencia que ya tenías guardados no se pisan.
- En los cálculos masivos (PVP, cuotas, web transferencia) los productos sin costo en pesos se saltean.
