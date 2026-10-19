# Sell in: vincular varias operaciones de Compras

Área: Productos

## Resumen ejecutivo

Al cargar un sell in, el campo **Pedido de compra (N°)** ahora permite vincular varias operaciones de **Compras**, y el formulario se completa con sus datos.

- **Varias operaciones:** cada número se agrega con **Agregar operación** o con Enter, y queda como una etiqueta, por ejemplo **N° 15**, que se puede quitar. Se pueden vincular hasta 50.
- **Completa lo que está vacío:** al vincular las operaciones, el formulario completa el proveedor, la fecha de ingreso y los productos con las cantidades pedidas en las órdenes de compra. Lo que ya está cargado no se toca.
- **Pregunta antes de reemplazar productos:** si ya hay productos cargados, el panel pregunta si se quieren reemplazar por los de las operaciones: **Mantener los actuales** o **Reemplazar productos**.
- **Moneda como sugerencia:** si las operaciones están en otra moneda que el sell in, aparece una sugerencia, por ejemplo **Las operaciones están en USD. Usar USD**. La moneda del sell in no cambia sola, porque puede ser distinta de la de las operaciones.
- **Mismo proveedor y misma moneda:** todas las operaciones vinculadas tienen que ser del mismo proveedor y estar en la misma moneda. Si no, el panel muestra el motivo.
- **En el detalle:** el sell in muestra sus operaciones, por ejemplo **Operaciones de compra: N° 15, N° 16**.

## Cómo se usa

1. Abrir **Productos → Sell in** y hacer clic en **Nuevo sell in**.
2. En **Pedido de compra (N°)**, escribir el número de una operación y hacer clic en **Agregar operación** o presionar Enter.
3. Repetir con cada operación que corresponda al sell in.
4. Revisar el proveedor, la fecha de ingreso y los productos que se completaron.
5. Si el panel pregunta por los productos, elegir **Mantener los actuales** o **Reemplazar productos**.
6. Completar el monto y el reparto, y seguir como siempre: **Calcular vista previa** y **Guardar sell in**.

> Para quitar una operación, hacer clic en la cruz de su etiqueta.
