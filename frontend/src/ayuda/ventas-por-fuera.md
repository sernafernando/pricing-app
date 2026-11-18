# Ventas por Fuera

Área: Reportes
Ruta: Reportes → Ventas por Fuera (abre Métricas con el canal **Por fuera**), Reportes → Operaciones por Fuera y Reportes → Cargas de PDF
Permiso: Pedile a un administrador acceso a las métricas de ventas por fuera (ventas_fuera.ver_metricas_pdf; ver la ganancia pide ventas_fuera.ver_ganancia; subir los PDF y corregir líneas pide ventas_fuera.subir_pdf).

## Para qué sirve

Muestra las ventas hechas por fuera de Mercado Libre, cargadas desde los reportes PDF de GBP. GBP no informa bien estos datos, así que las métricas por fuera salen solo de los PDF que se suben, no del sync de GBP.

Las ventas por fuera se ven en la misma pantalla que las de Mercado Libre: **Métricas**, con el selector **Canal** en **Por fuera**. Ahí se ven las unidades, lo facturado, el Total Gauss y el markup por producto, con los mismos filtros, columnas y exportación que Métricas ML. Está explicado en la ayuda de **Métricas ML**.

## Cómo se usa

1. Entrá a **Reportes → Ventas por Fuera**: se abre **Métricas** con el canal **Por fuera** elegido.
2. Elegí el período, la **Empresa** y el **Vendedor**.
3. Con **Costo por fuera** elegís el costo del markup y del Total Gauss: **Costo D** (el de siempre: Precio Costo × 1,065) o **Costo** (el Precio Costo del PDF).
4. Para cargar ventas nuevas usá **Subir PDF de ventas** (ver abajo).

Si tenés acceso a Métricas ML también podés pasar a **ML** o a **Todo** (las dos ventas sumadas, cada una con su regla). Si solo tenés acceso a ventas por fuera, la pantalla queda en **Por fuera**.

### Qué cambia en Por fuera

- Total Gauss = venta − costo: por fuera no hay comisión de Mercado Libre ni envío.
- El markup lo calculamos nosotros (venta / costo − 1). No se usan el Markup % ni el Profit % del PDF.
- Las notas de crédito restan unidades y plata.
- Las líneas sin producto (artículos manuales o códigos que no están en el catálogo) suman a la venta, pero no tienen marca, PM ni markup. Se ven con la etiqueta **Sin producto** y con la alerta **Sin producto**.
- El recargo del 4% de los cheques a 30 días no es venta: se guarda aparte por comprobante y no entra en el markup.
- No aparecen Tienda ML, Publicación, Publicidad, Costos TP ni Por tipo de envío, porque no existen fuera de Mercado Libre.

## Subir los PDF

**Subir PDF de ventas** (en Métricas y en **Cargas de PDF**) abre la carga. Hace falta el **Reporte de Ventas Detalladas** de GBP. El **Reporte de Ventas** (resumen) es opcional y sirve para controlar los totales. Los dos se exportan de GBP con "Con Impuestos: No".

1. Elegí o arrastrá los archivos.
2. La pantalla lee el PDF y muestra los vendedores que encontró, con sus comprobantes y su monto. Tildá los que querés importar. Los vendedores de la lista de excluidos (por ejemplo, los que en realidad son ventas de Mercado Libre o de Tienda Nube) aparecen sin tildar.
3. Tocá **Importar**. Solo se guardan los vendedores tildados.

El último PDF manda: lo que ya estaba cargado de esa empresa, de esos vendedores y en ese rango de fechas se reemplaza por lo del PDF nuevo. Así, un comprobante anulado en GBP también desaparece. Se puede subir todos los días sin que nada se duplique.

El resultado muestra la empresa, los vendedores, el rango, los comprobantes por tipo, las líneas y unidades, el total, qué se reemplazó, las líneas sin producto y el control con el resumen: si coinciden los comprobantes y los totales, y por qué no (por ejemplo, el recargo de los cheques). Si falta subir el resumen o la detallada de un vendedor y período, lo avisa.

## Operaciones por Fuera

**Operaciones por Fuera** (**Reportes → Operaciones por Fuera**) es la lista de las ventas cargadas desde los PDF, comprobante por comprobante, como la de **Ventas ML**. Pide el mismo permiso que ver las métricas por fuera (ventas_fuera.ver_metricas_pdf).

