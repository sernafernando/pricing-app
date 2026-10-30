# Sell in / Sell out

Área: Productos
Ruta: Productos → Sell in / Sell out
Permiso: Pedile a un administrador acceso a Sell in / Sell out (sell_in.ver; la pestaña Sell out pide además sell_out.ver, y la pestaña Grupos, permiso de edición de constantes: config.editar_constantes).

## Para qué sirve

Gestiona las promociones de compra (sell in) que bajan el costo de una compra, los bonos de marca y las campañas de sell out que suman ganancia por campaña. Tiene tres pestañas: **Sell in**, **Sell out** y **Grupos** (los grupos de productos que alcanzan las campañas).

## Cómo se usa

En **Sell in** podés filtrar por fechas, marca, moneda (ARS/USD), estado (Activa/Anulada) y aplicación (aplican/no aplican). También podés filtrar por tipo: **Por compra** o **Bono de marca**. La tabla muestra las compras y, debajo, los bonos de marca. Arriba hay tarjetas de resumen.

Si tenés permiso, el botón **Nuevo sell in** abre el panel para crear una compra o un bono. Al tocar una fila se abre el panel lateral con el detalle.

En **Sell out** se listan las campañas (buscables por nombre), con paginación. Si tenés permiso, **Nueva campaña** abre el panel de campaña.

Para anular varias campañas de una vez (pide permiso de gestión de campañas, sell_out.gestionar): marcá la casilla de cada fila, la casilla del encabezado para toda la página, o **Seleccionar todo lo filtrado (N)** para todas las que coinciden con la búsqueda. La barra muestra cuántas hay seleccionadas; **Anular seleccionados** pide confirmación, dice cuántas se anulan y permite un motivo. El sell out que acreditaron deja de contar: se borran sus consumos y se recalculan las ventas que alcanzaban. Es todo o nada: si alguna no se puede anular, no se anula ninguna y el mensaje dice cuál y por qué. Si una se está recalculando, el mensaje la nombra y se puede reintentar en unos segundos. Las que ya estaban anuladas se omiten y el resultado las cuenta aparte. Se pueden anular hasta 500 por vez.

El botón **Actualizar** recarga todo.

### Grupos de productos

Las campañas de sell out alcanzan productos a través de **grupos**. En la pestaña **Grupos** se listan todos, con su descripción, sus filtros, cuántos productos alcanzan hoy y qué campañas los usan (las anuladas se cuentan aparte).

- **Nuevo grupo** pide nombre y descripción; después se le agregan filtros.
- **Editar** abre el panel lateral: ahí se cambia el nombre o la descripción (**Guardar nombre**), se agregan filtros y se quitan.
- Cada **filtro** es una fila con marca, categoría, subcategoría y/o un producto (buscado por código o descripción). Un producto entra en el grupo si cumple **alguna** fila; dentro de una fila tiene que cumplir **todos** los campos elegidos. Un grupo sin filtros no alcanza productos.
- Después de cada cambio se vuelve a contar cuántos productos alcanza el grupo.
- Cambiar los filtros de un grupo cambia los productos que alcanzan las campañas que lo usan: esas campañas se recalculan solas.
- Si una campaña **activa** usa el grupo, **Agregar filtro** y **Quitar** no guardan enseguida: primero el panel avisa qué campañas activas se van a recalcular y cuántos productos alcanza el grupo antes y después del cambio (por ejemplo, "Productos alcanzados: 42 → 30."). **Confirmar cambio** lo guarda; **Cancelar** no cambia nada. Sin campañas activas, el cambio se guarda enseguida.
- **Eliminar grupo** no se puede en estos casos, y el mensaje dice por qué:
  - Lo usa una campaña activa: el mensaje la nombra; hay que quitar el grupo de la campaña antes.
  - Solo lo usan campañas anuladas: el mensaje las nombra. El grupo queda guardado porque es parte del historial de esas campañas.
  - Lo usa un offset, o tiene consumo de offsets registrado (lo que esos offsets ya aplicaron en ventas).

