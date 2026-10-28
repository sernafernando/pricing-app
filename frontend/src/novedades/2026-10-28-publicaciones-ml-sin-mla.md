# Publicaciones ML: productos sin MLA en la vista Producto

Área: Publicaciones

## Resumen ejecutivo

La vista **Producto** de Publicaciones ML muestra ahora la tarjeta **Sin MLA**, igual que Productos: cuántos productos del ERP no tienen ninguna publicación vinculada. Con un clic se listan esos productos, y se pueden exportar o usar en las acciones masivas de precios.

## Cómo se usa

1. Abrir **Reportes → Publicaciones ML** y elegir la vista **Producto**.
2. Arriba a la derecha aparece la tarjeta **Sin MLA** con la cantidad de productos.
3. Hacer clic en la tarjeta para listar esos productos. Otro clic vuelve a los productos con publicaciones.

## Para tener en cuenta

- Sin MLA usa solo los filtros de producto: búsqueda, marca, categoría, subcategoría, PM, stock del ERP, colores y filtros de presencia. Al activarla se quitan los filtros de publicación, como estado, tienda, tipo, vínculo, familia, oferta y promociones.
- Si se elige un filtro de publicación mientras Sin MLA está activa, la lista muestra un aviso de "Filtro inválido".
- Con un filtro de publicación activo, la tarjeta muestra "–", porque la cantidad no se puede calcular.
- La cantidad **puede no coincidir con la de Productos**. Productos toma los MLA del espejo del ERP. Publicaciones ML toma sus propios vínculos entre publicación y producto, contando también los de las variaciones. Los productos de los dos banlists de Productos quedan afuera en ambas pantallas.
- En Sin MLA no se muestran los indicadores de publicaciones ni el botón **Pausar / activar**, porque esos productos no tienen publicaciones.