1. Elegí el período. Podés buscar por cliente, artículo, código o número de comprobante, y filtrar por **Empresa**, **Vendedor**, **Tipo** (Fc, Nc, Nd), **Sin producto** y **Revisar**.
2. Arriba ves los totales de lo filtrado: comprobantes, unidades, venta, costo, Total Gauss, markup, líneas sin producto y líneas a revisar. Con **Costo D / Costo** elegís qué costo usar, igual que en Métricas.
3. Cada fila es un comprobante, con sus marcas: **Nc**, **Cheque** (con el recargo financiero), cuántas líneas **sin producto** tiene y cuántas **a revisar**.
4. Tocá un comprobante para ver sus líneas al costado: artículo, producto, cantidad, precio, costo, Total Gauss y markup.

### Por qué hay líneas sin producto

El recuadro **Por qué hay líneas sin producto** cuenta las líneas y la venta de cada causa:

- **Artículo manual, sin código**: un artículo cargado a mano en GBP (por ejemplo, un envío o un servicio).
- **Sin código en el PDF**: la línea no trae código y el inicio del artículo no coincide con ningún producto.
- **Código que no está en el catálogo**: el código del PDF no existe en los productos.

En cada línea sin producto se ve también su causa.

### Corregir una línea

Con el permiso ventas_fuera.subir_pdf, cada línea tiene sus botones:

- **Costo**: abre la misma ventana de costo de la pantalla anterior (pesos o dólares con el tipo de cambio, el markup VARIOS y la opción de armar el costo sumando productos del ERP). El costo que guardás pasa a ser el Costo D de la línea.
- **Producto**: buscá el producto real y tocá **Asignar**. Con **Recordar para próximas cargas** tildado, las próximas cargas con el mismo código (o el mismo artículo, si no tiene código) toman ese producto solas.
- **Quitar corrección**: la línea vuelve al costo del PDF y al producto que encuentra el sistema.
- **Confirmar**: aparece en las líneas marcadas **Revisar** (ver abajo) y vuelve a aplicar la corrección.

Las líneas corregidas se ven con la marca **Manual**. Al guardar, la lista se actualiza y también las métricas, los offsets y el sell in / sell out de esa línea.

### Las correcciones no se pierden al subir el PDF de nuevo

Las correcciones se guardan aparte de lo que trae el PDF. Si volvés a subir un PDF que reemplaza ese período:

- Si la línea es la misma (mismo comprobante, renglón, artículo, cantidad y precio), la corrección se vuelve a aplicar sola.
- Si la línea cambió, la corrección se guarda pero no se aplica, y la línea queda marcada **Revisar**. Revisala y tocá **Confirmar** para aplicarla, o **Quitar corrección**.

## Cargas de PDF

**Cargas de PDF** (**Reportes → Cargas de PDF**) lista cada carga: cuándo se subió, quién la subió, empresa, vendedor, rango, comprobantes, líneas, total, cuánto reemplazó, líneas sin producto y el estado del control. Una carga que después se reemplazó se ve en gris con **reemplazada**. Al tocar una carga se ve su detalle: los archivos, los avisos y qué reemplazó. Los PDF no se guardan: solo queda el nombre del archivo.

Ahí también se ve qué falta subir: para cada empresa, vendedor y rango, si falta el resumen o la detallada.

**Vendedores excluidos** (enlace en Cargas de PDF) es la lista de vendedores que no son ventas por fuera. Desde ahí se agregan o se quitan.

## Preguntas frecuentes

**¿Dónde quedó la pantalla vieja de Ventas por Fuera?**
Volvió por un tiempo como **Reportes → Ventas por Fuera (anterior)** (`/dashboard-ventas-fuera`, pide ventas_fuera.ver_dashboard), con sus pestañas, la edición de costos y las correcciones de producto. Sus datos siguen saliendo del sync de GBP, no de los PDF, y las columnas de sell in / sell out quedan vacías. La lista de operaciones de los PDF ahora está en **Reportes → Operaciones por Fuera**.

**¿Por qué no veo el Total Gauss ni el markup?**
Piden el permiso ventas_fuera.ver_ganancia (y en **Todo**, también ml_metricas.ver_ganancia).

**¿Por qué no veo Subir PDF de ventas?**
Pide el permiso ventas_fuera.subir_pdf.

**Subí dos PDF que tienen las mismas operaciones, ¿se duplican?**
No. El último reemplaza lo cargado de esos vendedores en su rango de fechas.

**¿Cómo cuenta una nota de crédito en los offsets de ganancia?**
Resta: descuenta sus unidades y su monto del offset del grupo, también cuando el offset es un monto fijo.

**¿Por qué no veo los botones para corregir una línea?**
Piden el permiso ventas_fuera.subir_pdf.
