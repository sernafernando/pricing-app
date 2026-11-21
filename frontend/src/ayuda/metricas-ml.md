# Métricas ML

Área: Reportes
Ruta: Reportes → Métricas ML
Permiso: Pedile a un administrador acceso a Métricas ML (ml_metricas.ver; ver ganancias pide ml_metricas.ver_ganancia). Las ventas por fuera piden ventas_fuera.ver_metricas_pdf (su ganancia, ventas_fuera.ver_ganancia).

## Para qué sirve

Es el tablero de rendimiento y rentabilidad por producto y publicación en Mercado Libre: ventas, margen, publicidad (ads), envíos, ageing y alertas. Permite agrupar por producto, publicación o agrupado, comparar con período anterior o mismo período del año pasado, y exportar. Con el selector **Canal** también muestra las ventas por fuera de Mercado Libre, cargadas desde los PDF de GBP.

## Canal: ML, Por fuera y Todo

Arriba de los filtros, **Canal** elige qué ventas se ven:

- **ML**: las ventas de Mercado Libre, como siempre. Es el valor por defecto.
- **Por fuera**: las ventas por fuera de Mercado Libre, cargadas desde los PDF de GBP. Total Gauss = venta − costo (sin comisión ni envío). Ver la ayuda de **Ventas por Fuera**.
- **Todo**: las dos sumadas. Cada venta usa su regla (ML descuenta comisión y envío, por fuera no) y después se suman. Las tarjetas separan ML de Por fuera, **Ventas por día** apila los dos canales y la tabla suma la columna **Canal** (ML, Por fuera o ML + fuera).

Solo ves los canales que tu permiso deja ver. Con acceso solo a ventas por fuera, el tablero queda en **Por fuera**. **Todo** pide los dos accesos.

Con **Por fuera** o **Todo** aparecen:

- **Costo por fuera**: **Costo D** (por defecto, Precio Costo × 1,065) o **Costo** (el Precio Costo del PDF). Cambia el costo, el Total Gauss y el markup de las ventas por fuera. ML usa su costo de siempre.
- **Empresa** y **Vendedor**: filtran las ventas por fuera. En **Todo** no filtran las de ML.
- La alerta **Sin producto**: las líneas del PDF cuyo artículo no está en el catálogo. Suman a la venta, pero no tienen marca, PM ni markup.

Con **Por fuera** se ocultan Tienda ML, Publicación, Publicidad, Costos TP, Por tipo de envío y Agrupar por Publicación, porque no existen fuera de Mercado Libre. En **Todo** siguen a la vista y filtran solo las ventas de ML.

**Subir PDF de ventas** (arriba, con el permiso ventas_fuera.subir_pdf) carga un PDF nuevo, y **Cargas de PDF** muestra el historial de cargas. Ver la ayuda de **Ventas por Fuera**.

## Cómo se usa

Arriba dice **Métricas ML** y aclara que muestra rendimiento y rentabilidad por producto y publicación en Mercado Libre Argentina. El encabezado muestra cuándo se actualizó por última vez. Los botones son **Exportar CSV**, **Exportar a Sheets** (si está habilitado) y el selector de columnas.

Debajo está la barra de filtros: rango de fechas (máx. 1 año), búsqueda (título, MLA, SKU/EAN o producto, con los mismos operadores que Publicaciones ML; ver **Operadores de búsqueda** abajo), agrupar por (Producto/Publicación/Agrupado), comparar con (Período anterior/Mismo período año pasado), tienda, publicidad (si tenés permiso de ganancia), costos TP (si tenés permiso), solo con ventas en el período, stock, ageing, alertas (Sin ventas 30d, Ageing > 60d, Markup cayendo), producto (marca/categoría/subcategoría/PM), estado y tipo de publicación. Los filtros de producto funcionan como en Productos: al abrir uno, el cursor queda en la búsqueda (✕ la borra); en **Subcategoría**, tildar una categoría marca todas sus subcategorías a la vista (a medias muestra cuántas, por ejemplo 1/2), buscar el nombre de una categoría muestra todas sus subcategorías, cada subcategoría muestra su grupo de comisión (G1, G2…) y cada PM su email.

### Operadores de búsqueda

La búsqueda funciona igual que la de **Publicaciones ML**, en la computadora y en el celular. Se aplica a las filas, a las tarjetas KPI y a las opciones de los filtros, y queda en el link de la pantalla.

| Escribís | Encuentra |
|---|---|
| `MLA123456` o `mla:MLA123456` | Una publicación por su número (exacto) |
| `ean:123456` | EAN exacto |
| `codigo:ABC123` | Código exacto |
| `marca:Samsung` | Marca exacta |
| `desc:texto` o `descripcion:texto` | La descripción contiene el texto (sin guiones ni espacios) |
| `promo:DEAL` o `promo:texto` | Publicaciones con una promoción activa de ese tipo (DEAL, SMART…) o cuyo nombre contiene el texto |
| `*123` | Termina en 123 (título, descripción, marca o código) |
| `123*` | Empieza con 123 (título, descripción, marca o código) |
| `123` (solo números) | La publicación MLA123, o el SKU o código exactamente 123 |
| `texto` | Título y SKU, o descripción, marca y código (sin guiones ni espacios) |

