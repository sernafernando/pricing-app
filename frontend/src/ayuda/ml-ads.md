# ML Ads

Área: Reportes
Ruta: Reportes → ML Ads
Permiso: Acceso a Métricas ML y, además, permiso para ver ganancias (ml_metricas.ver_ganancia); gestionar aportes pide ml_metricas.gestionar_aportes_ads.

## Para qué sirve

Reúne la publicidad de MercadoLibre en pestañas:

- **Aportes**: los aportes que las marcas hacen a las campañas de Product Ads. Ese monto deja de restarse en Métricas ML. Cada aporte puede ser un porcentaje o un monto fijo sobre un rango de fechas, con una forma de liquidación. Un aporte también puede ser para Display (toda la cuenta Display del anunciante o una campaña): ese monto se descuenta del Display que Métricas ML resta con "Restar toda la publicidad".
- **Display**: las campañas de Display de la cuenta, con su costo, su rendimiento y las ventas que MercadoLibre les atribuye.

Arriba dice **ML Ads** y debajo están las pestañas **Aportes** y **Display**. La pantalla abre en **Aportes**; el link a la pestaña Display la abre directo.

## Pestaña Aportes


Arriba de la pestaña dice **Aportes de marcas (Ads ML)** y aclara que lo que una marca paga de una campaña de Product Ads deja de restarse en Métricas ML.

Elegí el rango de fechas (Desde/Hasta). Se muestran tarjetas KPI: Costo Ads del período, Aporte de marcas, Costo neto y Campañas con aporte.

Debajo hay un buscador por campaña, un filtro **Todas / Con aporte / Sin aporte** y un filtro por anunciante. La tabla lista las campañas con costo del período, aporte, neto y los aportes cargados (con valor, rango y liquidación). Si tenés permiso de gestión, podés agregar, editar o borrar aportes desde cada fila.

El botón **Agregar aporte** (si tenés permiso) crea un aporte nuevo.

### Filtros y columnas

Filtros: rango de fechas, búsqueda por campaña, segmento (todas/con aporte/sin aporte), anunciante.

Columnas: Campaña, Estado, Costo del período, Aporte, Neto, Aportes cargados.

### Botones y acciones

- **Agregar aporte**: crea un aporte (si tenés permiso de gestión).
- Ícono de editar: modifica un aporte.
- Ícono de borrar: elimina un aporte (con confirmación).
- **Aporte**: agrega un aporte a una campaña.

## Pestaña Display

Elegí el rango de fechas (Desde/Hasta). Se muestran tarjetas KPI del período: **Costo** (sin IVA, como lo informa MercadoLibre), **Impresiones** (con el CPM), **Clics** (con el CTR), **Ventas atribuidas** (con las unidades) y **ROAS** (ventas atribuidas / costo).

Debajo, el gráfico **Costo diario** muestra lo gastado cada día del rango. Un día sin gasto (por ejemplo, con todas las campañas pausadas) vale cero; un día que todavía no se trajo de MercadoLibre queda como un hueco en la línea.

El buscador filtra por nombre o ID de campaña y el filtro **Todas / Activas / Pausadas** por estado; los dos filtran lo que ya está cargado.

Columnas: Campaña (con su ID), Objetivo, Estado, Desde, Hasta, Costo, Impresiones, Clics, Alcance, CTR, CPC, CPM, Ventas atribuidas, Unidades, ROAS. La fila **Total** suma las campañas visibles y recalcula CTR, CPC, CPM y ROAS sobre esas sumas.

- Un **—** en CTR, CPC, CPM o ROAS quiere decir que no hay base para calcularlo (por ejemplo, una campaña sin clics no tiene CPC). No es cero.
- El **Alcance**, como las demás cifras, es la suma del alcance de cada día: una persona alcanzada dos días (o por dos campañas) cuenta dos veces.
- Si faltan días de Display sin guardar en el rango, aparece un aviso: las cifras pueden estar incompletas. Si **Desde** queda después de **Hasta**, la pantalla pide un rango válido y no muestra cifras.

MercadoLibre conserva solo 90 días de métricas de Display; por eso se guardan a diario.

## Preguntas frecuentes

**¿Qué formas de liquidación hay?**
"Se recibe todo" (full) y "Se devuelve la diferencia" (refund_difference).

**¿Qué pasa si borro un aporte?**
El costo que cubría vuelve a descontarse en Métricas ML.

**¿Por qué veo un aviso de permiso?**
Esta pantalla pide el permiso para ver la ganancia de Métricas ML.