### Anular varios a la vez

En las listas de compras y de bonos de marca, cada fila tiene una casilla. La del encabezado marca la página, y **Seleccionar todo lo filtrado (N)** marca todo lo que muestran los filtros. Las compras que genera un bono de marca no tienen casilla, porque se anulan anulando el bono: **Seleccionar todo lo filtrado** las deja afuera y lo avisa (por ejemplo, "3 anulables; 2 generadas por bonos no se pueden anular a mano"). Con algo marcado aparece **N seleccionados** y el botón **Anular seleccionados**, que pide confirmación y dice cuántos se anulan y qué se revierte: en una compra se liberan sus unidades, y en un bono se anulan las compras que generó.

Se anula todo o nada: si alguno no se puede anular, no se anula ninguno y se lista cuál y por qué. Si otra operación está modificando esos registros en ese momento, tampoco se anula ninguno y pide reintentar en unos segundos. Los ya anulados se saltean. Se anulan hasta 500 por vez y hace falta el mismo permiso que para anular de a uno.

### Bonos de marca: base del bono

Al crear un bono de marca, **Base del bono** define cómo se calcula. Se elige una sola vez: después de guardarlo no se cambia.

- **Sobre facturas**: paga por las unidades facturadas de la marca, en el rango de fechas de factura del proveedor.
- **Sobre el costo de la venta**: para operaciones viejas que no tienen la factura cargada. Es siempre un porcentaje en pesos sobre el costo de cada venta, y alcanza una **Marca**, una **Categoría** o algunos **Modelos**. Las fechas **Venta desde** y **Venta hasta** son fechas de venta, no de factura.
- **Incluye IVA** (solo sobre el costo): tildado, el porcentaje cargado incluye IVA y se divide por el IVA de cada producto (por ejemplo, 3 % en un producto con IVA 10,5 % queda 2,71 %). Sin tildar, el porcentaje se usa tal cual. Esta casilla sí se puede cambiar después.

> Cuando se carga la factura de una operación, el sell in de esa factura toma sus unidades y el bono sobre el costo deja de aplicarse a ellas: no se cuenta dos veces.

### Bonos de marca: acumulables o no

**Acumulable con otros bonos** viene tildada. Tildada, el bono se suma a los otros bonos que cobran sobre la misma unidad. Sin tildar, el bono no cobra sobre las unidades que ya cobró un bono anterior (creado antes), y los bonos posteriores tampoco cobran sobre las suyas. Se puede cambiar al editar el bono.

### Campañas de sell out: tipos

Al crear o editar una campaña se elige el **Tipo**:

- **Por unidad**: un monto por cada unidad vendida. Puede tener **Montos por producto** y topes de unidades y de monto.
- **Porcentaje**: un porcentaje del costo o del precio neto de cada venta, con topes opcionales.
- **Monto total**: un único importe para toda la campaña, que suma una sola vez al total. No lleva topes: el monto total es el tope. Puede ser **negativo**: en ese caso descuenta de la ganancia y la lista lo muestra resaltado como **Deducción de ganancia**.

### Reparto del monto total

Una campaña por **Monto total** muestra, al abrirla con **Ver campaña**, la sección **Reparto del monto total**. Ahí se elige a qué productos de la campaña se le asigna el monto y cuánto a cada uno. No se reparte en partes iguales ni por unidades: lo decide quien reparte. Dentro de cada producto, su parte se distribuye entre sus ventas en las fechas de la campaña.