Con `promo:` las filas suman solo las ventas de las publicaciones que hoy tienen esa promoción, en todo el período elegido.

Las tarjetas KPI muestran los totales del conjunto filtrado. El **Sell out** del KPI también suma, una sola vez por campaña, lo que una campaña de **Monto total** no le dio a ningún producto (**Sin asignar** y **Asignado sin ventas**), en la fecha de fin de la campaña: entra cuando el período elegido incluye esa fecha, y con filtros de producto solo si la campaña alcanza alguno de los productos filtrados. Un PM ve solo lo **Asignado sin ventas** de los productos de sus marcas, y lo **Sin asignar** solo si ve todos los productos que alcanza la campaña (si no, ese monto es también de otras marcas). Ese monto no aparece en la fila de ningún producto. El gráfico muestra ventas por día. El panel de envíos muestra métricas de envíos. Si la publicidad está activa, se muestra el bloque de ads y las no atribuidas.

Con publicidad restada, arriba de las tarjetas aparece **Publicidad restada**: lo que se le restó al Total Gauss y al markup, línea por línea y sin IVA. Primero los **Product Ads de publicaciones** y, sin filtros, los **Product Ads sin producto**; después, en verde, los **Aportes de marcas (Product Ads)** que las marcas nos devuelven, y el subtotal **Product Ads neto**. Sin filtros también se ven **Display** (menos sus aportes de marcas) y **Brand Ads**: con **Restar toda la publicidad** dicen **Restado** y suman al total; con **Restar Ads de publicaciones** dicen **No restado** y no suman. Abajo, **= Publicidad restada** es el total que se restó. Si parte de los Product Ads es de anuncios sin campaña, la tarjeta lo dice: ningún aporte puede cubrirlos. **Ver aportes** abre la página de aportes. En el bloque de ads, **Inversión (bruta)** es lo gastado antes de restar aportes; la columna **Publicidad restada (neta de aportes)** muestra lo que se le restó a cada fila.

**Costo y sell out (c/ SO).** El costo de cada venta es el **costo SI** vigente el día de la venta, que ya tiene descontado el sell in: por eso no hay columna de sell in ni de costo con sell in. El sell out se **suma a la ganancia**, nunca se resta del costo: si de ganancia tenés $ 1.000 y el sell out suma 10 %, tenés $ 1.100. Con permiso de ganancia, el grupo de columnas **Sell out** muestra **Costo**, **Sell out**, **Total c/ SO** (Total Gauss + sell out) y **Markup c/ SO** ((ganancia + sell out) / costo); las tarjetas **Total Gauss** y **Markup promedio** muestran debajo la línea **C/ SO**, y la tarjeta **Sell out** el sell out del período y el costo. Donde una fila no tiene sell out, esas celdas quedan vacías. Con **Costos TP** no hay Markup c/ SO (el costo es el de TP).

La tabla lista los productos/publicaciones con sus métricas; al expandir una fila se ven sus publicaciones o el siguiente nivel (en vista agrupada). Al bajar por la tabla, las cabeceras de columnas quedan fijas dentro del tablero (los filtros y los indicadores de arriba pueden ocultarse). La paginación está abajo.

Si un filtro es rechazado por el tablero, aparece un aviso con el motivo.

## En el celular

En una pantalla angosta (celular, hasta 768 px de ancho) Métricas ML tiene su propia vista, con los mismos datos y los mismos filtros que en la computadora:

- Arriba: el título, cuándo se actualizó y **⋯** con **Exportar CSV** y **Exportar a Sheets** (si está habilitado). Debajo, la búsqueda y los períodos (**Hoy**, **7d**, **Mes actual**, **30d**, **3m** y **Rango…** para elegir fechas); los períodos se deslizan de costado.
- **Filtros** abre los filtros desde abajo: Agrupar por, Tienda, Stock y ventas, Ageing y Alertas a la vista, y **Producto**, **Publicación** y **Cálculo** (Publicidad, Costos TP, Comparar con) plegados, se abren con un toque. Cada filtro se aplica al tocarlo; **Ver N productos** cierra la hoja y **Limpiar** vuelve a los valores por defecto. El número de **Filtros** dice cuántos hay activos, y debajo se ven como etiquetas.
- El botón de orden (por ejemplo **Facturado ↓**) elige por qué ordenar y en qué sentido.
- Las tarjetas KPI van de a dos por fila.
- Cada producto es una tarjeta: nombre, SKU · marca · publicaciones, **Unid. período**, **Markup** y **Facturado**, y al pie stock, ageing, última venta y la tendencia (o **Sin stock**). Al tocarla se abre con las ventas de 24H a 30D, el markup (vs anterior, mín / máx 90D, c/ SO), Total Gauss, **Costo del período** (el costo de lo vendido en el período, en pesos, como la columna Costo de la computadora; no es el costo unitario), stock, ageing y última venta; **Ver sus n publicaciones** las lista debajo y **Menos datos** la cierra.
- Se muestran 20 tarjetas; **Cargar 20 más** trae las siguientes con los mismos filtros.

