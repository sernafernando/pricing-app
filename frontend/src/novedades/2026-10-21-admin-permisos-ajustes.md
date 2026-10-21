# Admin: cada pantalla muestra sus permisos adicionales

Área: Administración

## Resumen ejecutivo

En **Gestión → Admin → Usuarios**, vista **Por pantalla**, los permisos que no abren una pantalla pero habilitan acciones dentro de ella (por ejemplo **productos.editar_precios** en **Productos**) ya no están mezclados en una lista al final: ahora aparecen **dentro de su pantalla**, como **Permisos adicionales**. Así, al darle acceso a una pantalla, ves en el mismo lugar qué más puede hacer ahí.

Qué tenés que saber:

- **Cada pantalla indica cuántos adicionales tiene** con un **+N adicionales** al lado de los permisos que pide.
- **Los adicionales no cambian el acceso:** una pantalla sigue en **Accede** aunque le falte un adicional.
- **Se conceden, quitan o resetean igual** que los permisos de acceso, desde la misma fila.
- **El grupo del final ahora se llama Otros permisos** y reemplaza a **Permisos sin pantalla**: solo quedan ahí los permisos que no pertenecen a ninguna pantalla (globales o del sistema).
- **El buscador y los filtros también miran los adicionales:** buscar `editar_precios` muestra **Productos**, y **Con overrides** y **Críticos** incluyen pantallas por sus adicionales.

## Cómo se usa

1. Entrá a **Gestión → Admin**, pestaña **Usuarios**, y elegí un usuario.
2. En **Por pantalla**, buscá la pantalla (por ejemplo **Productos**) y mirá el **+N adicionales** de la fila.
3. Hacé clic en el nombre de la pantalla: abajo de los permisos de acceso aparece **Permisos adicionales**, cada uno con su descripción, si es **crítico**, de dónde viene y los botones **Conceder**, **Quitar** o **Resetear**.

> Si un permiso de una pantalla aparece en **Otros permisos**, avisá: significa que todavía no sabemos a qué pantalla pertenece.
