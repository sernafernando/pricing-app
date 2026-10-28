# Publicaciones ML: la búsqueda entiende los operadores de Productos

Área: Publicaciones

## Resumen ejecutivo

En **Publicaciones ML**, la búsqueda ahora responde como la de **Productos**:

- **desc:texto** (o **descripcion:texto**) busca en la descripción del producto, sin importar guiones ni espacios: `desc:cable-hdmi` encuentra "Cable HDMI 2m".
- **texto\*** busca lo que **comienza con** ese texto, en el título de la publicación o en la descripción, la marca o el código del producto. Ya existía **\*texto** (termina en).
- La búsqueda normal ahora también encuentra por **marca**, y en el producto ignora guiones y espacios: `kbhdmi` encuentra el código "KB-HDMI-2M" y `hik vision` encuentra la marca "Hikvision".
- La ayuda de atajos (**?**) lista todos los operadores de búsqueda.

## Cómo se usa

1. Abrir **Reportes → Publicaciones ML**.
2. Escribir en la búsqueda, por ejemplo `desc:domo`, `rout*` o el nombre de una marca.
3. Para ver todos los operadores, apretar **?** o el botón **Atajos de teclado** del encabezado.
