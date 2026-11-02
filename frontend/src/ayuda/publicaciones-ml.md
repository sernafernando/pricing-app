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

Orden: las publicaciones arrancan ordenadas por tipo (primero las Clásicas, después 3, 6, 9 y 12 cuotas, al final cualquier otro tipo) y, dentro de cada tipo, por facturación de 30 días (o por última actividad si no ves ventas). Al hacer clic en el título de una columna, manda esa columna. Las publicaciones de un producto, al expandirlo o en su panel lateral, también salen ordenadas por tipo.

## Botones y acciones

- **Exportar CSV / Exportar a Sheets**: descarga el conjunto filtrado.
- Selector de columnas: elige qué columnas mostrar.
- **Indicadores**: elige qué tarjetas de KPI mostrar (todas visibles por defecto). Lista solo las que se ven en la pantalla; ocultar una no cambia ningún número. La elección queda guardada en este navegador.
- **Equipos**: gestiona equipos de color.
- Editar precios en línea (✓ guarda, ✗ cancela).
- Asignar color a un producto o a varios seleccionados.
- Acciones masivas (si tenés permiso).
- Clic en una fila: abre el panel lateral de detalle.
- **Ctrl + clic**: abre la publicación en Mercado Libre.

## Preguntas frecuentes

**¿Por qué no veo algunas acciones?**
Dependen de permisos (editar precios, marcar color, acciones masivas).

**¿Qué es la vista Agrupado?**
Agrupa las publicaciones por marca, categoría, subcategoría, etc., en un árbol expandible.

**¿Cómo sé qué lote de sell in va a aplicar en la próxima venta?**
En el panel del producto (pestaña Resumen) está la sección **Lotes sell in**: los lotes en orden FIFO con su estado (Vigente, En cola, Agotado, Desde dd/mm) y qué descuenta la próxima venta. Ver **Sell in / Sell out → Lotes de un producto**.
