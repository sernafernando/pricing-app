# Publicaciones ML: buscar por MLA y por promoción

Área: Publicaciones

## Resumen ejecutivo

La búsqueda de **Publicaciones ML** suma los dos operadores de **Productos** que faltaban:

- **mla:MLA123456** trae esa publicación exacta, igual que pegar el número solo.
- **promo:DEAL** (o cualquier tipo de promoción: SMART, LIGHTNING, ...) trae las publicaciones que tienen una promoción activa de ese tipo, aplicada o no.
- **promo:texto** trae las publicaciones que tienen una promoción activa cuyo nombre contiene ese texto, por ejemplo `promo:hot sale`.
- **promo:** se combina con el filtro de promociones: si están los dos, quedan las publicaciones que cumplen ambos.
- Si la información de promociones no está disponible en ese momento, la pantalla avisa en lugar de mostrar la lista sin filtrar.

## Cómo se usa

1. Abrir **Reportes → Publicaciones ML**.
2. Escribir en la búsqueda `promo:` seguido del tipo o del nombre de la promoción, o `mla:` seguido del número de publicación.
3. La ayuda de atajos (**?**) lista todos los operadores de búsqueda.
