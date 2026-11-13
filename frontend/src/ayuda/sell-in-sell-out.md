# Sell in / Sell out

Área: Productos
Ruta: Productos → Sell in / Sell out
Permiso: Pedile a un administrador acceso a Sell in / Sell out (sell_in.ver; la pestaña Grupos pide además grupos.ver; la pestaña Productos pide además poder ver productos (productos.ver o un permiso de edición de precios); crear, editar y borrar grupos pide además el permiso de edición de constantes: config.editar_constantes).

## Para qué sirve

Gestiona las promociones de compra (sell in) que bajan el costo de una compra, los bonos de marca y las campañas de sell out que suman ganancia por campaña. Tiene tres pestañas: **Tacticals** (los acuerdos con las marcas, de sell in y de sell out, en una sola lista), **Grupos** (los grupos de productos que alcanzan las campañas) y **Productos** (el modo de costo de cada producto con lotes). Se abre en **Tacticals**. Las pestañas **Sell in** y **Sell out** ya no están: todo lo que mostraban se ve en **Tacticals**, y un link viejo a una de ellas abre **Tacticals** con ese tipo elegido. La pestaña **Programas** tampoco está: el tactical es el programa de la marca, y un link viejo a Programas abre **Tacticals**.

## Cómo se usa

Cada sell in y cada campaña de sell out se carga como un tactical, con **Nuevo tactical** en la pestaña **Tacticals** (ver más abajo). Lo que tomó cada línea se ve con **Ver ventas**.

El botón **Actualizar** recarga todo.

### Nuevo tactical

Un tactical es un acuerdo con una marca: sus datos y todas sus líneas se cargan en una sola pantalla y se crean juntos con **Crear tactical**.

