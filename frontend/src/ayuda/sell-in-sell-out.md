# Sell in / Sell out

Área: Productos
Ruta: Productos → Sell in / Sell out
Permiso: Pedile a un administrador acceso a Sell in / Sell out (sell_in.ver; la pestaña Sell out pide además sell_out.ver, y la pestaña Grupos, grupos.ver; la pestaña Productos pide además poder ver productos (productos.ver o un permiso de edición de precios); crear, editar y borrar grupos pide además el permiso de edición de constantes: config.editar_constantes).

## Para qué sirve

Gestiona las promociones de compra (sell in) que bajan el costo de una compra, los bonos de marca y las campañas de sell out que suman ganancia por campaña. Tiene cinco pestañas: **Sell in**, **Sell out**, **Tacticals** (los programas de las marcas, filtrables por marca), **Grupos** (los grupos de productos que alcanzan las campañas) y **Productos** (el modo de costo de cada producto con lotes).

## Cómo se usa

En **Sell in** podés filtrar por fechas, búsqueda, marca, moneda (ARS/USD), estado (Activa/Anulada), **Producto**, **Proveedor** y aplicación (aplican/no aplican). También podés filtrar por tipo: **Por compra** o **Bono de marca**. La tabla muestra las compras y, debajo, los bonos de marca. Arriba hay tarjetas de resumen.

- **Producto** y **Proveedor** se buscan y se eligen de la lista de resultados; la cruz al lado del elegido lo quita. Filtran solo las compras: las que tienen ese producto en alguna línea o son de ese proveedor. **Proveedor** aparece si tenés permiso para ver proveedores u órdenes de compra (administracion.ver_proveedores, administracion.ver_ordenes_compra o administracion.gestionar_ordenes_compra).
- Los bonos de marca siguen la búsqueda (descripción o marca del bono), la marca, la moneda, el estado y las fechas. Con fechas, se ven los bonos cuyo rango de fechas se cruza con el período elegido, aunque sea un solo día. La marca muestra todos los bonos que alcanzan productos de esa marca: los de esa marca, los de una categoría con productos de esa marca, los de modelos de esa marca y los de una operación con productos de esa marca (facturados o recibidos). Un bono de operación que todavía no tiene productos facturados ni recibidos no se puede ubicar en una marca: aparece con cualquier marca elegida. Aplicación, Producto y Proveedor no filtran los bonos: un bono no tiene "aplica" y alcanza una marca, una categoría, modelos o una operación, no un proveedor.
- Las tarjetas de bonos vigentes cuentan siempre todos los bonos activos, con cualquier filtro.

Los sell in nuevos se cargan desde la pestaña **Tacticals**, con **Nuevo tactical** (ver más abajo). Al tocar una fila se abre el panel lateral con el detalle.

En **Sell out** se listan las campañas, con paginación. Se filtran por período (las campañas cuyas fechas tocan el período elegido; **Todas las fechas** lo quita), por nombre, por estado (Activa/Anulada), por tipo (Por unidad, Porcentaje, Monto total), por moneda (ARS/USD), por marca (las campañas que alcanzan algún producto de esa marca a través de sus grupos) y, si tenés permiso de gestión de campañas, por grupo. Las campañas nuevas se cargan desde la pestaña **Tacticals**, con **Nuevo tactical**.

Para anular varias campañas de una vez (pide permiso de gestión de campañas, sell_out.gestionar): marcá la casilla de cada fila, la casilla del encabezado para toda la página, o **Seleccionar todo lo filtrado (N)** para todas las que coinciden con los filtros. La barra muestra cuántas hay seleccionadas; **Anular seleccionadas** pide confirmación, dice cuántas se anulan y permite un motivo. El sell out que acreditaron deja de contar: se borran sus consumos y se recalculan las ventas que alcanzaban. Es todo o nada: si alguna no se puede anular, no se anula ninguna y el mensaje dice cuál y por qué. Si una se está recalculando, el mensaje la nombra y se puede reintentar en unos segundos. Las que ya estaban anuladas se omiten y el resultado las cuenta aparte. Se pueden anular hasta 500 por vez. Con algo seleccionado aparece una barra flotante abajo y al centro de la ventana, con **N seleccionadas**, **Asignar a programa**, **Anular seleccionadas** y **×** para limpiar la selección; queda a mano mientras bajás por la lista.

