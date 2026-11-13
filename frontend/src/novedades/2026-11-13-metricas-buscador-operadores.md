# Métricas ML: la búsqueda funciona igual que en Publicaciones ML

Área: Métricas ML

## Resumen ejecutivo

La búsqueda de **Métricas ML** entiende los mismos operadores que la de **Publicaciones ML**: `ean:`, `codigo:`, `marca:`, `desc:`, `promo:`, `mla:`, el `*` al principio o al final y el número de MLA exacto. Filtra las filas, las tarjetas y las opciones de los filtros, en la computadora y en el celular.

## Qué cambia

- **Operadores**: `ean:7791234567890` (EAN exacto), `codigo:ABC123` (código exacto), `marca:Samsung` (marca exacta), `desc:texto` (la descripción contiene el texto, sin guiones ni espacios), `promo:DEAL` o `promo:hot sale` (publicaciones con esa promoción activa), `MLA123456` o `mla:MLA123456` (esa publicación).
- **Asterisco**: `*AX55` busca lo que termina en AX55 y `L32*` lo que empieza con L32 (título, descripción, marca o código).
- **Texto común**: busca en el título y el SKU de la publicación, y en la descripción, marca y código del producto, sin importar guiones ni espacios. Antes buscaba texto suelto en cualquier campo: ahora un número de MLA o un código escrito entero encuentra solo ese.
- La búsqueda queda en el link de la pantalla, como antes.

## Cómo verlo

1. Abrir **Métricas ML**.
2. Escribir `marca:` y una marca en la búsqueda: quedan solo los productos de esa marca, y las tarjetas suman solo esos.
3. La lista completa de operadores está en la ayuda de la pantalla, en **Operadores de búsqueda**.
