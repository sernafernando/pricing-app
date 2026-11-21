# Tienda

Área: Productos
Ruta: Productos → Tienda
Permiso: Pedile a un administrador acceso a Tienda.

## Para qué sirve

Sirve para gestionar los productos de la tienda propia: precios gremio, precios web/transferencia, cuotas, markups sugeridos, colores, y configurar los markups de la tienda (pestaña **⚙️ Setup Markups**, solo si tenés permiso).

## Cómo se usa

Arriba hay dos pestañas: **📦 Productos** y, si tenés permiso, **⚙️ Setup Markups**.

En **Productos** ves las tarjetas de estadísticas y el buscador **Buscar productos...**. Debajo está la barra de filtros (Stock, Precio, Marcas, Subcategorías, PM, Auditoría, Avanzados) y los botones **Limpiar**, **📊 Cuotas/Normal**, **💵 Gremio USD/💰 Gremio ARS**, **Auto-recalcular**, **Exportar**, **Calcular Web Transf.** y **Resetear Precios Gremio** (este último si tenés permiso).

La tabla se ordena haciendo clic en los encabezados. Cada fila muestra el producto y sus precios; los precios se pueden editar en línea.

## Filtros y columnas

Una marca sin ningún producto en stock no aparece en el filtro de marca, salvo que esté en **Admin → Marcas sin stock**. Si ya la tenías elegida, el filtro sigue funcionando y la marca se ve tildada.

En **⚙️ Setup Markups** tampoco aparece una marca sin stock, salvo que ya tenga un markup configurado o esté en **Admin → Marcas sin stock**.

Columnas principales: código, descripción, marca, stock, costo, precio gremio (ARS o USD según el toggle), cuotas y web/transferencia. En vista cuotas se muestran las cuotas.

La columna **Costo SI**, al lado de **Costo**, muestra el costo SI del producto en su moneda (el costo sobre el que se calculan los markups; se puede ordenar por ella). Si el producto todavía no tiene costo SI, muestra el costo de lista con **lista** al lado y más chico; sin costo, «—» (nunca 0). Con el mouse encima se ve desde cuándo rige y, si está en dólares, el costo en pesos con el tipo de cambio y su fecha. Un producto con precio pero sin costo en pesos (sin costo, o en dólares sin tipo de cambio) muestra «—» como markup debajo del precio: no se calcula, nunca un número viejo.

La columna **Costo** ocupa una sola línea: el costo en su moneda y, si el producto tiene sell in hoy, al lado y más chico **c/ sell in** con el costo que queda, en la misma moneda (con el mouse encima, el costo con sell in en pesos, el descuento por unidad y de dónde sale). Debajo del markup de **Sugerido**, **Gremio** y **Web Transf.** aparece el markup **c/ SO** si el producto tiene sell out hoy: el sell out sumado a la ganancia, sobre el **costo SI** del producto. El sell in no se resta del costo (ya está dentro del costo SI), así que no hay markup «c/ sell in» aparte. Se calcula con el neto de cada precio de Tienda, no con el de Mercado Libre: en Sugerido y Gremio, el precio sin IVA sin el % de varios; en Web Transf., el precio sin IVA menos la comisión de Tienda Nube y el % de varios. El sell out de Sugerido y Gremio sale de los tacticals que aplican a ventas por fuera, y el de Web Transf. de los que aplican a Tienda Nube; un tactical solo para tiendas oficiales de Mercado Libre no suma acá. Un sell out que es un % del precio usa el precio con IVA de esa columna.

Los precios **Gremio** y **Sugerido**, los markups de las cuotas y el markup de un precio gremio cargado a mano se calculan sobre el **costo SI** en pesos (el costo promedio con sell in; si el producto no tiene, su costo de lista). Gremio = costo SI × (1 + varios) × (1 + markup gremio); Sugerido = costo SI × (1 + varios) × (1 + markup clásica + markup sugerido). Ordenar por Gremio o Sugerido usa esos mismos precios, y **Exportar** (Lista Gremio y Lista Sugerido) da los mismos números. El precio gremio cargado a mano no cambia. Si el costo SI está en dólares y no hay tipo de cambio, o el producto no tiene costo, no hay precio Gremio ni Sugerido y esos markups quedan vacíos: nunca se calculan sobre el costo de lista ni sobre 0.

Filtros avanzados: presencia (Rebate, Mejor Oferta, Web Transferencia, Tienda Nube, Out of Cards), markup y estado. Filtro de auditoría por usuario, tipo y rango de fechas.

## Botones y acciones

- **Exportar**: exporta el listado.
- **Calcular Web Transf.**: cálculo masivo (si tenés permiso).
- **Resetear Precios Gremio**: elimina todos los precios gremio manuales (si tenés permiso).
- Editar en línea: precios gremio, cuotas, web/transferencia, markup sugerido; ✓ guarda, ✗ cancela. Con Ctrl + clic en el Gremio se carga un markup y el precio se arma sobre el costo SI; sin costo SI en pesos no se puede, cargá el precio.
- **Toggle Rebate**, **Toggle Web Transferencia**, **Toggle Out of Cards**.
- Asignar color a un producto o a varios seleccionados.
- Configurar cuotas individuales desde el ícono de configuración.
- Agregar producto a la banlist.

## Preguntas frecuentes

**¿Qué diferencia hay entre vista Normal y Cuotas?**
El botón **Normal / 📊 Cuotas** alterna las columnas de cuotas.

**¿Cómo cambio el precio gremio entre ARS y USD?**
Usá el botón **💵 Gremio USD / 💰 Gremio ARS**.

**¿Por qué el markup c/ SO de Web Transf. es distinto del de Gremio?**
Cada columna toma el sell out del canal por el que se vende ese precio (Tienda Nube para Web Transf., por fuera para Sugerido y Gremio) y, si es un % del precio, el precio de esa columna. El costo SI es el mismo en todas.

**¿Qué hace Resetear Precios Gremio?**
Elimina todos los precios gremio cargados a mano y vuelve al cálculo automático.