El botón **Actualizar** recarga todo.

### Nuevo tactical

Un tactical es un acuerdo con una marca: sus datos y todas sus líneas se cargan en una sola pantalla y se crean juntos con **Crear tactical**.

1. **Tipo**: **Sell out** (la marca te paga por cada unidad vendida en el rango) o **Sell in** (baja el costo de lo que vendés en el rango). Solo se puede elegir el tipo que tu permiso deja gestionar.
2. **Datos del tactical**: nombre, marca (sirve para filtrar los tacticals por marca), referencia de la marca (opcional), vigencia **Desde**/**Hasta**, moneda y condiciones. Sell out arranca en USD y sell in en ARS. En USD aparece **Tipo de cambio**: **Al cobro**, **Fijo** (pide el valor) o **Día de la venta**. **Los montos incluyen IVA** y **Se acumula con otras campañas** (marcado de entrada) son las condiciones. La nota es opcional.
3. **Líneas**: cada línea tiene un alcance y un monto con sus topes.
   - Alcance: **Productos** (uno o varios: **+ Producto** abre el buscador, se tildan los que van y **Agregar a la línea**; cada uno queda como etiqueta con su cruz para quitarlo), **Marca**, **Categoría** y, solo en sell in, **Factura** (**+ Factura** busca las compras por número, proveedor o fecha; se pueden tildar varias). Una línea de factura se cobra siempre como **monto total** y el monto se reparte entre los productos de la factura según lo facturado.
   - Monto: **por unidad** o **%**; en sell in, una línea de factura también puede ser **monto total** (en productos, marca o categoría no está disponible). Los montos se escriben como en Argentina (3,6 o 1.500).
   - Topes: **Tope unidades** y **Tope monto**; corta el que se alcance primero. Con varios productos, la pastilla **Por producto** (cada producto con sus topes) se puede cambiar a **Compartido** (un solo tope para todos).
   - **Máximo a cobrar** es lo más que puede dar la línea: el monto total; con %, el tope de monto; por unidad, monto × tope de unidades (por cada producto si los topes son por producto), sin pasar el tope de monto.
   - Cada línea se puede **duplicar** o **eliminar**. **+ Agregar línea** suma una y abre el buscador de productos.
4. La barra de abajo resume: en sell out, líneas, productos, tope total de unidades y máximo a cobrar; en sell in, líneas, marca y vigencia.

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

### Lotes de un producto

Cada venta toma las unidades del lote más viejo que todavía tiene (orden FIFO). Lo que descuenta por unidad depende del modo de costo del producto: por defecto es FIFO, y cada unidad descuenta el valor de su lote; con **ponderado** todas las unidades que quedan descuentan el promedio ponderado de los lotes, y con **último precio** descuentan el valor del lote más nuevo. El modo cambia el valor, nunca el orden en que se usan las unidades. Para ver cómo van a aplicar los lotes de un producto, abrí la sección **Lotes sell in** en el panel del producto de **Publicaciones ML** (pestaña Resumen) o en la ficha de información del producto de **Productos** (pestaña **Lotes sell in**).

- Arriba dice qué descuenta la próxima venta, por ejemplo: "La próxima venta descuenta $ 33,33 por unidad (lote 2); quedan 2 unidades a ese valor, después $ 10,00". Si ningún lote tiene unidades hoy, dice que el costo vuelve al normal (y hasta cuándo, si queda un lote con fecha futura) y si aplica un bono de costo en su lugar; si el lote vigente es el último, dice qué aplica cuando se termine.
- Debajo, los lotes en el orden en que se consumen, cada uno con su número, el estado, el descuento por unidad en pesos (una compra en USD, a su propio tipo de cambio), las unidades que quedan y las usadas, la fecha desde la que cuenta y la compra (#, proveedor, facturas; el proveedor y las facturas solo con el permiso de ver compras, el mismo de **Últimas compras**). Los estados son **Vigente** (el que toma la próxima venta), **En cola**, **Agotado** o **Desde dd/mm** (cuenta desde una fecha futura).
- **Ver ventas** en un lote muestra las ventas que lo consumieron (canal, venta, fecha, unidades y descuento); **Ver más ventas** trae las siguientes.

**Combos:** la venta de un combo (por ejemplo una notebook con -WH) descuenta de los lotes de cada uno de sus componentes, como si se hubiera vendido cada uno por separado: la cantidad vendida por la cantidad de ese componente en el combo. El combo no usa lotes propios. La composición sale del catálogo de combos de la app; si todavía no está sincronizado, el sell in no se calcula y se reintenta solo cuando se sincroniza.

Los lotes son solo lectura. Debajo está la sección **Modo de costo**.

### Pestaña Productos

La pestaña **Productos** lista cada producto que todavía tiene unidades en lotes de sell in, con su **Modo de costo** (**FIFO (por defecto)** si nunca se cambió), las **Unidades** que le quedan en los lotes, el **Sell in por unidad** que se lleva la próxima venta (el mismo valor que muestra el visor de lotes; "—" si ningún lote cuenta todavía) y la fecha de su **Últ. compra**. Abajo está el total de unidades.

Tocá el nombre de un producto para abrir su **Costo de sell in**: sus lotes y la sección **Modo de costo**, donde se cambia el modo. Al confirmar un cambio, la lista se actualiza sola.

### Modo de costo de un producto

La sección **Modo de costo**, dentro de **Lotes sell in**, muestra con qué modo descuentan hoy las unidades del producto ("Modo actual": **FIFO (por defecto)** si nunca se cambió, o el modo y desde qué fecha) y el **Historial** de cambios, el más nuevo primero, con quién lo hizo.

Para cambiarlo:

1. En **Cambiar a**, elegí **FIFO**, **Ponderado (PPP)** o **Último precio**. **Manual** (cargar cantidad y costo a mano) todavía no está disponible.
2. En **Desde**, la fecha desde la que rige. Por defecto es hoy.
3. Tocá **Ver cómo queda**. La vista previa dice cuántas ventas ya registradas cambian, la diferencia total en pesos, cuántas unidades quedan y a qué descuento por unidad, y compara el descuento de la próxima unidad y de la más nueva antes y después. Con **Último precio** el total puede no coincidir con lo que tienen los lotes: la vista previa dice cuánto queda sin asignar o cuánto se asigna de más.
4. Tocá **Confirmar cambio**, o **Cancelar** para no guardar nada. Si cambiás el modo o la fecha después de ver la vista previa, hay que verla de nuevo. Si el producto cambió mientras tanto (una venta o una compra nueva), el sistema pide volver a tocar **Ver cómo queda**.

Permisos: **Ponderado (PPP)** necesita `sell_in.costo_ponderado` y **Último precio** `sell_in.costo_ultimo`; volver a **FIFO** se puede con cualquiera de los permisos de modo. Una fecha pasada necesita además `sell_in.costo_retroactivo` y recalcula las ventas registradas desde ese día. Sin ningún permiso de modo se ve el modo actual y el historial, sin poder cambiarlo.

**Modo por defecto**: **Cambiar a** abre ya elegido el modo por defecto. Si nadie lo cambió, es **FIFO**. Un administrador lo cambia con el botón **Modo por defecto** de la sección: elige **FIFO**, **Ponderado (PPP)** o **Último precio** en **Abrir en** y toca **Guardar**. El cambio vale para todos los productos. Solo elige con qué modo abre el selector: no recalcula nada, y los productos sin modo propio siguen en FIFO. Si el usuario no tiene permiso para el modo por defecto, el selector abre en **FIFO**.

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

### Renovar una campaña

Para el próximo trimestre no hace falta cargar la campaña de cero. Quien gestiona campañas tiene el botón **Renovar** en cada fila de la lista (también en la vista **Por programa**) y en **Ver campaña**, en campañas activas y también en anuladas. Abre el formulario de una **campaña nueva** con todo copiado y el aviso «Copia de «nombre». Revisá fechas y montos antes de guardar.». No se guarda nada hasta tocar **Guardar campaña**; **Cancelar** vuelve a la campaña original.

- **Se copia**: el tipo y su monto (por unidad, porcentaje o monto total), la base del porcentaje, la moneda, el modo de tipo de cambio (el valor solo si es **Fijo**), los topes, **Acumulable**, **El monto incluye IVA**, la descripción, los grupos, los **Montos por producto**, y el **Reparto del monto total** (se guarda junto con la campaña; **No copiar el reparto** lo deja afuera, por ejemplo si cambiaste los grupos o bajaste el total, y se carga después desde la campaña guardada).
- **No se copia**: el estado, lo que acreditó, el tipo de cambio **Al cobro** que se definió al cobrar, el offset de origen ni el historial de cambios. Tampoco los productos que ya no están en los grupos.
- **Fechas**: por defecto, el trimestre calendario siguiente al que contiene la fecha hasta de la original (por ejemplo, una que termina el 15/11/2026 o el 31/12/2026 propone del 01/01/2027 al 31/03/2027). Se pueden cambiar.
- **Nombre**: si termina en un período, se avanza al nuevo trimestre («Rebate Q4 2026» → «Rebate Q1 2027», «Rebate 4Q26» → «Rebate 1Q27», «Campaña noviembre 2026» → «Campaña enero 2027»). Si no, queda igual (por ejemplo «Promo modelo 3.0»). Se puede editar.

- **Programa**: la copia queda en el mismo programa que la original mientras ese programa esté activo. Si está archivado, la copia queda sin programa.

La campaña original no cambia: sigue como estaba, con su historial y lo que acreditó.

### Programas

Un **programa** agrupa campañas de sell out que son el mismo acuerdo: las que se renuevan cada trimestre o las que se cargaron con el mismo nombre y un número porque aplican a cosas distintas. Asignar un programa **no cambia la plata** de las campañas: lo que acreditan, sus topes y la ganancia siguen igual. Solo las agrupa.

**Programa es el nivel superior.** Agrupa una campaña y sus repeticiones a lo largo de los quarters, y dura en el tiempo: por ejemplo, «EPSON PROG» junta todas sus campañas de cada trimestre. Cada **campaña** es el monto de un período sobre un alcance (productos, grupos). **Renovar** crea la campaña del quarter siguiente y la deja en el mismo programa.

- **Sección: Campañas | Programas** (arriba de la pestaña **Sell out**): **Campañas** es la lista de campañas; **Programas** es la vista para crear y ordenar los programas. La sección elegida queda en la dirección de la página.
- **Programas** muestra una fila por programa con **Campañas**, **Activas**, **Nombres distintos**, **Vigencia** (de la primera fecha de inicio a la última de fin de sus campañas, o «Sin campañas») y **Estado**. Se filtra por **Activos**, **Archivados** o **Todos**, y se busca por nombre.
- Tocar la flecha de un programa lista sus campañas. **Ver en Campañas** abre la lista de campañas con el filtro Programa puesto en ese programa.
- Quien gestiona campañas también puede:
  - **Nuevo programa**: nombre (no puede repetirse) y descripción opcional. Se crea vacío; las campañas se suman con **Asignar a programa**, con las sugerencias o moviéndolas desde otro programa.
  - **Editar**: cambiar el nombre o la descripción. Solo se guarda lo que cambiaste.
  - **Archivar** / **Reactivar**: un programa archivado no recibe campañas nuevas y una renovación de sus campañas queda sin programa. Sus campañas no cambian.
  - En un programa abierto, marcar campañas y tocar **Quitar del programa** (quedan sin programa) o **Mover a otro programa** (el mismo cuadro de **Asignar a programa**).
  - **Renovar programa** (solo en programas activos): crea de una vez la campaña del trimestre siguiente de cada campaña del último período del programa, con las mismas reglas que **Renovar** en una campaña (lo que se copia, las fechas y el nombre) y en el mismo programa. Antes de crear nada muestra:
    - el período que se renueva y el trimestre nuevo (por ejemplo, **Oct–Dic 2026** → **Ene–Mar 2027**, con sus fechas);
    - **Se crearán N**: cada campaña con su nombre actual → el nombre nuevo, las fechas nuevas y el **ID #** de la campaña original;
    - **Se omiten N**: las anuladas («anulada, no se renueva») y las que ya tienen su copia («ya renovada en la campaña N (nombre)»). Una campaña renovada a mano con **Renovar** también cuenta, aunque después le hayas cambiado el nombre. Una copia anulada no cuenta: esa campaña se vuelve a renovar;
    - en amarillo, las campañas del otro trimestre que quedan sin renovar en esta pasada. Pasa cuando se renovaron algunas a mano: primero se termina el período más viejo, y las otras se renuevan la próxima vez.
  - **Renovar N campañas** crea todas o ninguna. Si mientras mirabas la vista previa alguien renovó o anuló una de esas campañas, no se crea nada, aparece el aviso y la vista previa se vuelve a leer. Un programa sin campañas para renovar lo dice y no deja confirmar. Se renuevan hasta 500 campañas por vez. Las campañas nuevas se pueden editar después, como cualquier otra.

- **Ver: Por programa | Lista** (en la tarjeta de filtros, cuando hay programas): **Por programa** muestra una fila por programa con «N campañas · M nombres · desde – hasta» y cuántas están activas, y al final **Sin programa**. Tocar la fila la abre y lista sus campañas, con las mismas columnas, casillas, **Ver campaña** y **Renovar** que la lista. **Lista** es la lista de siempre. La vista elegida queda en la dirección de la página. Si hay al menos un programa, se abre en **Por programa**. Quien gestiona campañas tiene **Asignar ahora** en la fila **Sin programa**: abre **Asignar a programa** con todas las campañas sin programa que coinciden con los filtros. Si la lista cambió mientras se leían, lo avisa y no abre nada.
- Los grupos siguen los filtros: los números de cada fila y las campañas que muestra son los que cumplen los filtros, y un programa sin campañas que los cumplan no aparece.
- **ID de la campaña**: al lado del nombre de cada campaña figura «ID #n», el número para buscarla o nombrarla.
- **Filtro Programa**: **Todos**, **Sin programa** o un programa. También vale para **Seleccionar todo lo filtrado**.
- **Asignar a programa** (quien gestiona campañas): marcá campañas, o usá **Seleccionar todo lo filtrado**, y tocá **Asignar a programa** en la barra de selección. Elegí un **Programa existente** (solo los activos) o un **Programa nuevo** con nombre y descripción opcional, que se crea y se asigna en el mismo paso. Si el programa está archivado o el nombre ya existe, el aviso aparece en el mismo cuadro y no se asigna nada. Al terminar se muestra, por ejemplo, «3 campañas asignadas a «Programa». 1 ya lo tenía.».
- **Sugerencias de programa** (quien gestiona campañas): cuando hay campañas sin programa con **exactamente las mismas fechas**, arriba de la lista aparece «N sugerencias de programa: campañas sin programa con las mismas fechas». **Ver sugerencias** abre un panel con una tarjeta por grupo: un nombre propuesto (las palabras con que empiezan todos los nombres, o las fechas si no comparten ninguna), que se puede editar, sus fechas, cuántas campañas y nombres tiene, y la lista de campañas. **Crear programa y asignar** crea el programa y le asigna esas campañas. **Descartar** oculta la tarjeta hasta que vuelvas a abrir la página; no se guarda nada. No se aplica nada hasta que lo confirmes.

### Tacticals

Un **tactical** es un programa de una marca: sell in baja el costo, sell out suma a la ganancia. Cada tactical tiene una marca adjunta para poder filtrarlo por marca, y una o más líneas (productos, una marca, una categoría o, en sell in, una factura) con su monto y sus topes.

- La pestaña **Tacticals** la ve todo el que entra a la página, salvo que el servidor todavía no tenga tacticals o que no tengas permiso para ver ninguno. Al lado del nombre dice cuántos tacticals vigentes hay.
- **Nuevo tactical** (arriba a la derecha, en la pestaña Tacticals) abre la pantalla **Nuevo tactical**, donde elegís si es sell in o sell out. Aparece si podés gestionar sell in o sell out (sell_in.gestionar o sell_out.gestionar). Al crear o cancelar volvés a la pestaña Tacticals.
- Filtros:
  - **Tipo**: Todos, Sell in o Sell out.
  - **Marca**: la marca adjunta del tactical.
  - **Estado**: Vigentes (al abrir), Vencidos o Anulados.
  - **Vigencia**: Desde y Hasta.
  - **Buscar**: por nombre o referencia.
  - **Limpiar filtros** vuelve a los vigentes de todas las marcas.
- Columnas:
  - **Nombre**, con la referencia debajo.
  - **Tipo**, **Marca**, **Vigencia** y **Líneas**.
  - **Avance**: unidades usadas sobre la suma de los topes de unidades de sus líneas, con la barra, y debajo el monto usado. El monto dice «de» el total solo cuando todas las líneas tienen tope de monto.
  - **Estado**: Vigente, «Vence en N días» (cuando faltan 7 días o menos), «Vence hoy» (el último día), Vencido o Anulado.
- La flecha de cada fila muestra sus líneas:
  - **Qué incluye**: los productos, o la marca, la categoría o la factura.
  - **Monto**: por unidad, porcentaje o monto total.
  - **Tope unidades**, **Usadas**, **Tope monto** y **Usado**.
  - **Avance**: la barra del tope de unidades o, si no tiene, del tope de monto. Al llegar al tope dice «Tope alcanzado».
- Si podés gestionar ese tipo de tactical (sell_in.gestionar o sell_out.gestionar), cada fila tiene el botón de acciones (⋮) al final:
  - **Editar** (en tacticals no anulados) cambia solo el nombre, la nota, la fecha hasta y los topes de cada línea. La fecha hasta no puede quedar antes de hoy ni antes de la fecha desde, y un tope no puede quedar debajo de lo que la línea ya usó (cada línea muestra «Ya usó N u · monto»). Un tope vacío lo saca. Una línea de monto total no lleva topes. Las líneas, los montos y el alcance no se editan: para cambiarlos, anulá el tactical y renovalo. El cambio pasa a las campañas y bonos del tactical y queda en la auditoría.
  - **Renovar** abre **Nuevo tactical** con todo lo del tactical cargado: tipo, datos, líneas, montos y topes. Las fechas quedan vacías para que elijas las nuevas. **Crear tactical** crea un tactical NUEVO y el anterior queda como estaba. Una línea por factura vuelve sin la factura, porque esa factura ya tuvo su bono: elegí la nueva o eliminá la línea.
  - **Anular** (en tacticals no anulados) pide confirmación y dice qué se revierte. En sell out, sus campañas dejan de acreditar y se recalculan las ventas que alcanzaban. En sell in, sus bonos dejan de aplicarse y se anulan las compras que generaron: las ventas que tomaban pasan a las compras siguientes. Podés dejar un motivo, que queda en la auditoría. Anula el tactical con todas sus líneas y no se puede deshacer.

## Filtros y columnas

Sell in: fechas, búsqueda, marca, moneda, estado, producto, proveedor, aplicación, tipo (los bonos de marca siguen fechas, búsqueda, marca, moneda y estado). Sell out: período, nombre, estado, tipo, moneda, marca, grupo y programa. Tacticals: tipo, marca, estado, vigencia y búsqueda. Grupos: nombre, filtros, productos alcanzados y campañas que lo usan. Productos: producto, modo de costo, unidades, sell in por unidad y última compra.

## Botones y acciones

- **Nuevo tactical** (pestaña Tacticals): abre **Nuevo tactical** (según permiso).
- **Nuevo grupo**: crea un grupo (según permiso).
- **Crear tactical**: crea el tactical con todas sus líneas; **Cancelar** lo descarta después de confirmar.
- **Editar** (acciones de una fila de Tacticals): cambia nombre, nota, fecha hasta y topes; **Guardar cambios** manda solo lo que cambiaste.
- **Renovar** (acciones de una fila de Tacticals): abre **Nuevo tactical** cargado con ese tactical, con fechas nuevas por elegir.
- **Anular** (acciones de una fila de Tacticals): anula el tactical con todas sus líneas, después de confirmar.
- Tocar una fila: abre el panel lateral de detalle.
- **Actualizar**: recarga datos.

## Preguntas frecuentes

**¿Por qué no veo la pestaña Sell out?**
Pide un permiso adicional (sell_out.ver). Pedíselo a un administrador.

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

**¿Por qué "Seleccionar todo lo filtrado" dice que la lista cambió?**
Antes de anular, la pantalla trae todas las campañas de la búsqueda y las cuenta. Si no coinciden con el total de la lista (por ejemplo, alguien cargó o anuló una campaña en ese momento), no selecciona nada para no anular de más ni de menos. Tocá **Actualizar** y volvé a intentar.
