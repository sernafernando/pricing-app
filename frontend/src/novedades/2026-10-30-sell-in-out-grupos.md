# Sell in / Sell out: pestaña Grupos para armar los grupos de productos

Área: Productos

## Resumen ejecutivo

Los grupos de productos que usan las campañas de sell out ahora se arman en la misma pantalla. La nueva pestaña **Grupos** lista cada grupo con sus filtros, cuántos productos alcanza y qué campañas lo usan, y permite crearlos, renombrarlos, editar sus filtros y eliminarlos.

## Cómo se usa

1. Abrir **Productos → Sell in / Sell out** y pasar a la pestaña **Grupos**.
2. Tocar **Nuevo grupo**, escribir el nombre (y una descripción si hace falta) y tocar **Crear grupo**.
3. En el panel lateral, elegir marca, categoría, subcategoría y/o buscar un producto, y tocar **Agregar filtro**. Repetir para cada fila.
4. El panel muestra cuántos productos alcanza el grupo, y se actualiza después de cada cambio.
5. Para cambiar un grupo existente, tocar **Editar** en su fila.

## Para tener en cuenta

- Pide permiso de edición de constantes (config.editar_constantes), el mismo que gestionar offsets.
- Un producto entra en el grupo si cumple alguna fila; dentro de una fila, todos los campos elegidos.
- Cambiar un grupo cambia los productos que alcanzan las campañas de sell out que lo usan: esas campañas se recalculan solas.
- Un grupo que usa una campaña de sell out o un offset no se puede eliminar; si lo usa una campaña activa, el mensaje la nombra.
