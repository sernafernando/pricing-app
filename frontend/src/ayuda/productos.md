# Productos

Área: Productos
Ruta: ya no está en el menú; se abre escribiendo /productos en la dirección del navegador
Permiso: Pedile a un administrador acceso a Productos.

## Para qué sirve

Publicaciones ML reemplaza a esta pantalla en el menú y es la que se abre al entrar. Productos sigue funcionando igual si entrás por su dirección.


Sirve para consultar y gestionar el catálogo de productos: ver precios, stock, costos, markups, asignar colores, filtrar por marca/categoría/PM, editar precios y cuotas en línea, y lanzar acciones masivas sobre el conjunto filtrado.

## Cómo se usa

Arriba ves las tarjetas de estadísticas (por ejemplo **📦 Total Productos**, **📊 Stock & Precio**, **✨ Nuevos (7 días)**, **Sin MLA**, **💎 Oferta sin Rebate**, **📉 Markup Negativo**). Tocando una tarjeta o su sub-ítem se aplica el filtro correspondiente.

Debajo está el buscador **Buscar productos...** y la barra de filtros. Podés filtrar por **Stock** y **Precio** con los selectores compactos, y abrir paneles para **Marcas**, **Subcategorías**, **PM** y **Auditoría**. El botón **Avanzados** abre más filtros. **Limpiar** borra todos.

La tabla se puede ordenar haciendo clic en los encabezados. Cada fila se expande con la flecha para ver las publicaciones (MLAs) del producto.

El selector **Vista** cambia las columnas visibles entre **Normal**, **📊 Cuotas** y **💰 PVP**. El selector **Capa** elige la capa de color (Global o un equipo). Con **Equipos** gestionás los equipos de color.

**Exportar** está siempre disponible; **Calcular Web Transf.**, **Calcular PVP** y **Acciones masivas** aparecen según permisos. **Auto-recalcular** activa o desactiva el recálculo automático de cuotas.

## Filtros y columnas

Columnas fijas: **Código**, **Descripción**, **Marca**, **Stock**, **Costo**, y la columna de precio (en vista Normal es **Precio Clásica**; en vista Cuotas son **3 Cuotas**, **6 Cuotas**, **9 Cuotas**, **12 Cuotas**; en vista PVP son **Precio PVP** y **PVP 3/6/9/12 Cuotas**).

La columna **Costo** ocupa una sola línea: el costo en su moneda (por ejemplo `USD $17.04`) y, si el producto tiene sell in hoy, al lado y más chico **c/ sell in** con el costo que queda, en la misma moneda que el costo. Con el mouse encima se ve el PPP (o «sin PPP»), el costo con sell in en pesos, el descuento por unidad (en la moneda del costo y en pesos) y de dónde sale el sell in. El costo con sell in en dólares usa el mismo tipo de cambio con el que se pasa el costo a pesos para el markup; los markups no cambian.

En vista Normal también se ven **Precio Rebate**, **Mejor Oferta** y **Web Transf.**

Filtros avanzados (panel **Filtros Avanzados**): presencia (Rebate, Mejor Oferta, Web Transferencia, Tienda Nube, Out of Cards), markup (Clásica, Rebate, Oferta, Web Transf.), estado (MercadoLibre, Estado MLA, Promos, precios mayoristas, productos nuevos, Tienda Oficial) y marcado por color.

**Contexto de markup (tacticals)** (en **Filtros Avanzados**) elige para qué tiendas se calculan los sell out de los tacticals en las líneas bajo el costo y en el markup **c/ sell in/out**. El sell in de los tacticals no depende de la tienda: es el mismo con cualquier selección. **Todas (como hoy)** (marcado de entrada) usa todos los tacticals. Al destildarlo aparecen las tiendas oficiales; con una o varias tiendas, **Por fuera** o **Tienda Nube** tildados, entra un tactical si aplica a alguna de las elegidas. Mientras no elijas ninguna, dice «Elegí al menos una tienda o canal; mientras tanto se ve como Todas.» y se ve como **Todas**. No filtra el listado: cambia solo qué tacticals de sell out suman a esas líneas.

Filtro de auditoría (panel **Auditoría**): usuario que modificó, tipo de modificación y rango de fechas (Desde/Hasta).

## Botones y acciones

- **Limpiar**: borra todos los filtros.
- **Exportar**: abre la exportación.
- **Calcular Web Transf.**: cálculo masivo (si tenés permiso).
- **Calcular PVP**: cálculo masivo de PVP (si tenés permiso).
- **Acciones masivas**: acciones sobre el conjunto filtrado (si tenés permiso).
- **Recalcular Cuotas Web/PVP**: recalcula cuotas para todos los productos filtrados (si tenés permiso y estás en vista cuotas/pvp).
- En cada fila, el precio se puede editar en línea (✓ guarda, ✗ cancela); también se editan Rebate, Web Transferencia y cuotas.
- **Toggle Rebate ON/OFF**, **Toggle Web Transferencia ON/OFF**, **Toggle Out of Cards**.
- Cada fila tiene un botón para ver información detallada del producto y para agregarlo a la banlist.
- **Equipos**: gestiona equipos de color.

## Preguntas frecuentes

**¿Cómo cambio entre vistas?**
Usá el botón **Normal / 📊 Cuotas / 💰 PVP** o el atajo Alt+V, que va ciclando entre las tres vistas.

**¿Cómo edito un precio?**
Hacé clic sobre el precio (si tenés permiso) y escribí el nuevo valor; confirmá con Enter o con ✓, cancelá con ✗ o Esc.

**¿Qué hace "Out of Cards"?**
Marca el producto como fuera de tarjetas; se puede tildar desde la columna de Rebate.

**¿Los filtros se recuerdan?**
No se guardan al salir de la pantalla y se aplican al listado completo de productos, no solo a la página visible; podés limpiarlos con **Limpiar** o **Limpiar Todos**.

**¿Cómo sé qué lote de sell in va a aplicar en la próxima venta?**
En la información detallada del producto (pestaña **Lotes sell in**) está la sección **Lotes sell in**: los lotes en orden FIFO con su estado (Vigente, En cola, Agotado, Desde dd/mm) y qué descuenta la próxima venta según el modo de costo del producto (FIFO, ponderado o último precio); debajo, la sección **Modo de costo** para cambiarlo con su vista previa, con los permisos de modo de costo. Ver **Sell in / Sell out → Lotes de un producto** y **Modo de costo de un producto**.
