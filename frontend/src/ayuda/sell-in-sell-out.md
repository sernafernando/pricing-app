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
2. **Datos del tactical**: nombre, marca (sirve para filtrar los tacticals por marca), referencia de la marca (opcional), vigencia **Desde**/**Hasta**, moneda y condiciones. Sell out arranca en USD y sell in en ARS. En USD aparece **Tipo de cambio**: **Al cobro**, **Fijo** (pide el valor) o **Día de la venta**. **Los montos incluyen IVA** y **Se acumula con otras campañas** (marcado de entrada) son las condiciones. La nota es opcional.
3. **Líneas**: cada línea tiene un alcance y un monto con sus topes.
   - Alcance: **Productos** (uno o varios: **+ Producto** abre el buscador, se tildan los que van y **Agregar a la línea**; cada uno queda como etiqueta con su cruz para quitarlo), **Marca**, **Categoría** y, solo en sell in, **Factura** (**+ Factura** busca las compras por número, proveedor o fecha; se pueden tildar varias). Una línea de factura se cobra siempre como **monto total** y el monto se reparte entre los productos de la factura según lo facturado.
   - Monto: **por unidad**, **%** o **monto total**. En sell in, **monto total** es solo para una línea de factura (en productos, marca o categoría no está disponible). Los montos se escriben como en Argentina (3,6 o 1.500).
   - **Monto total en sell out**: un importe en la moneda del tactical (USD o ARS) que se reparte entre los productos de la línea en las fechas del tactical, sin cargar el monto de cada producto. Debajo de lo que incluye la línea se elige **cómo repartirlo** (es obligatorio): **Partes iguales por modelo** (cada producto recibe la misma parte), **Según unidades vendidas** (cada unidad vendida en el rango recibe la misma parte: el reparto sigue las ventas y las devoluciones de esas fechas, y nunca pasa el total) o **Proporcional al costo** (cada producto según su costo). Una línea de monto total no lleva topes ni la pastilla **Por producto**: el total es el tope. Si falta el criterio, el aviso dice «Hay 1 línea sin reparto del monto total. Completala o eliminala.».
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

### Bonos de marca: base del bono

Al crear un bono de marca, **Base del bono** define cómo se calcula. Se elige una sola vez: después de guardarlo no se cambia.

- **Sobre facturas**: paga por las unidades facturadas de la marca, en el rango de fechas de factura del proveedor.
- **Sobre el costo de la venta**: para operaciones viejas que no tienen la factura cargada. Es siempre un porcentaje en pesos sobre el costo de cada venta, y alcanza una **Marca**, una **Categoría** o algunos **Modelos**. Las fechas **Venta desde** y **Venta hasta** son fechas de venta, no de factura.
- **Incluye IVA** (solo sobre el costo): tildado, el porcentaje cargado incluye IVA y se divide por el IVA de cada producto (por ejemplo, 3 % en un producto con IVA 10,5 % queda 2,71 %). Sin tildar, el porcentaje se usa tal cual. Esta casilla sí se puede cambiar después.

> Cuando se carga la factura de una operación, el sell in de esa factura toma sus unidades y el bono sobre el costo deja de aplicarse a ellas: no se cuenta dos veces.

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

Tocá el nombre de un producto para abrir su **Costo de sell in**: sus lotes y la sección **Modo de costo**, donde se cambia el modo. Al confirmar un cambio, la lista se actualiza sola.

### Modo de costo de un producto

La sección **Modo de costo**, dentro de **Lotes sell in**, muestra con qué modo descuentan hoy las unidades del producto ("Modo actual": **FIFO (por defecto)** si nunca se cambió, o el modo y desde qué fecha) y el **Historial** de cambios, el más nuevo primero, con quién lo hizo.

Para cambiarlo:

1. En **Cambiar a**, elegí **FIFO**, **Ponderado (PPP)**, **Último precio** o **Manual**.
2. En **Desde**, la fecha desde la que rige. Por defecto es hoy.
   - Con **Manual**, cargá también la **Cantidad** de unidades que quedan y su **Costo unitario** en pesos (por ejemplo, el de reposición).
3. Tocá **Ver cómo queda**. La vista previa dice cuántas ventas ya registradas cambian, la diferencia total en pesos, cuántas unidades quedan y a qué descuento por unidad, y compara el descuento de la próxima unidad y de la más nueva antes y después. Con **Último precio** el total puede no coincidir con lo que tienen los lotes: la vista previa dice cuánto queda sin asignar o cuánto se asigna de más. Con **Manual** muestra además el costo del producto que se congela y cuánto descuenta cada unidad (o cuánto suma, si el costo cargado es mayor).
4. Tocá **Confirmar cambio**, o **Cancelar** para no guardar nada. Si cambiás el modo, la fecha, la cantidad o el costo después de ver la vista previa, hay que verla de nuevo. Si el producto cambió mientras tanto (una venta o una compra nueva), el sistema pide volver a tocar **Ver cómo queda**.

**Cómo funciona Manual**: al guardar, se congela el costo actual del producto (en pesos; si está en dólares, al tipo de cambio del día). Desde la fecha elegida, la cantidad cargada **reemplaza** las unidades que les quedaban a los lotes, y cada una descuenta el costo congelado menos el costo cargado. Si el costo cargado es mayor que el congelado, en vez de descontar suma la diferencia al costo de la venta. Las compras que cuentan después de esa fecha se usan cuando se terminan las unidades manuales. Un producto sin costo cargado no puede pasar a Manual.

Permisos: **Ponderado (PPP)** necesita `sell_in.costo_ponderado`, **Último precio** `sell_in.costo_ultimo` y **Manual** `sell_in.costo_manual`; volver a **FIFO** se puede con cualquiera de los permisos de modo. Una fecha pasada necesita además `sell_in.costo_retroactivo` y recalcula las ventas registradas desde ese día. Sin ningún permiso de modo se ve el modo actual y el historial, sin poder cambiarlo.

**Modo por defecto**: **Cambiar a** abre ya elegido el modo por defecto. Si nadie lo cambió, es **FIFO**. Un administrador lo cambia con el botón **Modo por defecto** de la sección: elige **FIFO**, **Ponderado (PPP)** o **Último precio** en **Abrir en** (**Manual** no, porque necesita la cantidad y el costo de cada producto) y toca **Guardar**. El cambio vale para todos los productos. Solo elige con qué modo abre el selector: no recalcula nada, y los productos sin modo propio siguen en FIFO. Si el usuario no tiene permiso para el modo por defecto, el selector abre en **FIFO**.

### Campañas de sell out: tipos

Al crear o editar una campaña se elige el **Tipo**:

- **Por unidad**: un monto por cada unidad vendida. Puede tener **Montos por producto** y topes de unidades y de monto.
- **Porcentaje**: un porcentaje del costo o del precio neto de cada venta, con topes opcionales.
- **Monto total**: un único importe para toda la campaña, que suma una sola vez al total. No lleva topes: el monto total es el tope. Puede ser **negativo**: en ese caso descuenta de la ganancia y la lista lo muestra resaltado como **Deducción de ganancia**.

**Combos en sell out:** la venta de un combo (por ejemplo una notebook con -WH) cuenta para las campañas de **cada componente**, como si se hubiera vendido cada uno por separado: la cantidad vendida por la cantidad de ese componente en el combo, una fila por componente. En una campaña por **Porcentaje**, a cada componente le toca la parte del precio (o del costo) del combo proporcional a su costo dentro del combo; si algún componente no tiene costo cargado, el combo se reparte en partes iguales por unidad. El combo nunca cuenta como producto propio, aunque un grupo lo alcance. Lo mismo vale para los bonos de marca por % del costo de la venta.

### Reparto del monto total

Una campaña por **Monto total** muestra, al abrirla con **Ver campaña**, la sección **Reparto del monto total**. Ahí se ve cómo se reparte el monto entre los productos de la campaña. **Criterio** dice cómo se repartió:

- **Partes iguales por modelo**: cada producto recibe la misma parte del total.
- **Según unidades vendidas**: cada unidad vendida en las fechas de la campaña recibe la misma parte. Es dinámico: el reparto sigue las ventas y las devoluciones que van entrando en esas fechas, y nunca pasa el total.
- **Proporcional al costo**: cada producto recibe una parte según su costo.
- **Manual**: quien reparte elige a qué productos y cuánto a cada uno.

Dentro de cada producto, su parte se distribuye entre sus ventas en las fechas de la campaña. Al **Renovar** una campaña repartida por criterio, la copia muestra **Reparto:** con ese criterio y se vuelve a repartir igual al guardarla; una repartida a mano copia sus partes como siempre.

- **Repartir por criterio**: quien gestiona campañas (`sell_out.gestionar`, o un administrador), sin restricción de marca, elige el criterio en **Repartir según** y toca **Ver reparto**. La vista previa muestra cada producto con sus unidades vendidas hasta hoy y su monto, y lo **Sin asignar**. **Aplicar reparto** lo guarda y reemplaza el reparto actual; **Cancelar** no guarda nada. Un PM que solo tiene `sell_out.repartir` no ve esta opción, porque el reparto por criterio alcanza a productos de todas las marcas: sigue repartiendo a mano los productos de sus marcas.

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

Un **tactical** es un programa de una marca: sell in baja el costo, sell out suma a la ganancia. Cada tactical tiene una marca adjunta para poder filtrarlo por marca, y una o más líneas (productos, una marca, una categoría o, en sell in, una factura) con su monto y sus topes.

- La pestaña **Tacticals** la ve todo el que entra a la página, salvo que el servidor todavía no tenga tacticals o que no tengas permiso para ver ninguno. Al lado del nombre dice cuántos tacticals vigentes hay.
- **Nuevo tactical** (arriba a la derecha, en la pestaña Tacticals) abre la pantalla **Nuevo tactical**, donde elegís si es sell in o sell out. Aparece si podés gestionar sell in o sell out (sell_in.gestionar o sell_out.gestionar). Al crear o cancelar volvés a la pestaña Tacticals.
- Filtros:
  - **Tipo**: Todos, Sell in o Sell out.
  - **Marca**: la marca adjunta del tactical.
  - **Moneda**: ARS o USD, la moneda del tactical.
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
  - **Ver ventas** abre al costado lo que cargó esa línea, solo para mirar. En una línea de sell out es su campaña, con la lista de ventas que acreditó. En sell in es su bono, con las unidades vendidas y lo aplicado, o su compra, con el costo de cada producto antes y después. Desde ahí no se edita ni se anula: eso se hace con **Editar** o **Anular** en el tactical.
- Si podés gestionar ese tipo de tactical (sell_in.gestionar o sell_out.gestionar), cada fila tiene el botón de acciones (⋮) al final:
  - **Editar** (en tacticals no anulados) cambia solo el nombre, la nota, la fecha hasta y los topes de cada línea. La fecha hasta no puede quedar antes de hoy ni antes de la fecha desde, y un tope no puede quedar debajo de lo que la línea ya usó (cada línea muestra «Ya usó N u · monto»). Un tope vacío lo saca. Una línea de monto total no lleva topes. Las líneas, los montos y el alcance no se editan: para cambiarlos, anulá el tactical y renovalo. El cambio pasa a las campañas y bonos del tactical y queda en la auditoría.
  - **Renovar** abre **Nuevo tactical** con todo lo del tactical cargado: tipo, datos, líneas, montos y topes. Las fechas quedan vacías para que elijas las nuevas. **Crear tactical** crea un tactical NUEVO y el anterior queda como estaba. Una línea por factura vuelve sin la factura, porque esa factura ya tuvo su bono: elegí la nueva o eliminá la línea.
  - **Anular** (en tacticals no anulados) pide confirmación y dice qué se revierte. En sell out, sus campañas dejan de acreditar y se recalculan las ventas que alcanzaban. En sell in, sus bonos dejan de aplicarse y se anulan las compras que generaron: las ventas que tomaban pasan a las compras siguientes. Podés dejar un motivo, que queda en la auditoría. Anula el tactical con todas sus líneas y no se puede deshacer.

## Filtros y columnas

Tacticals: tipo, marca, moneda, estado, vigencia y búsqueda. Grupos: nombre, filtros, productos alcanzados y campañas que lo usan. Productos: producto, modo de costo, unidades, sell in por unidad y última compra.

## Botones y acciones

- **Nuevo tactical** (pestaña Tacticals): abre **Nuevo tactical** (según permiso).
- **Nuevo grupo**: crea un grupo (según permiso).
- **Crear tactical**: crea el tactical con todas sus líneas; **Cancelar** lo descarta después de confirmar.
- **Editar** (acciones de una fila de Tacticals): cambia nombre, nota, fecha hasta y topes; **Guardar cambios** manda solo lo que cambiaste.
- **Renovar** (acciones de una fila de Tacticals): abre **Nuevo tactical** cargado con ese tactical, con fechas nuevas por elegir.
- **Anular** (acciones de una fila de Tacticals): anula el tactical con todas sus líneas, después de confirmar.
- **Ver ventas** (en cada línea de un tactical): abre al costado lo que cargó esa línea, solo para mirar.
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
