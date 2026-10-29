# Sell in / Sell out

Área: Productos
Ruta: Productos → Sell in / Sell out
Permiso: Pedile a un administrador acceso a Sell in / Sell out (sell_in.ver; la pestaña Sell out pide además sell_out.ver).

## Para qué sirve

Gestiona las promociones de compra (sell in) que bajan el costo de una compra, los bonos de marca y las campañas de sell out que suman ganancia por campaña. Tiene dos pestañas: **Sell in** y **Sell out**.

## Cómo se usa

En **Sell in** podés filtrar por fechas, marca, moneda (ARS/USD), estado (Activa/Anulada) y aplicación (aplican/no aplican). También podés filtrar por tipo: **Por compra** o **Bono de marca**. La tabla muestra las compras y, debajo, los bonos de marca. Arriba hay tarjetas de resumen.

Si tenés permiso, el botón **Nuevo sell in** abre el panel para crear una compra o un bono. Al tocar una fila se abre el panel lateral con el detalle.

En **Sell out** se listan las campañas (buscables por nombre), con paginación. Si tenés permiso, **Nueva campaña** abre el panel de campaña.

El botón **Actualizar** recarga todo.

### Bonos de marca: base del bono

Al crear un bono de marca, **Base del bono** define cómo se calcula. Se elige una sola vez: después de guardarlo no se cambia.

- **Sobre facturas**: paga por las unidades facturadas de la marca, en el rango de fechas de factura del proveedor.
- **Sobre el costo de la venta**: para operaciones viejas que no tienen la factura cargada. Es siempre un porcentaje en pesos sobre el costo de cada venta, y alcanza una **Marca**, una **Categoría** o algunos **Modelos**. Las fechas **Venta desde** y **Venta hasta** son fechas de venta, no de factura.
- **Incluye IVA** (solo sobre el costo): tildado, el porcentaje cargado incluye IVA y se divide por el IVA de cada producto (por ejemplo, 3 % en un producto con IVA 10,5 % queda 2,71 %). Sin tildar, el porcentaje se usa tal cual. Esta casilla sí se puede cambiar después.

> Cuando se carga la factura de una operación, el sell in de esa factura toma sus unidades y el bono sobre el costo deja de aplicarse a ellas: no se cuenta dos veces.

### Campañas de sell out: tipos

Al crear o editar una campaña se elige el **Tipo**:

- **Por unidad**: un monto por cada unidad vendida. Puede tener **Montos por producto** y topes de unidades y de monto.
- **Porcentaje**: un porcentaje del costo o del precio neto de cada venta, con topes opcionales.
- **Monto total**: un único importe para toda la campaña, que suma una sola vez al total. No lleva topes: el monto total es el tope. Puede ser **negativo**: en ese caso descuenta de la ganancia y la lista lo muestra resaltado como **Deducción de ganancia**.

### Reparto del monto total

Una campaña por **Monto total** muestra, al abrirla con **Ver campaña**, la sección **Reparto del monto total**. Ahí se elige a qué productos de la campaña se le asigna el monto y cuánto a cada uno. No se reparte en partes iguales ni por unidades: lo decide quien reparte. Dentro de cada producto, su parte se distribuye entre sus ventas en las fechas de la campaña.

- **Quién puede repartir**: el PM, sobre los productos de sus marcas, y quien gestiona campañas. Los demás ven el reparto sin poder cambiarlo. Un PM ve solo los productos de sus marcas; lo asignado a otras marcas se respeta y cuenta en los totales.
- **Cómo se reparte**: en **Agregar producto** se busca el producto por código o descripción. En su fila se elige **%** (un porcentaje del monto total) o **Monto fijo**, y se escribe el valor. Un monto fijo lleva el mismo signo que el total: en una deducción, también va en negativo. Un **%** siempre se escribe en positivo.
- Debajo de las filas se ven al momento lo **Asignado** y lo **Sin asignar** con los cambios, antes de guardar. **Guardar reparto** los guarda. Si el reparto supera el monto total, o un monto fijo no tiene el signo del total, el panel lo dice y no guarda.

Arriba de la sección, la campaña muestra:

- **Asignado**: la suma de lo que se le dio a cada producto.
- **Asignado sin ventas**: la parte de lo asignado que fue a productos sin ventas en las fechas de la campaña.
- **Sin asignar**: lo que todavía no se le dio a ningún producto (monto total menos lo asignado, con el mismo signo).

Lo sin asignar (y lo asignado a productos sin ventas) no se pierde: suma en los totales el día que termina la campaña, no en la fila de ningún producto. Si el reparto guardado no se puede calcular, la sección dice por qué.

## Filtros y columnas

Sell in: fechas, marca, moneda, estado, aplicación, tipo. Sell out: búsqueda por nombre.

## Botones y acciones

- **Nuevo sell in** / **Nueva campaña**: crean registros (según permiso).
- Tocar una fila: abre el panel lateral de detalle.
- **Actualizar**: recarga datos.

## Preguntas frecuentes

**¿Por qué no veo la pestaña Sell out?**
Pide un permiso adicional (sell_out.ver). Pedíselo a un administrador.

**¿Qué diferencia hay entre sell in y sell out?**
Sell in baja el costo de la compra; sell out suma ganancia por campaña (o la descuenta, si es un monto total negativo).

**¿Por qué no puedo cambiar el reparto de una campaña?**
Repartir pide permiso de reparto (lo tienen los PM y los administradores) o de gestión de campañas, y la campaña tiene que estar activa. Un PM solo puede repartir productos de sus marcas.
