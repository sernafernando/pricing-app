# Banlist MLAs

Área: Productos
Ruta: Productos → Banlist MLAs
Permiso: Pedile a un administrador el permiso para gestionar la banlist.

## Para qué sirve

Sirve para mantener una lista de MLAs (y de productos) que se excluyen automáticamente de las exportaciones de rebates y de todas las vistas. Tiene dos pestañas: **🚫 Banlist MLAs** y **📦 Banlist Productos**.

## Cómo se usa

### Pestaña Banlist MLAs

Arriba dice **Banlist de MLAs** y aclara que los MLAs en esta lista se excluyen de las exportaciones de rebates.

En la sección **Agregar MLAs a la Banlist** pegá uno o varios MLAs separados por comas, espacios o saltos de línea (formatos **MLA123456789** o **123456789**), opcionalmente un **Motivo**, y usá **➕ Agregar a Banlist**. Mientras trabaja dice **⏳ Agregando...**.

Más abajo está la tabla **MLAs Baneados (N)** con buscador **Buscar por MLA, motivo o usuario...**. Columnas: **MLA**, **Motivo**, **Agregado por**, **Fecha** y, si sos administrador, **Acciones**. Si no hay resultados dice **No hay MLAs en la banlist** o **No se encontraron resultados**.

El botón **🗑️ Eliminar** (solo administradores) quita un MLA, con confirmación.

### Pestaña Banlist Productos

Dice **Banlist de Productos** y aclara que los productos en esta lista se excluyen de todas las vistas y exportaciones.

En **Agregar Productos a la Banlist** completá **Item IDs** y/o **EANs** (separados por comas, espacios o saltos de línea), opcionalmente un **Motivo**, y usá **➕ Agregar a Banlist**.

Más abajo está la tabla **Productos Baneados (N)** con buscador **Buscar por Item ID, EAN, código, descripción o motivo...**. Columnas: **Item ID / EAN**, **Código**, **Descripción**, **Motivo**, **Usuario**, **Fecha** y, si sos administrador, **Acciones**.

## Filtros y columnas

Sin filtros aparte del buscador por texto.

## Botones y acciones

- **➕ Agregar a Banlist**: agrega los MLAs o productos ingresados.
- **🗑️ Eliminar**: quita un registro (solo administradores), con confirmación.

## Preguntas frecuentes

**¿Qué pasa si ingreso un MLA duplicado?**
Se avisa cuántos eran duplicados y no se vuelven a agregar.

**¿Quién puede eliminar de la banlist?**
Solo los usuarios con rol administrador.