1. **Tipo**: **Sell out** (la marca te paga por cada unidad vendida en el rango) o **Sell in** (baja el costo de lo que vendés en el rango). Solo se puede elegir el tipo que tu permiso deja gestionar.
2. **Datos del tactical**: nombre, marcas (una o varias: cada marca elegida queda como etiqueta con su cruz para quitarla, y el desplegable ofrece las que faltan; sirven para filtrar los tacticals por marca), referencia de la marca (opcional), vigencia **Desde**/**Hasta** (en la misma línea que la referencia), moneda (**USD** o **ARS**, con el tipo de cambio al lado) y condiciones. Sell out arranca en USD y sell in en ARS. En USD aparece **Tipo de cambio**: **Al cobro**, **Fijo** (pide el valor) o **Día de la venta**. **Los montos incluyen IVA** y **Se acumula con otras campañas** (marcado de entrada) son las condiciones. La nota es opcional.
   - **Tiendas donde aplica** (solo en sell out): **Todas las tiendas oficiales** (marcado de entrada) alcanza todas las ventas del producto: las de Mercado Libre (también las de publicaciones sin tienda oficial), las de **Por fuera**, las de **Tienda Nube** y las de cualquier canal que se sume más adelante. Al destildarlo aparecen las tiendas oficiales, **Por fuera** y **Tienda Nube** para elegir: entonces solo cuentan las ventas de publicaciones de las tiendas tildadas y de los canales tildados (las ventas de Mercado Libre sin tienda oficial quedan afuera). La tienda de una venta es la tienda oficial de su publicación. Un tactical de sell in no elige tiendas: baja el costo de todas las ventas del producto (cualquier tienda, por fuera y Tienda Nube) con un solo tope.
   - **Por factura**: una línea por factura no tiene fechas. Su reintegro aplica a las unidades que entraron en esa factura hasta que se vendan, cuando sea que se vendan; después, las ventas siguientes del producto ya no lo toman. Se puede agregar una factura de cualquier fecha. Si todas las líneas de un sell in son por factura, **Vigencia** dice «Por factura» y no pide fechas. Si el tactical mezcla líneas por factura con otras, las fechas siguen siendo obligatorias y valen solo para las otras líneas. Si en Compras corrigen la fecha de la factura, el reintegro sigue aplicando. Una línea se puede cargar antes de que llegue la factura, con monto total, % o monto por unidad: en **+ Factura** la operación dice «Esperando factura»; la línea no aplica nada hasta que Compras vincula la factura de esa operación, y desde ahí aplica igual que si se hubiera cargado con la factura (un monto total se reparte recién entonces sobre lo facturado). Mientras espera, una línea de monto total no tiene **Ver ventas**. Si se anula o se edita el tactical antes de que llegue la factura, la línea que espera se anula o se cambia como cualquier otra.
   - **Tope compartido entre las tiendas elegidas**: tildado (de entrada), todas las tiendas y canales elegidos restan de un solo tope, como hasta ahora; destildado, cada tienda o canal tiene su propio contador con el mismo tope. Debajo, un recuadro explica qué hace el tope con las tiendas elegidas, usando el primer tope de unidades de las líneas (por ejemplo 100 u.): tildado se titula «Un solo tope entre todas» y dice que «cuando se vendan 100 u. en total, deja de acreditar en todas»; destildado se titula «Un tope para cada tienda o canal», muestra las 100 u. de cada una y dice que cuando una llega a 100 u. vendidas deja de acreditar solo en esa y las demás siguen. Si ninguna línea tiene tope de unidades, habla del «tope de la línea». Con un tope por tienda, **Todas las tiendas oficiales** da un tope a cada tienda oficial, otro a las ventas sin tienda oficial y uno a cada canal (**Por fuera** y **Tienda Nube**), y el **Máximo a cobrar** de cada línea y del resumen suma un tope por cada tienda o canal (un monto total no se multiplica). En la campaña o el bono, el tope dice «por tienda» y lo que «quedan» suma lo que todavía puede acreditar cada tienda o canal, «entre todas las tiendas»; una tienda que ya llegó a su tope suma cero.
   - Los tacticals que ya existían antes de que estuviera esta opción siguen acreditando igual que siempre: quedaron con **Todas las tiendas oficiales**, **Por fuera**, **Tienda Nube** y **Tope compartido** tildados. **Renovar** los abre así.
3. **Líneas**: cada línea tiene un alcance y un monto con sus topes.
   - Alcance: **Productos** (uno o varios: **+ Producto** abre el buscador, se tildan los que van y **Agregar a la línea**; cada uno queda como etiqueta con su cruz para quitarlo), **Marca** (con una **Categoría** opcional al lado: solo ofrece las categorías en las que la marca tiene productos; con **Todas las categorías** alcanza toda la marca, y elegir una, por ejemplo TP-LINK y Routers, alcanza solo los routers de TP-LINK; al cambiar la marca, la categoría vuelve a **Todas las categorías**), **Categoría** y, solo en sell in, **Factura** (**+ Factura** busca las compras por número, proveedor o fecha; se pueden tildar varias). Una línea de factura arranca en **monto total** (se reparte entre los productos de la factura según lo facturado), y también puede ser un **%** o un monto **por unidad** sobre lo facturado.
   - Monto: **por unidad**, **%** o **monto total**. Los montos se escriben como en Argentina (3,6 o 1.500).
   - **Monto total en sell out**: un importe en la moneda del tactical (USD o ARS) que se reparte entre los productos de la línea en las fechas del tactical, sin cargar el monto de cada producto. Debajo de lo que incluye la línea se elige **cómo repartirlo** (es obligatorio): **Partes iguales por modelo** (el total se reparte en partes iguales entre los productos de la línea que vendieron en el rango: un producto sin ventas no recibe parte, porque lo que no vendió lo vendió otro), **Según unidades vendidas** (cada unidad vendida en el rango recibe la misma parte: el reparto sigue las ventas y las devoluciones de esas fechas, y nunca pasa el total) o **Proporcional al costo** (el total se reparte según el costo de cada producto, también solo entre los que vendieron en el rango). Una línea de monto total no lleva topes ni la pastilla **Por producto**: el total es el tope. Si falta el criterio, el aviso dice «Hay 1 línea sin reparto del monto total. Completala o eliminala.».
   - **Monto total en sell in**: en una línea de productos, marca o categoría, el total baja el costo de esas ventas y se reparte con el mismo selector (**Partes iguales por modelo**, **Según unidades vendidas** o **Proporcional al costo**; es obligatorio). No lleva topes: el total es el tope. El total queda guardado en pesos (ARS), porque el costo de cada venta está en pesos. En un tactical en USD, **monto total** se puede elegir solo con **Tipo de cambio** **Fijo**: el importe en USD se pasa a pesos a ese tipo de cambio (con otro tipo de cambio el botón aparece apagado y dice «Un monto total en USD necesita tipo de cambio fijo.»). **Partes iguales por modelo** y **Proporcional al costo** (costo de cada producto en pesos, al último tipo de cambio BNA; un producto sin costo no recibe parte) fijan la parte de cada producto al crear, aunque no tenga ventas: en sell in se descuenta el costo igual (a diferencia de sell out). Un combo nunca recibe parte propia, aunque la marca o la categoría lo alcance: sus ventas cuentan en sus componentes, que se llevan todo el total; **Según unidades vendidas** reparte el total entre las unidades vendidas en las fechas del tactical. El total tiene que ser mayor que cero: en sell in no se descuenta un monto negativo. Una línea de factura sigue igual que antes: su monto total se reparte según lo facturado y no lleva criterio.
   - **Quién reparte por criterio**: crear un tactical de sell in pide `sell_in.gestionar` (o ser administrador), un permiso sin restricción de marca; por eso el reparto por criterio está disponible para todo el que puede cargar la línea.
   - Topes: **Tope unidades** y **Tope monto**; corta el que se alcance primero. Con varios productos, la pastilla **Por producto** (cada producto con sus topes) se puede cambiar a **Compartido** (un solo tope para todos).
   - **Máximo a cobrar** es lo más que puede dar la línea: el monto total; con %, el tope de monto; por unidad, monto × tope de unidades (por cada producto si los topes son por producto), sin pasar el tope de monto.
   - Cada línea se puede **duplicar** o **eliminar**. **+ Agregar línea** suma una y abre el buscador de productos.
4. La barra de abajo resume: en sell out, líneas, productos, tope total de unidades y máximo a cobrar; en sell in, líneas, marca (o marcas) y vigencia.

Si falta algo, un aviso arriba dice qué (por ejemplo, «Hay 1 línea sin productos. Completala o eliminala.»). Un tope que no se puede leer como número (o de unidades con decimales) o un porcentaje mayor a 100 también frenan el alta: nunca se manda una línea sin el tope que escribiste. Si el servidor rechaza una línea, el aviso nombra la línea como la ves en pantalla. Al crear, vuelve al listado y muestra «Tactical creado: …». **Cancelar** pregunta antes de descartar lo cargado.

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
- **Borrar seleccionados** borra varios grupos a la vez: marcá la casilla de cada uno (la del encabezado marca todos) y confirmá. Se borran los que se pueden borrar; los demás se quedan, y el aviso dice cuántos se borraron y, para cada uno de los que quedaron, el mismo motivo que daría **Eliminar grupo**.
- Con el permiso para ver grupos (grupos.ver) pero sin el de edición de constantes, la pestaña es de lectura: no aparecen **Nuevo grupo**, **Editar** ni las casillas.

### Bonos de marca: base del bono

Al crear un bono de marca, **Base del bono** define cómo se calcula. Se elige una sola vez: después de guardarlo no se cambia.

- **Sobre facturas**: paga por las unidades facturadas de la marca, en el rango de fechas de factura del proveedor.
- **Sobre el costo de la venta**: para operaciones viejas que no tienen la factura cargada. Va en pesos sobre el costo de cada venta, y alcanza una **Marca**, una **Categoría** o algunos **Modelos**. Las fechas **Venta desde** y **Venta hasta** son fechas de venta, no de factura. En **Forma del monto** se elige **% del costo de la venta** o **Monto total**.
- **Monto total** (solo sobre el costo de la venta): un importe en pesos (ARS) que se reparte entre los productos del bono según **Repartir el monto total**: **Partes iguales por modelo**, **Según unidades vendidas** o **Proporcional al costo**. No lleva topes ni valores propios por modelo: el total es el tope. Si el total es cero o negativo, el bono no se guarda y el panel muestra el motivo. Al abrir el bono, la sección **Reparto del monto total** muestra la parte de cada producto (código, producto y monto) en **Partes iguales por modelo** y **Proporcional al costo**; en **Según unidades vendidas** dice que el total sigue las unidades vendidas en las fechas del bono. Cargar o editar un bono pide `sell_in.gestionar`, sin restricción de marca, así que el criterio está disponible para todo el que puede editarlo.
- **Incluye IVA** (solo sobre el costo): tildado, el porcentaje cargado incluye IVA y se divide por el IVA de cada producto (por ejemplo, 3 % en un producto con IVA 10,5 % queda 2,71 %). Sin tildar, el porcentaje se usa tal cual. En un **Monto total**, tildado significa que el total incluye IVA: a la parte de cada producto se le descuenta su IVA. Esta casilla sí se puede cambiar después.

> Cuando se carga la factura de una operación, el sell in de esa factura toma sus unidades y el bono sobre el costo deja de aplicarse a ellas: no se cuenta dos veces.

**Marca con categoría:** una línea por marca de sell in con categoría, cargada en un tactical, se lista como «Marca TP-LINK · Routers» y alcanza solo los productos de la marca en esa categoría. Al abrirla, debajo de la marca dice «Solo la categoría Routers de la marca (se elige en el tactical).». Editarla desde acá conserva la categoría; la categoría se elige o se cambia solo en el tactical.

### Bonos de marca: acumulables o no

**Acumulable con otros bonos** viene tildada. Tildada, el bono se suma a los otros bonos que cobran sobre la misma unidad. Sin tildar, el bono no cobra sobre las unidades que ya cobró un bono anterior (creado antes), y los bonos posteriores tampoco cobran sobre las suyas. Se puede cambiar al editar el bono.

### Lotes de un producto

Cada venta toma las unidades del lote más viejo que todavía tiene (orden FIFO). Lo que descuenta por unidad depende del modo de costo del producto: por defecto es FIFO, y cada unidad descuenta el valor de su lote; con **ponderado** todas las unidades que quedan descuentan el promedio ponderado de los lotes, con **último precio** descuentan el valor del lote más nuevo, y con **manual** las unidades que quedan se reemplazan por una cantidad y un costo cargados a mano. Ponderado y último precio cambian el valor, nunca el orden en que se usan las unidades. Para ver cómo van a aplicar los lotes de un producto, abrí la sección **Lotes sell in** en el panel del producto de **Publicaciones ML** (pestaña Resumen) o en la ficha de información del producto de **Productos** (pestaña **Lotes sell in**).

- Arriba dice qué descuenta la próxima venta, por ejemplo: "La próxima venta descuenta $ 33,33 por unidad (lote 2); quedan 2 unidades a ese valor, después $ 10,00". Si ningún lote tiene unidades hoy, dice que el costo vuelve al normal (y hasta cuándo, si queda un lote con fecha futura) y si aplica un bono de costo en su lugar; si el lote vigente es el último, dice qué aplica cuando se termine.
- Debajo, los lotes en el orden en que se consumen, cada uno con su número, el estado, el descuento por unidad en pesos (una compra en USD, a su propio tipo de cambio), las unidades que quedan y las usadas, la fecha desde la que cuenta y la compra (#, proveedor, facturas; el proveedor y las facturas solo con el permiso de ver compras, el mismo de **Últimas compras**). Los estados son **Vigente** (el que toma la próxima venta), **En cola**, **Agotado**, **Desde dd/mm** (cuenta desde una fecha futura) o **Reemplazado** (una carga manual reemplazó las unidades que le quedaban). Una carga manual aparece como un lote más, **Carga manual #n**, con la cantidad y el valor por unidad cargados.
- **Ver ventas** en un lote muestra las ventas que lo consumieron (canal, venta, fecha, unidades y descuento); **Ver más ventas** trae las siguientes.

**Combos:** la venta de un combo (por ejemplo una notebook con -WH) descuenta de los lotes de cada uno de sus componentes, como si se hubiera vendido cada uno por separado: la cantidad vendida por la cantidad de ese componente en el combo. El combo no usa lotes propios. La composición sale del catálogo de combos de la app; si todavía no está sincronizado, el sell in no se calcula y se reintenta solo cuando se sincroniza.

Los lotes son solo lectura. Debajo está la sección **Modo de costo**.

### Pestaña Productos

La pestaña **Productos** lista cada producto que todavía tiene unidades en lotes de sell in, con su **Modo de costo** (**FIFO (por defecto)** si nunca se cambió), las **Unidades** que le quedan en los lotes, el **Sell in por unidad** que se lleva la próxima venta (el mismo valor que muestra el visor de lotes; "—" si ningún lote cuenta todavía) y la fecha de su **Últ. compra**. Abajo está el total de unidades.

Arriba de la lista hay una barra:

- **Buscar**: filtra por código o descripción (sin importar mayúsculas ni tildes).
- **Marca**: muestra solo los productos de esa marca. Ofrece las marcas que aparecen en la lista.
- **Modo de costo**: muestra solo los productos con ese modo. **FIFO (por defecto)** son los que nunca cambiaron de modo; **FIFO** son los que alguien pasó a FIFO a propósito.
- **Limpiar filtros**: vuelve a mostrar todos los productos.
- **Modo por defecto: …** muestra con qué modo abre el selector de modo de costo (ver más abajo). Un administrador ve al lado **Cambiar**, que abre el mismo modal **Modo por defecto** que está en el panel de cada producto.

El total de unidades de abajo suma solo los productos que se ven. Si ningún producto cumple los filtros, la lista lo dice.

Tocá el título de una columna (**Producto**, **Modo de costo**, **Unidades**, **Sell in por unidad** o **Últ. compra**) para ordenar por ella; un segundo toque invierte el orden. Los productos sin **Sell in por unidad** van siempre al final.

**Ver lotes**, al final de cada fila, abre el **Costo de sell in** del producto: sus lotes y la sección **Modo de costo**, donde se cambia el modo. Al confirmar un cambio, la lista se actualiza sola.

### Modo de costo de un producto

La sección **Modo de costo**, dentro de **Lotes sell in**, muestra con qué modo descuentan hoy las unidades del producto ("Modo actual": **FIFO (por defecto)** si nunca se cambió, o el modo y desde qué fecha) y el **Historial** de cambios, el más nuevo primero, con quién lo hizo. En el panel de un producto de **Publicaciones ML** la sección empieza cerrada, en una línea con el modo actual: **Cambiar** (o **Ver**) la abre y **Ocultar** la cierra.

Para cambiarlo:

1. En **Cambiar a**, elegí **FIFO**, **Ponderado (PPP)**, **Último precio** o **Manual**.
2. En **Desde**, la fecha desde la que rige. Por defecto es hoy.
   - Con **Manual**, cargá también la **Cantidad** de unidades que quedan y su **Costo unitario** en pesos (por ejemplo, el de reposición).
3. Tocá **Ver cómo queda**. La vista previa dice cuántas ventas ya registradas cambian, la diferencia total en pesos, cuántas unidades quedan y a qué descuento por unidad, y compara el descuento de la próxima unidad y de la más nueva antes y después. Con **Último precio** el total puede no coincidir con lo que tienen los lotes: la vista previa dice cuánto queda sin asignar o cuánto se asigna de más. Con **Manual** muestra además el costo del producto que se congela y cuánto descuenta cada unidad (o cuánto suma, si el costo cargado es mayor).
4. Tocá **Confirmar cambio**, o **Cancelar** para no guardar nada. Si cambiás el modo, la fecha, la cantidad o el costo después de ver la vista previa, hay que verla de nuevo. Si el producto cambió mientras tanto (una venta o una compra nueva), el sistema pide volver a tocar **Ver cómo queda**.

**Cómo funciona Manual**: al guardar, se congela el costo actual del producto (en pesos; si está en dólares, al tipo de cambio del día). Desde la fecha elegida, la cantidad cargada **reemplaza** las unidades que les quedaban a los lotes, y cada una descuenta el costo congelado menos el costo cargado. Si el costo cargado es mayor que el congelado, en vez de descontar suma la diferencia al costo de la venta. Las compras que cuentan después de esa fecha se usan cuando se terminan las unidades manuales. Un producto sin costo cargado no puede pasar a Manual.

Permisos: **Ponderado (PPP)** necesita `sell_in.costo_ponderado`, **Último precio** `sell_in.costo_ultimo` y **Manual** `sell_in.costo_manual`; volver a **FIFO** se puede con cualquiera de los permisos de modo. Una fecha pasada necesita además `sell_in.costo_retroactivo` y recalcula las ventas registradas desde ese día. Sin ningún permiso de modo se ve el modo actual y el historial, sin poder cambiarlo.

**Modo por defecto**: **Cambiar a** abre ya elegido el modo por defecto. Si nadie lo cambió, es **FIFO**. Un administrador lo cambia con **Cambiar**, al lado de **Modo por defecto** en la barra de la pestaña **Productos**, o con el botón **Modo por defecto** de esta sección: elige **FIFO**, **Ponderado (PPP)** o **Último precio** en **Abrir en** (**Manual** no, porque necesita la cantidad y el costo de cada producto) y toca **Guardar**. El cambio vale para todos los productos. Solo elige con qué modo abre el selector: no recalcula nada, y los productos sin modo propio siguen en FIFO. Si el usuario no tiene permiso para el modo por defecto, el selector abre en **FIFO**.

### Campañas de sell out: tipos

Al crear o editar una campaña se elige el **Tipo**:

- **Por unidad**: un monto por cada unidad vendida. Puede tener **Montos por producto** y topes de unidades y de monto.
- **Porcentaje**: un porcentaje del costo o del precio neto de cada venta, con topes opcionales.
- **Monto total**: un único importe para toda la campaña, que suma una sola vez al total. No lleva topes: el monto total es el tope. Puede ser **negativo**: en ese caso descuenta de la ganancia y la lista lo muestra resaltado como **Deducción de ganancia**.

**Combos en sell out:** la venta de un combo (por ejemplo una notebook con -WH) cuenta para las campañas de **cada componente**, como si se hubiera vendido cada uno por separado: la cantidad vendida por la cantidad de ese componente en el combo, una fila por componente. En una campaña por **Porcentaje**, a cada componente le toca la parte del precio (o del costo) del combo proporcional a su costo dentro del combo; si algún componente no tiene costo cargado, el combo se reparte en partes iguales por unidad. El combo nunca cuenta como producto propio, aunque un grupo lo alcance. Lo mismo vale para los bonos de marca por % del costo de la venta.

### Reparto del monto total

Una campaña por **Monto total** muestra, al abrirla con **Ver campaña**, la sección **Reparto del monto total**. Ahí se ve cómo se reparte el monto entre los productos de la campaña. **Criterio** dice cómo se repartió:

- **Partes iguales por modelo**: el total se reparte en partes iguales entre los productos que tuvieron ventas en las fechas de la campaña; un producto sin ventas no recibe parte (lo que no vendió lo vendió otro). Mientras el rango no terminó, el reparto es **provisional**: se hace entre los que vendieron hasta hoy y la sección lo avisa. Se recalcula solo con cada venta o devolución de esas fechas, también si llega después de que termine el rango; al terminar queda entre los productos que vendieron. Si ninguno vendió, todo el monto queda **Sin asignar**.
- **Según unidades vendidas**: cada unidad vendida en las fechas de la campaña recibe la misma parte. Es dinámico: el reparto sigue las ventas y las devoluciones que van entrando en esas fechas, y nunca pasa el total.
- **Proporcional al costo**: el total se reparte según el costo de cada producto, solo entre los productos que tuvieron ventas en las fechas de la campaña. Las partes por costo que muestra la tabla se fijan al repartir y son de referencia: la de un producto sin ventas se reparte entre los que vendieron. Igual que en partes iguales, es **provisional** hasta que termina el rango y se recalcula solo con cada venta o devolución de esas fechas.
- **Manual**: quien reparte elige a qué productos y cuánto a cada uno.

Dentro de cada producto, su parte se distribuye entre sus ventas en las fechas de la campaña. Al **Renovar** una campaña repartida por criterio, la copia muestra **Reparto:** con ese criterio y se vuelve a repartir igual al guardarla; una repartida a mano copia sus partes como siempre.

- **Repartir por criterio**: quien gestiona campañas (`sell_out.gestionar`, o un administrador), sin restricción de marca, elige el criterio en **Repartir según** y toca **Ver reparto**. La vista previa muestra cada producto con sus unidades vendidas hasta hoy y su monto, y lo **Sin asignar**. **Aplicar reparto** lo guarda y reemplaza el reparto actual; **Cancelar** no guarda nada. Un PM que solo tiene `sell_out.repartir` no ve esta opción, porque el reparto por criterio alcanza a productos de todas las marcas: sigue repartiendo a mano los productos de sus marcas, salvo en una campaña ya repartida por criterio, que ve solo para consultar.

- **Quién puede repartir a mano**: el PM, sobre los productos de sus marcas, y quien gestiona campañas. Los demás ven el reparto sin poder cambiarlo. En el reparto, un PM ve solo los productos de sus marcas. Lo asignado a productos de otras marcas no se ve ni se cambia, pero se respeta al guardar y cuenta en **Asignado** y **Sin asignar**.
- **Cómo se reparte**: en **Agregar producto** se busca el producto por código o descripción. En su fila se elige **%** (un porcentaje del monto total) o **Monto fijo**, y se escribe el valor. Un monto fijo lleva el mismo signo que el total: en una deducción, también va en negativo. Un **%** siempre se escribe en positivo.
- Debajo de las filas se ven al momento lo **Asignado** y lo **Sin asignar** con los cambios, antes de guardar (marcados **aprox.** cuando incluyen productos de otras marcas que no ves). **Guardar reparto** los guarda y el criterio pasa a **Manual**. Si el reparto supera el monto total, o un monto fijo no tiene el signo del total, el panel lo dice y no guarda.

Arriba de la sección, la campaña muestra:

- **Asignado**: la suma de lo que se le dio a cada producto.
- **Asignado sin ventas**: la parte de lo asignado que fue a productos sin ventas en las fechas de la campaña.
- **Sin asignar**: lo que todavía no se le dio a ningún producto (monto total menos lo asignado, con el mismo signo).

Con **Incluye IVA** tildado, el IVA se descuenta con el IVA de cada producto en el momento en que el monto se le asigna: cada producto usa el suyo, aunque sean distintos. Por eso lo asignado a productos sin ventas ya se ve sin IVA, y lo **Sin asignar** se ve tal como se cargó, con IVA, con la aclaración **con IVA: se descuenta al asignarlo a un producto**. Sin tildar, todo se usa tal como se cargó. Al pasar el mouse sobre **Sin asignar** se ve esta regla.

Lo sin asignar (y lo asignado a productos sin ventas) no se pierde: suma en los totales de **Métricas ML** (el indicador de sell out, el total con sell in/out y una línea final del CSV) cuando el período incluye el día que termina la campaña, no en la fila de ningún producto. Con filtros (marca, categoría, producto, etc.) cuenta solo si la campaña alcanza alguno de los productos filtrados. Si el reparto guardado no se puede calcular, la sección dice por qué y no suma nada.

### Tacticals

Un **tactical** es un programa de una marca: sell in baja el costo, sell out suma a la ganancia. Cada tactical tiene una o varias marcas adjuntas para poder filtrarlo por marca, y una o más líneas (productos, una marca, una categoría o, en sell in, una factura) con su monto y sus topes.

- La pestaña **Tacticals** la ve todo el que entra a la página, salvo que el servidor todavía no tenga tacticals o que no tengas permiso para ver ninguno. Al lado del nombre dice cuántos tacticals vigentes hay.
- **Nuevo tactical** (arriba a la derecha, en la pestaña Tacticals) abre la pantalla **Nuevo tactical**, donde elegís si es sell in o sell out. Aparece si podés gestionar sell in o sell out (sell_in.gestionar o sell_out.gestionar). Al crear o cancelar volvés a la pestaña Tacticals.
- Filtros:
  - **Tipo**: Todos, Sell in o Sell out.
  - **Marca**: muestra los tacticals que tienen esa marca entre las suyas.
  - **Moneda**: ARS o USD, la moneda del tactical.
  - **Contiene**: Todas (al abrir), Productos, Marca, Categoría o Factura. Muestra los tacticals que tienen al menos una línea de ese tipo; un tactical con líneas de varios tipos aparece en cada uno.
  - **Estado**: Vigentes (al abrir), Vencidos o Anulados.
  - **Cobranza**: Todos (al abrir), Pendientes (sin cobro cargado) o Cobrados.
  - **Vigencia**: Desde y Hasta.
  - **Buscar**: por nombre o referencia.
  - **Producto**: escribí el código o parte de la descripción (sin importar mayúsculas) y muestra los tacticals con alguna línea que alcance ese producto: porque lo tiene cargado, por su **marca**, por su **categoría** o por una **factura** donde está facturado. Por ejemplo, `RE200` trae también los tacticals cargados solo por la marca TP-Link. Si el texto coincide con varios productos, trae los tacticals de cualquiera de ellos.
  - **Limpiar filtros** vuelve a los vigentes de todas las marcas, con Cobranza en Todos y sin Contiene ni Producto.
- Arriba de la lista, **Pendientes** y **Cobrados** dicen cuántos tacticals hay de cada uno y su monto por moneda: lo que generaron sus líneas (el mismo monto que muestra **Avance**) **de** su tope, por ejemplo `ARS 4.380.250 de 6.000.000`. El tope es la suma de los topes de monto de las líneas; en una línea de **Monto total**, el total es su tope. Las líneas sin tope de monto no suman al tope; si en una moneda hay líneas con y sin tope, el tope se muestra aparte, por ejemplo `ARS 900 · tope 500 (líneas con tope)`, porque lo generado incluye también las líneas sin tope. Además, **N sin tope** dice cuántos tacticals no tienen tope de monto en ninguna línea. Cuentan todos los tacticals que cumplen los otros filtros (no solo la página que estás viendo); el filtro **Cobranza** no los cambia.
- Columnas:
  - **Nombre**, con la referencia debajo.
  - **Tipo**, **Marca** (todas las del tactical, separadas por coma), **Vigencia** y **Líneas**.
  - **Avance**: unidades usadas sobre la suma de los topes de unidades de sus líneas, con la barra, y debajo el monto usado. El monto dice «de» el total solo cuando todas las líneas tienen tope de monto.
  - **Estado**: Vigente, «Vence en N días» (cuando faltan 7 días o menos), «Vence hoy» (el último día), Vencido o Anulado.
  - **Cobranza**: «Pendiente», o «Cobrado» con la fecha en que se cobró.
  - Un tactical con todas sus líneas por factura dice «Por factura» en **Vigencia** y queda Vigente hasta que se anule.
  - Un tactical con una línea por factura que todavía espera su factura dice «Esperando factura» en **Estado** hasta que Compras la vincula.
- La flecha de cada fila muestra sus líneas:
  - **Qué incluye**: los productos, o la marca, la categoría o la factura.
  - **Monto**: por unidad, porcentaje o monto total.
  - **Tope unidades**, **Usadas**, **Tope monto** y **Usado**.
  - **Avance**: la barra del tope de unidades o, si no tiene, del tope de monto. Al llegar al tope dice «Tope alcanzado».
  - **Ver ventas** abre al costado lo que cargó esa línea, solo para mirar. En una línea de sell out es su campaña, con la lista de ventas que acreditó. En sell in es su bono, con las unidades vendidas y lo aplicado, o su compra, con el costo de cada producto antes y después. Desde ahí no se edita ni se anula: eso se hace con **Editar** o **Anular** en el tactical.
- Si podés gestionar ese tipo de tactical (sell_in.gestionar o sell_out.gestionar), la columna **Cobranza** tiene **Cargar cobro** (o **Editar cobro**, si ya está cobrado). Abre debajo de la fila el cuadro **Cobranza**:
  - **Fecha de cobro**: el único dato obligatorio.
  - **Medio**: **Nota de crédito** pide el **Número de NC**; **Fondo en distribuidor** pide el **Distribuidor**; **Otro** pide un **Detalle**.
  - **Observaciones**: texto libre.
  - **Guardar** lo marca «Cobrado» con esa fecha. **Deshacer cobro** borra el cobro y el tactical vuelve a «Pendiente». **Cancelar** (o Escape) cierra sin guardar.
- Si podés gestionar ese tipo de tactical (sell_in.gestionar o sell_out.gestionar), cada fila tiene el botón de acciones (⋮) al final:
  - **Editar** (en tacticals no anulados) abre **Editar tactical**: la misma pantalla de **Nuevo tactical**, con todo cargado (tipo, datos, fechas, líneas, montos, topes y facturas). Podés cambiar cualquier cosa, también el tipo: si se cargó un sell out y era sell in, se corrige ahí. **Guardar cambios** pide confirmación: el tactical se vuelve a cargar como si lo crearas de cero y lo que ya aplicó (el cuadro dice cuánto y en cuántas unidades) se recalcula con los datos nuevos, también lo ya vendido. Si cambiás el tipo, la moneda o el tipo de cambio de un sell out con el tipo de cambio al cobro ya cargado, ese tipo de cambio se descarta y hay que cargarlo de nuevo. Una fecha hasta que no cambiás puede quedar en el pasado; si la cambiás, no puede quedar antes de hoy. Una línea de factura con monto total que no cambia conserva su compra; si su compra ya se usó en un modo de costo manual, esa línea no se puede cambiar ni quitar. El cambio queda en la auditoría.
  - En un tactical **Cobrado**, **Editar** cambia solo el nombre, la nota, la fecha hasta y los topes de cada línea (para cambiar montos o líneas, primero **Deshacer cobro**). La fecha hasta no puede quedar antes de hoy ni antes de la fecha desde, y un tope no puede quedar debajo de lo que la línea ya usó (cada línea muestra «Ya usó N u · monto»); con un tope por tienda, debajo de lo que usó la tienda o canal que más usó. Un tope vacío lo saca. Una línea de monto total no lleva topes. Un tactical por factura no tiene fecha hasta para editar, y en uno mixto la fecha hasta no mueve las líneas por factura. El cambio pasa a las campañas y bonos del tactical y queda en la auditoría.
  - **Renovar** abre **Nuevo tactical** con todo lo del tactical cargado: tipo, datos, líneas, montos y topes. Las fechas quedan vacías para que elijas las nuevas. **Crear tactical** crea un tactical NUEVO y el anterior queda como estaba. Una línea por factura vuelve sin la factura, porque esa factura ya tuvo su bono: elegí la nueva o eliminá la línea. Una línea de monto total vuelve con su criterio de reparto; en sell in en USD, con el importe en USD que se cargó (no con el total en pesos).
  - **Anular** (en tacticals no anulados) pide confirmación y dice qué se revierte. En sell out, sus campañas dejan de acreditar y se recalculan las ventas que alcanzaban. En sell in, sus bonos dejan de aplicarse y se anulan las compras que generaron: las ventas que tomaban pasan a las compras siguientes. Podés dejar un motivo, que queda en la auditoría. Anula el tactical con todas sus líneas y no se puede deshacer.

## Filtros y columnas

Los selectores de marca no ofrecen marcas sin ningún producto en stock, salvo que estén en **Admin → Marcas sin stock**. La marca ya cargada en un registro se sigue viendo al editarlo.

Tacticals: tipo, marca, moneda, contiene (tipo de línea), estado, cobranza, vigencia, búsqueda y producto; columna Cobranza (Pendiente o Cobrado con la fecha). Grupos: nombre, filtros, productos alcanzados y campañas que lo usan. Productos: búsqueda por código o descripción, marca y modo de costo; columnas producto, modo de costo, unidades, sell in por unidad y última compra, todas ordenables.

## Botones y acciones

- **Nuevo tactical** (pestaña Tacticals): abre **Nuevo tactical** (según permiso).
- **Nuevo grupo**: crea un grupo (según permiso).
- **Crear tactical**: crea el tactical con todas sus líneas; **Cancelar** lo descarta después de confirmar.
- **Editar** (acciones de una fila de Tacticals): abre **Editar tactical** con todo cargado; **Guardar cambios** lo vuelve a cargar con los datos nuevos, después de confirmar. En un tactical cobrado cambia solo nombre, nota, fecha hasta y topes.
- **Renovar** (acciones de una fila de Tacticals): abre **Nuevo tactical** cargado con ese tactical, con fechas nuevas por elegir, sus tiendas y su modo de tope.
- **Anular** (acciones de una fila de Tacticals): anula el tactical con todas sus líneas, después de confirmar.
- **Cargar cobro** / **Editar cobro** (columna Cobranza de una fila de Tacticals): abre el cuadro **Cobranza**; **Guardar** lo marca cobrado y **Deshacer cobro** lo vuelve a pendiente (según permiso).
- **Ver ventas** (en cada línea de un tactical): abre al costado lo que cargó esa línea, solo para mirar.
- **Ver lotes** (pestaña Productos, en cada fila): abre los lotes y el modo de costo del producto.
- **Cambiar** (pestaña Productos, al lado de **Modo por defecto**; solo administradores): cambia con qué modo abre el selector de modo de costo.
- **Actualizar**: recarga datos.

## Preguntas frecuentes

**¿Dónde quedaron las pestañas Sell in y Sell out?**
Todo está en **Tacticals**: elegí **Sell in** o **Sell out** en **Tipo**.

**¿Dónde quedó la pestaña Programas?**
Ya no está: el tactical es el programa de la marca, así que todo se ve en **Tacticals**. Las campañas que tenían programa no cambian: siguen acreditando igual.

**¿Por qué no veo la pestaña Grupos?**
Pide el permiso para ver grupos (grupos.ver); el de edición de constantes no alcanza. Pedíselo a un administrador.

**¿Por qué veo la pestaña Grupos pero no puedo crear, editar ni borrar?**
Eso pide además el permiso de edición de constantes (config.editar_constantes), el mismo que gestionar offsets. Pedíselo a un administrador.

**¿Por qué no puedo eliminar un grupo?**
Lo usa una campaña de sell out, un offset, o tiene consumo de offsets registrado. Si lo usa una campaña activa, el mensaje la nombra: quitá el grupo de esa campaña y volvé a intentar. Si solo lo usan campañas anuladas, el grupo queda guardado porque es parte de su historial.

**¿Qué diferencia hay entre sell in y sell out?**
Sell in baja el costo de la compra; sell out suma ganancia por campaña (o la descuenta, si es un monto total negativo).

**¿Por qué no puedo cambiar el reparto de una campaña?**
Repartir pide permiso de reparto (lo tienen los PM y los administradores) o de gestión de campañas, y la campaña tiene que estar activa. Un PM solo puede repartir productos de sus marcas.

**¿Qué monto suman Pendientes y Cobrados?**
Lo que generaron las líneas de esos tacticals, por moneda: el mismo monto de la columna **Avance**, seguido de **de** y la suma de sus topes de monto en esa moneda. Un tactical en USD puede sumar a ARS si tiene líneas de costo, que van en pesos; su tope también (un monto total de costo cargado en USD se guarda en pesos al tipo de cambio fijo). Si ninguna línea de una moneda tiene tope, esa moneda muestra solo lo generado.

**¿Un tactical anulado puede marcarse cobrado?**
Sí: la marca pudo haber pagado lo que se generó antes de anularlo. Con **Estado** en Anulados ves sus Pendientes y Cobrados.
