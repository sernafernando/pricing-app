# Métricas ML

Área: Reportes
Ruta: Reportes → Métricas ML
Permiso: Pedile a un administrador acceso a Métricas ML (ml_metricas.ver; ver ganancias pide ml_metricas.ver_ganancia).

## Para qué sirve

Es el tablero de rendimiento y rentabilidad por producto y publicación en Mercado Libre: ventas, margen, publicidad (ads), envíos, ageing y alertas. Permite agrupar por producto, publicación o agrupado, comparar con período anterior o mismo período del año pasado, y exportar.

## Cómo se usa

Arriba dice **Métricas ML** y aclara que muestra rendimiento y rentabilidad por producto y publicación en Mercado Libre Argentina. El encabezado muestra cuándo se actualizó por última vez. Los botones son **Exportar CSV**, **Exportar a Sheets** (si está habilitado) y el selector de columnas.

Debajo está la barra de filtros: rango de fechas (máx. 1 año), búsqueda por producto/SKU/MLA/marca, agrupar por (Producto/Publicación/Agrupado), comparar con (Período anterior/Mismo período año pasado), tienda, publicidad (si tenés permiso de ganancia), costos TP (si tenés permiso), solo con ventas en el período, stock, ageing, alertas (Sin ventas 30d, Ageing > 60d, Markup cayendo), producto (marca/categoría/subcategoría/PM), estado y tipo de publicación.

Las tarjetas KPI muestran los totales del conjunto filtrado. El **Sell out** del KPI también suma, una sola vez por campaña, lo que una campaña de **Monto total** no le dio a ningún producto (**Sin asignar** y **Asignado sin ventas**), en la fecha de fin de la campaña: entra cuando el período elegido incluye esa fecha, y con filtros de producto solo si la campaña alcanza alguno de los productos filtrados. Ese monto no aparece en la fila de ningún producto. El gráfico muestra ventas por día. El panel de envíos muestra métricas de envíos. Si la publicidad está activa, se muestra el bloque de ads y las no atribuidas.

La tabla lista los productos/publicaciones con sus métricas; al expandir una fila se ven sus publicaciones o el siguiente nivel (en vista agrupada). La paginación está abajo.

Si un filtro es rechazado por el tablero, aparece un aviso con el motivo.

## Filtros y columnas

Filtros: fecha, búsqueda, tienda, producto, publicación (estado/tipo), stock, ageing, alertas, solo con ventas, agrupación, dimensión (en agrupado), publicidad, costos TP, comparación.

Columnas: definidas por el selector de columnas (incluye métricas de ventas, margen, ads, etc.; las de margen solo si tenés permiso de ganancia).

## Botones y acciones

- **Exportar CSV**: descarga el tablero filtrado. Si alguna campaña de **Monto total** termina en el período, el archivo cierra con una línea **Sell out de montos totales sin producto (Sin asignar y Asignado sin ventas)** con ese monto en la columna **Sell out**.
- **Exportar a Sheets**: crea una hoja de Google Sheets (si está habilitado).
- Selector de columnas: elige qué columnas mostrar.
- **Limpiar filtros**: vuelve a los valores por defecto.
- Expandir fila: muestra publicaciones o siguiente nivel.

## Preguntas frecuentes

**¿Por qué no veo las columnas de margen/ganancia?**
Piden el permiso ml_metricas.ver_ganancia.

**¿Cuál es el período máximo?**
1 año.

**¿Qué hace "Costos TP"?**
Muestra el Total TP junto al Total Gauss; el markup usa el costo TP en las operaciones de la tienda TP-Link.

**¿Por qué el Sell out del KPI no coincide con la suma de las filas?**
Porque también suma lo que una campaña de **Monto total** dejó sin asignar a un producto, o asignó a productos sin ventas, en la fecha de fin de la campaña. Ese monto no es de ningún producto, por eso no está en las filas.
