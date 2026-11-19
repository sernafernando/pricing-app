# Publicaciones ML: markup con sell in / sell out en todas las vistas

Área: Publicaciones ML

## Resumen ejecutivo

En **Publicaciones ML** hay dos columnas nuevas en el grupo **Markup**, en todas las vistas: **Actual c/ SISO** (el markup de hoy con el sell in y el sell out de cada publicación, el mismo que muestra el panel) y **Real 30D c/ SISO** (el markup real de las ventas de 30 días con su sell in y sell out). Ya no hace falta abrir el panel una por una para ver cuánto deja una publicación con las campañas.

## Cómo se usa

1. Abrí **Publicaciones ML** en cualquier vista: **Producto**, **Publicaciones**, **Precios**, **Agrupado** o **Auditoría de stock**.
2. Las columnas aparecen al lado de **Actual** y **Real 30D**. Hacé clic en el título para ordenar: **Actual c/ SISO** pone primero la peor.
3. En **Columnas** las podés ocultar o mover, y quedan guardadas en tus vistas.
4. **Exportar** las incluye.

## A tener en cuenta

- **Actual c/ SISO** pide el permiso para ver la ganancia. **Real 30D c/ SISO** pide además el de ver las métricas.
- Si una publicación no tiene sell in ni sell out, la columna muestra su markup sin ellos (el tooltip lo dice).
- **Pendiente** quiere decir que falta el tipo de cambio o la base de la campaña para calcularlo, como en la pestaña **Precios**.
- En **Agrupado** y en las filas de producto de **Auditoría de stock**, **Actual c/ SISO** es el rango (el más bajo y el más alto) de sus publicaciones. **Auditoría de stock** no suma un **Real 30D c/ SISO**: su **Real 30D** ya lo incluye.
- **Actual** ahora toma la promo aplicada: con una SMART, un precio negociado o un precio competitivo, suma lo que aporta Mercado Libre, igual que **Activa ahora** en la pestaña **Promos**. Antes mostraba menos markup que el panel (por ejemplo 14,67 % en lugar de 18,61 %).
- Las **PCs** cuentan como un producto propio en sell in y sell out, como en **Auditoría de stock**: una campaña, un bono o un lote de sell in que alcanza a la PC se le aplica cuando se vende, y su venta nunca cuenta además por sus componentes. Hoy no hay lotes de sell in cargados a ninguna PC: hasta que se cargue uno, una venta de PC no toma sell in.
