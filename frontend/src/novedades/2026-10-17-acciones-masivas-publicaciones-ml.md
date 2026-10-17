# Publicaciones ML: acciones masivas de precios

Área: Publicaciones

## Resumen ejecutivo

**Publicaciones ML** tiene un menú nuevo, **Acciones masivas**, con las mismas acciones de precios masivas que **Productos**: **Calcular Web Transf.**, **Calcular PVP** y **Markup y cuotas**. Se aplican sobre los productos vinculados a las publicaciones, así que el precio cambia en todas las publicaciones de cada producto.

- **Sobre el filtro actual:** si no hay nada seleccionado, las acciones se aplican a los productos vinculados de todas las publicaciones que muestra el filtro. En la vista por publicación eso incluye el filtro de markup, así que se pueden filtrar los markups negativos y corregirlos de una vez.
- **O sobre una selección:** cada fila tiene una casilla que selecciona su producto vinculado. Con productos seleccionados, las acciones se aplican solo a esos. **Limpiar selección** vuelve al filtro. La selección se vacía al cambiar de filtro o de vista.
- **Cuántos productos son:** el botón muestra la cantidad antes de aplicar, y el menú dice sobre cuántos productos se va a aplicar.
- **Lo que queda afuera:** las publicaciones sin producto vinculado y los productos que ya no están en el catálogo quedan afuera, y el menú avisa cuántos son. Las filas sin producto vinculado no se pueden seleccionar.
- **Tope de 10.000 productos:** si el filtro abarca más, el botón queda desactivado y explica el motivo.
- **El botón también queda desactivado** mientras se calculan los productos del filtro o si el filtro no selecciona ningún producto vinculado. Al pasar el mouse por el botón se ve el motivo.
- **Permisos:** cada acción pide el mismo permiso que en Productos. Sin ninguno de esos permisos, el menú no aparece.

## Cómo se usa

1. Abrir **Reportes → Publicaciones ML** y filtrar las publicaciones.
2. Si hace falta, marcar la casilla de las filas cuyos productos se quieren cambiar.
3. Hacer clic en **Acciones masivas** y revisar sobre cuántos productos se va a aplicar y qué queda afuera.
4. Elegir **Calcular Web Transf.**, **Calcular PVP** o **Markup y cuotas**.
5. Completar la ventana, igual que en Productos, y confirmar.
