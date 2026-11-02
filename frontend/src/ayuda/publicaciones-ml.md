# Publicaciones ML

Área: Reportes
Ruta: Reportes → Publicaciones ML
Permiso: Acceso a Productos o a Ventas ML (productos.ver o ml_ops.ver).

## Para qué sirve

Gestiona todas las publicaciones de Mercado Libre: verlas, filtrarlas, ordenarlas, editar precios en línea, asignar colores, aplicar acciones masivas y exportar. Se puede ver por producto, por publicación, por precios o agrupado.

## Cómo se usa

Arriba dice **Publicaciones ML**. Hay un botón **Exportar CSV** / **Exportar a Sheets** (si está habilitado), un selector de columnas y **Equipos** para gestionar equipos de color.

Debajo está la barra de filtros: búsqueda por producto/SKU/MLA/marca, vista (Producto/Publicaciones/Precios/Agrupado), dimensión (en agrupado), estado, tienda, presencia (rebate/oferta/web transf/tienda nube/out of cards), tipo, vínculo, stock, color, productos, auditoría, promos, precios mayoristas y markup.

La tabla lista las publicaciones con sus métricas; al expandir una fila se ven las publicaciones del producto. Se pueden editar precios en línea, asignar colores, aplicar acciones masivas (si tenés permiso) y ver el detalle en el panel lateral.

**Limpiar filtros** vuelve al punto de partida.

## Filtros y columnas

Filtros: búsqueda, vista/agrupación, estado, tienda, presencia, tipo, vínculo, stock, producto, auditoría, color, promos, precios mayoristas y markup.

Columnas: configurables con el selector de columnas (incluye código, descripción, marca, stock, costos, precios, markups, etc.).

## Botones y acciones

- **Exportar CSV / Exportar a Sheets**: descarga el conjunto filtrado.
- Selector de columnas: elige qué columnas mostrar.
- **Indicadores**: elige qué tarjetas de KPI mostrar (todas visibles por defecto). Lista solo las que se ven en la pantalla; ocultar una no cambia ningún número. La elección queda guardada en este navegador.
- **Equipos**: gestiona equipos de color.
- Editar precios en línea (✓ guarda, ✗ cancela).
- Asignar color a un producto o a varios seleccionados.
- Acciones masivas (si tenés permiso).
- Clic en una fila: abre el panel lateral de detalle. El panel de una publicación abre en **Promos**; sin permiso para ver promociones, en **Precios**, y si tampoco hay precios para mostrar, en **Resumen**. El panel de un producto abre en **Precios**, o en **Resumen** si no hay precios para mostrar; al volver desde una de sus publicaciones queda en la pestaña donde estaba.
- Pestaña **Promos**: para no saturar la conexión con Mercado Libre, después de consultar a Mercado Libre con éxito por las promociones de una publicación, no vuelve a consultar durante 5 minutos; mientras tanto muestra lo último que se trajo. Si una consulta falla, se vuelve a intentar la próxima vez que se abre la pestaña, y después de aplicar o quitar una promoción también se vuelve a consultar.
- **Ancho del panel**: arrastrá la línea entre la tabla y el panel (o enfocala con Tab y usá ← →) para darle más lugar a uno u otro. Los dos tienen un ancho mínimo (en una ventana angosta el panel conserva su mínimo y su ancho de siempre, y la tabla queda más chica) y el ancho elegido queda guardado en este navegador.
- **Ctrl + clic**: abre la publicación en Mercado Libre.

## Preguntas frecuentes

**¿Por qué no veo algunas acciones?**
Dependen de permisos (editar precios, marcar color, acciones masivas).

**¿Qué es la vista Agrupado?**
Agrupa las publicaciones por marca, categoría, subcategoría, etc., en un árbol expandible.

**¿Cómo sé qué lote de sell in va a aplicar en la próxima venta?**
En el panel del producto (pestaña Resumen) está la sección **Lotes sell in**: los lotes en orden FIFO con su estado (Vigente, En cola, Agotado, Desde dd/mm) y qué descuenta la próxima venta. Ver **Sell in / Sell out → Lotes de un producto**.
