# Métricas ML: el nuevo tablero por producto y publicación

Área: Reportes

## Resumen ejecutivo

**Métricas ML** (menú **Reportes → Métricas ML**, con la etiqueta *Nuevo*) es un tablero tipo "bolsa": muestra cómo vende y cuánto rinde cada **producto** en Mercado Libre y cuál de sus **publicaciones** funciona mejor.

El tablero anterior sigue disponible como **Métricas ML (anterior)**. Los números de ambos pueden no coincidir porque usan otra fórmula de markup.

Qué tenés que saber:

- Las ventas se cuentan en el día en que **se acreditó la plata**, igual que en Ventas ML.
- Podés ver los datos **por producto, por publicación o agrupados** por marca, categoría, subcategoría, tienda o PM.
- Los filtros se pueden usar para **mostrar** o para **ocultar** (excluir).
- Las columnas de **ganancia** (Total Gauss, markup) solo las ve quien tiene el permiso `ml_metricas.ver_ganancia`.

## Cómo se usa

1. Entrá a **Reportes → Métricas ML**. Necesitás el permiso `ml_metricas.ver`.
2. Elegí el **período** (por defecto 30 días; el máximo es un año). Con **Comparar con** elegís contra qué se mide: el período anterior o el mismo período del año pasado.
3. Elegí cómo **Agrupar por**: *Producto*, *Publicación* o *Agrupado* (ver más abajo).
4. Usá los filtros y las alertas para llegar a lo que te interesa.
5. Ordená haciendo clic en el encabezado de cualquier columna: un segundo clic invierte el orden.

## Los números del tablero

- Arriba hay **indicadores del período** con su variación contra la comparación elegida y un gráfico chico: unidades vendidas, facturado bruto, Total Gauss, markup promedio, cantidad de productos (o publicaciones) con ventas y ageing promedio.
- La tabla muestra las ventas en distintas ventanas (24H, 3D, 7D, 15D y 30D) con su tendencia, el facturado del período, la última venta, el **ageing** (días desde la última venta) y el **stock**.
- Con permiso de ganancia, también ves el markup actual, su variación contra el período anterior y su mínimo y máximo de los últimos 90 días.
- El botón de **columnas** deja ocultar las que no necesitás.

## Filtros

- **Solo con ventas en el período**: viene activado, para que un período corto muestre lo que se vendió y no todo el catálogo. Si lo desactivás ves también lo que no tuvo ventas.
- **Stock**: con stock, sin stock o sin dato (es el stock del ERP, el mismo que muestra Productos).
- **Ageing**: hasta 30 días, de 31 a 60 y más de 60.
- **Publicación**: estado (activa, pausada, cerrada) y tipo (clásica, premium, catálogo, full).
- **Tienda**: Gauss, TP-Link Oficial u otras tiendas oficiales.
- **Producto**: marca, categoría, subcategoría y PM. Los filtros se **cruzan entre sí**: si elegís una marca, las demás listas solo ofrecen lo que tiene esa marca.
- **Alertas**: *Sin ventas 30d*, *Ageing > 60d* y, para quien ve ganancia, *Markup cayendo*.

> Los chips de stock, ageing y publicación tienen tres estados: un clic los deja como **"solo estas"**, un segundo clic los pasa a **ocultar** (aparecen tachados y te dicen cuántas filas están escondiendo) y un tercero los saca.

## Vistas agrupadas y publicaciones

- En **Producto**, hacé clic en la flecha de una fila para ver **sus publicaciones** y cuál rinde mejor.
- En **Agrupado**, elegís la **dimensión**: marca, categoría, subcategoría, tienda o PM. Cada fila suma todo lo que cae en ese grupo.
- La vista agrupada es **anidada**: al abrir un grupo se abre el nivel de abajo, hasta llegar a los productos y sus publicaciones. Si un grupo tiene muchas filas, el botón **Ver más** trae las siguientes.

## Exportar

**Exportar CSV** baja lo que estás viendo, con el período, los filtros y el orden elegidos.

> Si no ves las columnas de Total Gauss y markup, es porque tu usuario no tiene el permiso `ml_metricas.ver_ganancia`. Pedíselo a un administrador si lo necesitás.