## Filtros y columnas

Filtros: fecha, búsqueda, tienda, producto, publicación (estado/tipo), stock, ageing, alertas, solo con ventas, agrupación, dimensión (en agrupado), publicidad, costos TP, comparación.

En el filtro de **Marca** una marca sin ningún producto en stock solo aparece si vendió en el período y con los filtros que estás viendo, o si está en **Admin → Marcas sin stock**. Lo ya tildado sigue a la vista.

Columnas: definidas por el selector de columnas (incluye métricas de ventas, margen, ads, etc.; las de margen solo si tenés permiso de ganancia).

## Botones y acciones

- **Exportar CSV**: descarga el tablero filtrado; con permiso de ganancia trae **Sell out**, **Sell out pendientes**, **Total Gauss c/ SO** y **Markup c/ SO %** (no hay columna de sell in). Si alguna campaña de **Monto total** termina en el período, el archivo cierra con una línea **Sell out de montos totales sin producto (Sin asignar y Asignado sin ventas)** con ese monto en la columna **Sell out**.
- **Exportar a Sheets**: crea una hoja de Google Sheets (si está habilitado).
- Selector de columnas: elige qué columnas mostrar.
- **Indicadores**: elige qué tarjetas de KPI mostrar (todas visibles por defecto). Lista solo las que se ven en la pantalla; ocultar una no cambia ningún número. La elección queda guardada en este navegador.
- **Filas finas**: muestra la tabla con filas más bajas, al estilo de una planilla, para ver muchos productos a la vez. Cada fila queda en una sola línea: el nombre del producto o de la publicación y sus datos (SKU, marca, cantidad de publicaciones, tipo y estado) se cortan con "…" si no entran y se ven completos al pasar el mouse sobre ellos. Se apaga con el mismo botón y la elección queda guardada en este navegador.
- **Limpiar filtros**: vuelve a los valores por defecto.
- **Filas por página** (abajo de la tabla): 25, 50, 100, 200 o **Todos**. **Todos** muestra todas las filas del tablero en una sola página, sin tope de cantidad: las filas llegan de a 2000 a medida que se baja por el tablero (el scroll es el de la tabla, no el de toda la página), y la tabla dibuja solo las que se ven para que la pantalla no se trabe. Si una parte no llega, abajo de la tabla aparece el aviso con **Reintentar**.
- Expandir fila: muestra publicaciones o siguiente nivel. Las publicaciones de un producto salen ordenadas por tipo: primero las **Clásicas**, después las de **3 cuotas**, **6**, **9** y **12 cuotas**, y al final cualquier otro tipo. Dentro de cada tipo van de mayor a menor facturación.
- Tipo de publicación: cada publicación muestra una etiqueta con su tipo (**Clásica**, **3 cuotas**, **6 cuotas**, **9 cuotas**, **12 cuotas**). Una Clásica con cuotas cofinanciadas por Mercado Libre dice **Clásica**; al pasar el mouse se aclara. Otros tipos muestran su nombre (por ejemplo, **Gratuita**).
- Agrupar por **Publicación**: las filas arrancan ordenadas por tipo, en el mismo orden que arriba. Al hacer clic en el título de otra columna, manda esa columna. Agrupar por **Producto** sigue ordenando por facturación.

## Preguntas frecuentes

**¿Por qué no veo las columnas de margen/ganancia?**
Piden el permiso ml_metricas.ver_ganancia.

**¿Cuál es el período máximo?**
1 año.

**¿Qué hace "Costos TP"?**
Muestra el Total TP junto al Total Gauss; el markup usa el costo TP en las operaciones de la tienda TP-Link.

**¿Dónde quedó el sell in?**
Adentro del costo: el costo de cada venta es el **costo SI**, que ya tiene descontado el sell in. Por eso no se muestra aparte ni se resta otra vez. El sell out sí se ve aparte y se suma a la ganancia (**c/ SO**).

**¿Por qué el Sell out del KPI no coincide con la suma de las filas?**
Porque también suma lo que una campaña de **Monto total** dejó sin asignar a un producto, o asignó a productos sin ventas, en la fecha de fin de la campaña. Ese monto no es de ningún producto, por eso no está en las filas.

**¿De dónde sale el "Facturado ML Hoy" de la barra de arriba?**
De este tablero: es el **Facturado bruto** de hoy, sin ningún filtro elegido. Tocarlo abre Métricas ML. Lo ve quien tiene acceso a Métricas ML; si no tenés acceso o hoy todavía no hay ventas, la barra muestra el clima.
