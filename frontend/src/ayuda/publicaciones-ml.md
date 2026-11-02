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

Columna **Tipo**: una etiqueta con el tipo de cada publicación (**Clásica**, **3 cuotas**, **6 cuotas**, **9 cuotas**, **12 cuotas**). Una Clásica con cuotas cofinanciadas por Mercado Libre dice **Clásica**; al pasar el mouse se aclara. Otros tipos muestran su nombre (por ejemplo, **Gratuita**).

Orden: las publicaciones arrancan ordenadas por tipo (primero las Clásicas, después 3, 6, 9 y 12 cuotas, al final cualquier otro tipo) y, dentro de cada tipo, por facturación de 30 días (o por última actividad si no ves ventas). Al hacer clic en el título de una columna, manda esa columna. Las publicaciones de un producto, al expandirlo o en su panel lateral, también salen ordenadas por tipo y, dentro de cada tipo, por última actividad.

## Botones y acciones

- **Exportar CSV / Exportar a Sheets**: descarga el conjunto filtrado. La columna **Tipo** del archivo dice lo mismo que la de la pantalla (**Clásica**, **3 cuotas**, …), no el código de Mercado Libre.
- Selector de columnas: elige qué columnas mostrar.
- **Indicadores**: elige qué tarjetas de KPI mostrar (todas visibles por defecto). Lista solo las que se ven en la pantalla; ocultar una no cambia ningún número. La elección queda guardada en este navegador.
- **Equipos**: gestiona equipos de color.
- Editar precios en línea (✓ guarda, ✗ cancela).
- Casilla de una fila: la de una publicación marca solo esa publicación, no las demás de su producto. En la vista **Producto**, la casilla de la fila de un producto marca el producto, y la de una publicación dentro de un producto abierto marca solo esa publicación. **Mayús + clic** en una casilla marca todas las filas entre la última marcada y esa; la casilla del encabezado marca las filas de la página.
- **Pintar**: pinta las filas marcadas en la capa elegida, cada una como lo que es. Una publicación se pinta sola, nunca las demás de su producto ni el producto (por ejemplo, "Pintar 2 publicaciones"); en la vista **Producto**, la fila de un producto pinta el producto. Una publicación pintada muestra su propio color, y si no tiene uno, el de su producto; **Sin color** le saca el suyo y vuelve a mostrar el del producto. El filtro de color sigue el color que se ve en cada publicación, y en la vista **Producto** las filas usan el color del producto. Con más de 500 publicaciones marcadas se pintan en tandas de 500. Los números del teclado (1 a 7) pintan la fila enfocada de la misma forma. Productos y las demás pantallas siguen mostrando el color del producto.
- Acciones masivas (si tenés permiso). Los precios son por producto: las acciones de precio se aplican a los productos vinculados de las filas marcadas, una vez cada uno, y el botón dice cuántos productos son y de cuántas publicaciones marcadas salen. Una publicación sin producto vinculado se puede marcar, pero no recibe acciones de precio.
- **Pausar / activar** (si tenés permiso): con filas marcadas, pausa o activa en Mercado Libre solo esas publicaciones (por ejemplo, "Pausar las 2 marcadas"), nunca las demás de su producto; la fila de un producto en la vista **Producto** incluye todas sus publicaciones. Sin nada marcado, actúa sobre las publicaciones del filtro. Antes de enviar, pide confirmar cuántas publicaciones van a cambiar, y deja sin tocar las que ya tienen ese estado.
- Clic en una fila: abre el panel lateral de detalle. El panel de una publicación abre en **Promos**; sin permiso para ver promociones, en **Precios**, y si tampoco hay precios para mostrar, en **Resumen**. El panel de un producto abre en **Precios**, o en **Resumen** si no hay precios para mostrar; al volver desde una de sus publicaciones queda en la pestaña donde estaba.
- Encabezado del panel: en todas las pestañas muestra el precio con el markup debajo (el markup solo con permiso para ver la ganancia), el stock y las ventas de 30 días (con permiso para ver las métricas). En el panel de un producto muestra el stock, las ventas y el markup de 30 días con los filtros actuales.
- Pestaña **Resumen** de una publicación: **Atención** (solo si hay algo para revisar: eliminada en Mercado Libre, subestado, último error, vínculo en conflicto o sin producto, markup negativo), **Rentabilidad** del precio al markup (con permiso para ver la ganancia), **Stock** junto a **Producto vinculado** y **Datos de la publicación**. El estado, el stock total y las ventas están en el encabezado y no se repiten abajo; el precio y el markup vuelven a aparecer solo como el principio y el final de **Rentabilidad**.
- Pestaña **Precios**: una línea con las referencias del producto (costo, costo con offset, sell in / sell out, IVA) y el botón **Calcular**; debajo, una tabla con una fila por plan (Clásica, 3, 6, 9 y 12 cuotas) con el precio de Lista ML y el de PVP y su markup, cada precio una sola vez. Cada precio se edita en su fila por monto o fijando el markup. Más abajo, el rebate, la mejor oferta, fuera de tarjetas y la web transferencia, con el precio de Tienda Nube. Si la mejor oferta es el mismo rebate (fuera de tarjetas), dice *Igual al rebate*.
- Pestaña **Promos**: para no saturar la conexión con Mercado Libre, después de consultar a Mercado Libre con éxito por las promociones de una publicación, no vuelve a consultar durante 5 minutos; mientras tanto muestra lo último que se trajo. Si una consulta falla, se vuelve a intentar la próxima vez que se abre la pestaña, y después de aplicar o quitar una promoción también se vuelve a consultar.
- **Ancho del panel**: arrastrá la línea entre la tabla y el panel (o enfocala con Tab y usá ← →) para darle más lugar a uno u otro. Los dos tienen un ancho mínimo (en una ventana angosta el panel conserva su mínimo y su ancho de siempre, y la tabla queda más chica) y el ancho elegido queda guardado en este navegador.
- **Ctrl + clic**: abre la publicación en Mercado Libre.
- **Alt + clic**: abre la publicación en el panel de vendedores de Mercado Libre.
- **Mayús + clic**: abre las promociones de la publicación en el panel de vendedores.
- Los tres atajos funcionan en cualquier parte de la fila y abren en el panel lateral de Mercado Libre si tenés instalada la extensión; si no, en una pestaña nueva.

## Preguntas frecuentes

**¿Por qué no veo algunas acciones?**
Dependen de permisos (editar precios, marcar color, acciones masivas).

**¿Qué es la vista Agrupado?**
Agrupa las publicaciones por marca, categoría, subcategoría, etc., en un árbol expandible.

**¿Cómo sé qué lote de sell in va a aplicar en la próxima venta?**
En el panel del producto (pestaña Resumen) está la sección **Lotes sell in**: los lotes en orden FIFO con su estado (Vigente, En cola, Agotado, Desde dd/mm) y qué descuenta la próxima venta. Ver **Sell in / Sell out → Lotes de un producto**.
