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

## Roles: el rol que elegís se destaca en la matriz

En **Gestión → Admin → Roles**, al hacer clic en un rol ahora su columna queda **marcada en la matriz de permisos**: el encabezado y todas sus casillas se ven resaltados, y los permisos que tiene se ven más fuertes que los que no tiene. Así ves de un vistazo qué tiene habilitado, sin recorrer la matriz entera.

- **Solo los permisos de este rol:** arriba de la matriz aparece una casilla que deja solo las filas de los permisos que tiene el rol, con la cantidad entre paréntesis. Las categorías que quedan vacías se ocultan.
- **Cuenta los cambios sin guardar:** si marcás o desmarcás una casilla del rol, el filtro y la cantidad lo tienen en cuenta antes de guardar.
- **Sigue prendido al cambiar de rol:** si elegís otro rol, el filtro pasa a mostrar los permisos del nuevo.
- **Al cerrar el panel del rol** se quita el resaltado y se apaga el filtro.
- **Desde el panel del rol:** el número de **Permisos** es un enlace que prende el filtro directamente.

### Cómo se usa

1. Entrá a **Gestión → Admin**, pestaña **Roles**.
2. Hacé clic en la tarjeta de un rol: se abre su panel y su columna queda resaltada en la matriz.
3. Tildá **Solo los permisos de este rol** (o hacé clic en el número de **Permisos** del panel) para ver solo lo que tiene.
4. Cerrá el panel para volver a ver la matriz completa.

## Admin a todo el ancho y usable en el celular

**Gestión → Admin** ahora usa **todo el ancho de la pantalla** en todas sus pestañas: la matriz de **Roles** muestra más columnas sin tener que desplazarse.

En el **celular**:

- **Las pestañas se deslizan de costado** en vez de ensanchar la página: ya no hay que mover la pantalla de lado a lado.
- **Usuarios muestra la lista o el usuario, no las dos cosas apiladas:** al tocar un usuario se abre su detalle, y el botón **← Usuarios** vuelve a la lista. El nombre, el rol y el estado se leen completos y los botones **Editar**, **Password** y **Desactivar** quedan debajo.
- **La matriz de roles deja ver los roles:** la columna **Permiso** es más angosta (sin el código) y queda fija a la izquierda, así entran al menos dos roles al lado.
- **El panel del rol se abre desde abajo** por encima de la matriz, sin empujarla hacia abajo. Se cierra con la **X**.
- **Menos márgenes**, para aprovechar el ancho del teléfono.
