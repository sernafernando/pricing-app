# Publicaciones ML: vínculo con productos igual que en Productos

Área: Publicaciones

## Resumen ejecutivo

**Publicaciones ML** ahora vincula cada publicación con su producto igual que la pantalla **Productos**, usando el mapa de publicaciones del sistema. El SKU de Mercado Libre queda solo como respaldo para las publicaciones que ese mapa no conoce.

- **Por qué cambia:** el SKU cargado en Mercado Libre muchas veces es de otro producto, por ejemplo un Deco X60 con el código del Deco E4. Medido antes del cambio: 203 publicaciones mostraban el producto equivocado y 795 aparecían sin vincular aunque Productos las conocía.
- **Primero el mapa, después el SKU:** si el mapa de publicaciones asocia la publicación a un producto del catálogo, se usa ese producto. Si no, decide el SKU con las mismas reglas que hasta ahora.
- **Los vínculos manuales siguen mandando:** un vínculo cargado a mano no cambia.
- **El SKU sigue visible:** el SKU de cada fila se sigue mostrando, aunque no coincida con el producto vinculado.
- **Cambios en minutos:** cuando cambia el mapa de publicaciones, el vínculo se actualiza en la próxima pasada, en minutos, y no al día siguiente.
- **Reemplaza la carga única del sistema anterior:** la novedad "vínculos cargados desde el sistema anterior" del 17/10 anunciaba una carga única que nunca se aplicó. Ya no hace falta, porque el mapa ahora se usa siempre.

## Cómo se usa

1. Abrir **Reportes → Publicaciones ML**.
2. Revisar el producto vinculado de cada publicación: ahora es el mismo que muestra **Productos**.
3. Si una publicación tiene el producto equivocado, vincularla a mano desde el panel lateral.

> Para corregir un vínculo en las dos pantallas a la vez, corregir la publicación en el mapa de publicaciones del sistema.
