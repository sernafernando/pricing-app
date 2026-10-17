# Publicaciones ML: SKU en la lista y mejor vínculo automático

Área: Publicaciones

## Resumen ejecutivo

**Publicaciones ML** muestra el SKU de cada publicación, y el vínculo automático con productos reconoce más formas de cargar el SKU.

- **SKU en cada fila:** junto al MLA aparece el SKU del vendedor, con un ícono de código de barras. Al pasar el mouse dice **SKU del vendedor**. Sirve para revisar por qué una publicación no se vincula. Si la publicación no tiene SKU en Mercado Libre, no se muestra nada.
- **SKU con otro formato:** el vínculo automático ahora reconoce el SKU aunque tenga espacios, guiones, puntos, barras o mayúsculas distintas de las del código del producto. Si el SKU coincide exactamente con un código, ese sigue teniendo prioridad.
- **SKU cargado como ID de producto:** si el SKU es un número que corresponde al ID de un producto, por ejemplo **981**, también se vincula. Los números con ceros adelante o con el largo de un código de barras no se toman como ID.
- **SKU vacío o solo con espacios:** se usa el campo personalizado de la publicación en Mercado Libre, como cuando no hay SKU.
- **SKU "0", vacío o solo con espacios:** nunca vincula por sí mismo.
- **Cuándo se aplica:** el nuevo criterio se aplica en el barrido diario de la madrugada, así que las publicaciones ya existentes se vinculan después de ese barrido.

## Cómo se usa

1. Abrir **Reportes → Publicaciones ML**.
2. En una publicación sin vincular, mirar el SKU que aparece junto al MLA.
3. Comparar ese SKU con el código del producto que debería tener.
4. Si sigue sin vincularse después del barrido de la madrugada, vincularla a mano desde el panel lateral.

> Para que una publicación se vincule sola, el SKU en Mercado Libre tiene que ser el código del producto o su ID.
