# Ventas ML

Área: Reportes
Ruta: Reportes → Ventas ML
Permiso: Pedile a un administrador acceso a Ventas ML (ml_ops.ver).

## Para qué sirve

Muestra todas las ventas de Mercado Libre en un solo lugar: qué se vendió, a quién, en qué estado está el dinero y la mercadería, y cuánto quedó neto. Una fila es un pack (un paquete); si una compra tiene varios productos, es una sola fila que se abre para ver las ventas de adentro.

## Cómo se usa

Entrá a **Reportes → Ventas ML**. Elegí el período arriba a la izquierda (o un rango propio) y, si querés, buscá por texto en el buscador.

Afiná con los filtros:
- **Tienda**: Gauss, TP-Link Oficial u otras tiendas oficiales.
- **Operación** (el dinero) y **Mercadería** (el producto): son dos ejes independientes. Una venta cancelada puede tener la mercadería todavía en el depósito, o ya devuelta.
- **Producto**: marca, categoría, subcategoría y PM. Las opciones se ajustan entre sí.
- **Solo con alertas**: deja únicamente las ventas que tienen algo para revisar.
- **Incluir**: tildes para mostrar u ocultar ventas A revisar, En disputa, Mixta, Provisorio y Canceladas. Cuando ocultás una categoría, te dice cuántas está escondiendo.

Mirá las tarjetas de totales: cantidad de ventas, facturado bruto, neto de ML, Total Gauss, markup promedio y las ventas que todavía no tienen Total Gauss utilizable. Las ventas sin cobro efectivo se cuentan aparte.

En la tabla, cada fila muestra el producto (con SKU y MLA; si hay varios, un cartel +N productos), la orden, el comprador, el estado, el envío, el importe, el neto y el Total Gauss.

**Limpiar filtros** vuelve al punto de partida.

## Filtros y columnas

Filtros: período, tienda, operación, mercadería, producto (marca/categoría/subcategoría/PM), solo con alertas, incluir (A revisar/En disputa/Mixta/Provisorio/Canceladas), búsqueda por texto.

Columnas: configurables con el botón de columnas; se pueden redimensionar arrastrando el borde del encabezado y restablecer con **Restablecer columnas**. La elección queda guardada en el navegador.

## Botones y acciones

- Clic en una fila: abre el panel fijo a la derecha con el desglose (pack o venta suelta). Se puede cerrar con la cruz o Esc.
- Dentro de un pack abierto, clic en una de sus ventas para ver el detalle puntual.
- **Ctrl + clic** (o Cmd + clic en Mac) sobre una fila abre esa venta directamente en Mercado Libre.
- **Columnas**: elige qué columnas mostrar.
- **Exportar CSV**: baja las ventas filtradas (no solo la página actual).
- **% de varios**: muestra el historial del porcentaje de varios que se usa para llegar al Total Gauss. Solo quien tiene permiso puede cargar uno nuevo.
- **Actualizar**: vuelve a cargar la tabla y los totales. Arriba a la derecha ves cuándo se sincronizó por última vez con Mercado Libre.
- Si tenés permiso (ml_ops.resincronizar), el panel de una venta tiene un botón para resincronizarla con Mercado Libre y recalcular sus números.

## Preguntas frecuentes

**¿El día de una venta es el día de la venta o del pago?**
El día en que se acreditó la plata, no cuando se abrió la operación. Las ventas rechazadas o sin plata acreditada no aparecen en ningún día.

**¿Los totales suman lo que veo?**
Sí, los totales siempre suman exactamente lo que ves filtrado.

**¿Qué es un pack?**
Un paquete. Si una compra tiene varios productos, es una sola fila que se abre para ver las ventas de adentro.

**¿Qué aviso puedo ver arriba de la tabla?**
Si el cálculo de métricas está detenido, las tarjetas muestran un aviso de que los totales pueden estar desactualizados.
