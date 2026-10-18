# Publicaciones ML: filtro de SKU distinto del producto

Área: Publicaciones

## Resumen ejecutivo

**Publicaciones ML** tiene una opción nueva en el filtro **Vínculo**: **SKU distinto del producto**. Lista las publicaciones cuyo SKU cargado en Mercado Libre no corresponde al producto con el que están vinculadas, que es el mismo que muestra la pantalla **Productos**.

- **Columna SKU distinto:** con el filtro activo, aparece una columna que muestra, para cada publicación:
  - el tipo de diferencia;
  - **SKU en Mercado Libre**;
  - **Producto por SKU**, el producto que corresponde a ese SKU;
  - **Producto vinculado**.
- **Tipos de diferencia:**
  - **Otro producto:** el SKU es el código de otro producto.
  - **SKU sin coincidencia:** el SKU no coincide con ningún producto o está vacío.
- **Aviso en cualquier vista:** las publicaciones con SKU distinto llevan un ícono de aviso en la celda **Publicación**. Al pasar el mouse dice **SKU distinto del producto vinculado** y el tipo.
- **Para qué sirve:** para corregir el SKU en Mercado Libre.
- **El vínculo no cambia:** manda el producto de Productos, aunque el SKU diga otra cosa.

## Cómo se usa

1. Abrir **Reportes → Publicaciones ML**.
2. En el filtro **Vínculo**, elegir **SKU distinto del producto**.
3. En la columna **SKU distinto**, comparar el SKU en Mercado Libre con el producto vinculado.
4. Corregir el SKU de la publicación en Mercado Libre.

> Una publicación con **Otro producto** puede confundir a quien la busque por SKU: conviene corregirla primero.
