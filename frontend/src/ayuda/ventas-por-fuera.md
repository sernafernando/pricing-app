# Ventas por Fuera

Área: Reportes
Ruta: Reportes → Ventas por Fuera (abre Métricas con el canal **Por fuera**)
Permiso: Pedile a un administrador acceso a las métricas de ventas por fuera (ventas_fuera.ver_metricas_pdf; ver la ganancia pide ventas_fuera.ver_ganancia; subir los PDF pide ventas_fuera.subir_pdf).

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

## Cargas de PDF

**Cargas de PDF** (**Reportes → Cargas de PDF**) lista cada carga: cuándo se subió, quién la subió, empresa, vendedor, rango, comprobantes, líneas, total, cuánto reemplazó, líneas sin producto y el estado del control. Una carga que después se reemplazó se ve en gris con **reemplazada**. Al tocar una carga se ve su detalle: los archivos, los avisos y qué reemplazó. Los PDF no se guardan: solo queda el nombre del archivo.

Ahí también se ve qué falta subir: para cada empresa, vendedor y rango, si falta el resumen o la detallada.

**Vendedores excluidos** (enlace en Cargas de PDF) es la lista de vendedores que no son ventas por fuera. Desde ahí se agregan o se quitan.

## Preguntas frecuentes

**¿Dónde quedó la pantalla vieja de Ventas por Fuera?**
La reemplaza Métricas con el canal **Por fuera**. Los links viejos llevan ahí.

**¿Por qué no veo el Total Gauss ni el markup?**
Piden el permiso ventas_fuera.ver_ganancia (y en **Todo**, también ml_metricas.ver_ganancia).

**¿Por qué no veo Subir PDF de ventas?**
Pide el permiso ventas_fuera.subir_pdf.

**Subí dos PDF que tienen las mismas operaciones, ¿se duplican?**
No. El último reemplaza lo cargado de esos vendedores en su rango de fechas.

**¿Cómo cuenta una nota de crédito en los offsets de ganancia?**
Resta: descuenta sus unidades y su monto del offset del grupo, también cuando el offset es un monto fijo.