- **Quién puede repartir**: el PM, sobre los productos de sus marcas, y quien gestiona campañas. Los demás ven el reparto sin poder cambiarlo. En el reparto, un PM ve solo los productos de sus marcas. Lo asignado a productos de otras marcas no se ve ni se cambia, pero se respeta al guardar y cuenta en **Asignado** y **Sin asignar**.
- **Cómo se reparte**: en **Agregar producto** se busca el producto por código o descripción. En su fila se elige **%** (un porcentaje del monto total) o **Monto fijo**, y se escribe el valor. Un monto fijo lleva el mismo signo que el total: en una deducción, también va en negativo. Un **%** siempre se escribe en positivo.
- Debajo de las filas se ven al momento lo **Asignado** y lo **Sin asignar** con los cambios, antes de guardar (marcados **aprox.** cuando incluyen productos de otras marcas que no ves). **Guardar reparto** los guarda. Si el reparto supera el monto total, o un monto fijo no tiene el signo del total, el panel lo dice y no guarda.

Arriba de la sección, la campaña muestra:

- **Asignado**: la suma de lo que se le dio a cada producto.
- **Asignado sin ventas**: la parte de lo asignado que fue a productos sin ventas en las fechas de la campaña.
- **Sin asignar**: lo que todavía no se le dio a ningún producto (monto total menos lo asignado, con el mismo signo).

Con **Incluye IVA** tildado, el IVA se descuenta con el IVA de cada producto en el momento en que el monto se le asigna: cada producto usa el suyo, aunque sean distintos. Por eso lo asignado a productos sin ventas ya se ve sin IVA, y lo **Sin asignar** se ve tal como se cargó, con IVA, con la aclaración **con IVA: se descuenta al asignarlo a un producto**. Sin tildar, todo se usa tal como se cargó. Al pasar el mouse sobre **Sin asignar** se ve esta regla.

Lo sin asignar (y lo asignado a productos sin ventas) no se pierde: suma en los totales de **Métricas ML** (el indicador de sell out, el total con sell in/out y una línea final del CSV) cuando el período incluye el día que termina la campaña, no en la fila de ningún producto. Con filtros (marca, categoría, producto, etc.) cuenta solo si la campaña alcanza alguno de los productos filtrados. Si el reparto guardado no se puede calcular, la sección dice por qué y no suma nada.

## Filtros y columnas

Sell in: fechas, marca, moneda, estado, aplicación, tipo. Sell out: búsqueda por nombre. Grupos: nombre, filtros, productos alcanzados y campañas que lo usan.

## Botones y acciones

- **Nuevo sell in** / **Nueva campaña** / **Nuevo grupo**: crean registros (según permiso).
- Tocar una fila: abre el panel lateral de detalle.
- **Actualizar**: recarga datos.

## Preguntas frecuentes

**¿Por qué no veo la pestaña Sell out?**
Pide un permiso adicional (sell_out.ver). Pedíselo a un administrador.

**¿Por qué no veo la pestaña Grupos?**
Pide permiso de edición de constantes (config.editar_constantes), el mismo que gestionar offsets. Pedíselo a un administrador.

**¿Por qué no puedo eliminar un grupo?**
Lo usa una campaña de sell out, un offset, o tiene consumo de offsets registrado. Si lo usa una campaña activa, el mensaje la nombra: quitá el grupo de esa campaña y volvé a intentar. Si solo lo usan campañas anuladas, el grupo queda guardado porque es parte de su historial.

**¿Qué diferencia hay entre sell in y sell out?**
Sell in baja el costo de la compra; sell out suma ganancia por campaña (o la descuenta, si es un monto total negativo).

**¿Por qué no puedo cambiar el reparto de una campaña?**
Repartir pide permiso de reparto (lo tienen los PM y los administradores) o de gestión de campañas, y la campaña tiene que estar activa. Un PM solo puede repartir productos de sus marcas.

**¿Por qué "Seleccionar todo lo filtrado" dice que la lista cambió?**
Antes de anular, la pantalla trae todas las campañas de la búsqueda y las cuenta. Si no coinciden con el total de la lista (por ejemplo, alguien cargó o anuló una campaña en ese momento), no selecciona nada para no anular de más ni de menos. Tocá **Actualizar** y volvé a intentar.
