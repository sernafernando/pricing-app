# Sell in: los combos descuentan de los lotes de sus componentes

Área: Sell in

## Resumen ejecutivo

La venta de un combo (por ejemplo, una notebook con -WH) ahora descuenta de los lotes de sell in de **cada componente**, como si se hubiera vendido cada uno por separado. Antes el combo contaba como un producto propio y la notebook base no se enteraba.

- La cantidad que toma cada componente es la cantidad vendida por la cantidad de ese componente en el combo.
- El combo no usa lotes propios: nunca cuenta dos veces.
- Una devolución del combo devuelve las unidades a los lotes de cada componente.
- La composición sale del catálogo de combos de la app. Si todavía no está sincronizado, no se calcula nada y se reintenta solo.

## Cómo se usa

No hay que hacer nada: en **Lotes sell in** de la notebook base ya aparecen las ventas de sus combos.
