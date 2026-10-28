# Publicaciones ML: productos sin MLA en la vista Producto

Área: Publicaciones

## Resumen ejecutivo

La vista **Producto** de Publicaciones ML muestra ahora la tarjeta **Sin MLA** junto a las tarjetas de totales, igual que Productos: el **Total**, **Con Stock**, **Sin Stock** y **Nuevos** de los productos del ERP que no tienen ninguna publicación vinculada. Con un clic se listan esos productos, y se pueden exportar o usar en las acciones masivas de precios.

## Cómo se usa

1. Abrir **Reportes → Publicaciones ML** y elegir la vista **Producto**.
2. En la tarjeta **Sin MLA**, hacer clic en un número para listar esos productos: por ejemplo, **Con Stock** lista los productos sin publicación que tienen stock en el ERP.
3. Para volver a los productos con publicaciones, hacer clic en **Total Productos** o en cualquier otra tarjeta.

## Para tener en cuenta

- Sin MLA usa solo los filtros de producto: búsqueda, marca, categoría, subcategoría, PM, stock del ERP, colores y filtros de presencia. Al elegir un número de Sin MLA se quitan los filtros de publicación, como estado, tienda, tipo, vínculo, familia, oferta y promociones.
- Si se elige un filtro de publicación mientras Sin MLA está activa, la lista muestra un aviso de "Filtro inválido".
- Con un filtro de publicación activo, los números de Sin MLA muestran "–", porque no se pueden calcular.
- Las cantidades **pueden no coincidir con las de Productos**. Productos toma los MLA del espejo del ERP. Publicaciones ML toma sus propios vínculos entre publicación y producto, contando también los de las variaciones. Los productos de los dos banlists de Productos quedan afuera en ambas pantallas.
- En Sin MLA no se muestran los indicadores de publicaciones ni el botón **Pausar / activar**, porque esos productos no tienen publicaciones.
