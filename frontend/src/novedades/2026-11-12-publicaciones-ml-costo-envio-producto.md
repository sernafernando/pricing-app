# Publicaciones ML: elegir el costo de envío de cada producto

Área: Publicaciones ML

## Resumen ejecutivo

El panel de un producto muestra, en **Precios**, el bloque **Costo de envío del producto**: todos los costos de envío posibles del producto a la vez (el máximo de sus publicaciones, el promedio, el promedio ponderado por ventas y el costo de cada publicación) y cuál usa. Hasta ahora siempre se usaba el más alto; ahora un PM puede elegir otro, y el markup y los precios del producto se calculan con ese costo.

## Cómo se usa

1. En **Publicaciones ML**, vista **Producto**, hacer clic en un producto: el panel abre en **Precios**.
2. Debajo de los precios está **Costo de envío del producto**. La opción en uso dice **Seleccionado**.
3. Elegir **Máximo (actual)**, **Promedio**, **Ponderado por ventas** o una publicación de la lista **Por publicación** (con su tipo, su logística, sus unidades vendidas en los últimos 30 días y **(más vendida)** en la que más vendió). **Ver las N restantes** muestra todas las publicaciones.
4. Tocar **Guardar elección**. La lista se actualiza con los markups nuevos y abajo queda quién hizo el cambio y cuándo.

> **Ponderado por ventas** siempre se calcula con las ventas de los últimos 30 días; si no hubo ventas, usa el promedio. Si la publicación elegida se pausa o se queda sin costo, se usa el máximo hasta que elijas otra, y el bloque lo avisa.

Para cambiar la elección hace falta el permiso para editar el precio de la Clásica de Productos; sin él, el bloque muestra la elección guardada pero no se puede cambiar.
