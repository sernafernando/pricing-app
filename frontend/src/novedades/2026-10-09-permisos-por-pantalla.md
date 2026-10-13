# Admin: los permisos de cada usuario ahora se ven por pantalla

Área: Administración

## Resumen ejecutivo

En **Gestión → Admin → Usuarios**, los permisos del usuario seleccionado ya no son una lista larga agrupada por categoría: ahora se muestran **por pantalla**, en el mismo orden que el menú lateral. De un vistazo se ve a qué pantallas entra, a cuáles no y qué permiso le falta para cada una.

Qué tenés que saber:

- **Cada pantalla muestra su estado:** **Accede**, **Sin acceso**, **Condicional** o **Pública** (no pide permiso).
- **Se ve qué permiso pide cada pantalla** y de dónde sale: del **rol**, de un **override** agregado o quitado, o si **falta**.
- **Se puede conceder, quitar o resetear** un permiso desde la misma fila, sin buscarlo en otra lista.
- **Condicional** aparece en las pantallas que muestran datos según las marcas y categorías de cada PM (por ejemplo **Métricas ML** y **Ranking productos**). Significa: tiene el permiso, pero no tiene pares marca/categoría asignados, así que la pantalla abre vacía.
- **Ningún permiso queda afuera:** los que no abren una pantalla (acciones dentro de una página o del sistema) siguen editables en el grupo **Permisos sin pantalla**, al final.

## Cómo se usa

1. Entrá a **Gestión → Admin**, pestaña **Usuarios**, y elegí un usuario de la lista.
2. Usá el buscador para encontrar una pantalla o un permiso: busca por nombre de pantalla, ruta, sección, código o descripción del permiso (no importan las mayúsculas ni los acentos).
3. Usá los filtros (detallados abajo) para acotar la lista.
4. Si a una pantalla le falta un único permiso, el botón **Conceder** de la fila lo agrega directamente.
5. Hacé clic en el nombre de la pantalla para ver el detalle: cada permiso con su descripción, si es **crítico**, de dónde viene y los botones **Conceder**, **Quitar** o **Resetear** (vuelve al permiso del rol).

### Filtros

- **Sin acceso:** pantallas a las que hoy no puede entrar.
- **Con overrides:** pantallas con algún permiso agregado o quitado a mano.
- **Críticos:** pantallas que piden algún permiso marcado como crítico.
- **Depende de datos:** pantallas cuyo contenido depende de las marcas y categorías asignadas.

> Si una pantalla figura como **Condicional**, el permiso no alcanza: hay que asignarle pares marca/categoría al usuario. El enlace **Ir a Mis Sub-PMs** de la fila lleva a la pantalla donde se delegan.

## Nuevo diseño de la pestaña Usuarios

La pestaña **Usuarios** ahora se divide en dos columnas:

- **A la izquierda, la lista de usuarios:** cada uno con su **rol**. Arriba hay un buscador por nombre, usuario, email o rol (no importan las mayúsculas ni los acentos). Al usuario seleccionado se le suma un indicador de **overrides** (`+agregados −quitados`).
- **A la derecha, el usuario seleccionado:** su nombre, rol, email y estado, con los botones **Editar**, **Password** y **Activar/Desactivar**.
- **Resumen de acceso:** arriba de la lista de pantallas, cuatro números: **Pantallas accesibles** (sobre el total), **Sin acceso**, **Condicionales** y **Overrides** agregados y quitados. Cuentan todas las pantallas del usuario, sin importar la búsqueda ni los filtros que tengas aplicados.

## Alta y edición de usuarios en una ventana

Crear o editar un usuario ya no despliega un formulario dentro de la lista ni del encabezado: ahora se abre en una **ventana** aparte.

- **+ Nuevo Usuario** abre la ventana con usuario, email, nombre completo, contraseña y rol.
- **Editar**, en el encabezado del usuario seleccionado, abre la misma ventana con sus datos cargados (sin contraseña: se cambia con **Password**).
- Los errores (por ejemplo, un campo obligatorio vacío) se muestran dentro de la ventana, sin cerrarla.
- Se cierra con **Cancelar**, con la **×** o con la tecla **Esc**. Hacer clic afuera no la cierra, para no perder lo cargado.
