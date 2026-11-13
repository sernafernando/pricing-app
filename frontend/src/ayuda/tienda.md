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

Columnas principales: código, descripción, marca, stock, costo, precio gremio (ARS o USD según el toggle), cuotas y web/transferencia. En vista cuotas se muestran las cuotas.

La columna **Costo** ocupa una sola línea: el costo en su moneda y, si el producto tiene sell in hoy, al lado y más chico **c/ sell in** con el costo que queda, en la misma moneda (con el mouse encima, el costo con sell in en pesos, el descuento por unidad y de dónde sale). Debajo del markup de **Sugerido**, **Gremio** y **Web Transf.** aparecen el markup **c/ sell in** y el markup **c/ sell in + sell out** (o **c/ sell out** si no hay sell in). Se calculan con el neto de cada precio de Tienda, no con el de Mercado Libre: en Sugerido y Gremio, el precio sin IVA sin el % de varios; en Web Transf., el precio sin IVA menos la comisión de Tienda Nube y el % de varios. El sell out de Sugerido y Gremio sale de los tacticals que aplican a ventas por fuera, y el de Web Transf. de los que aplican a Tienda Nube; un tactical solo para tiendas oficiales de Mercado Libre no suma acá. Un sell out que es un % del precio usa el precio con IVA de esa columna.

Filtros avanzados: presencia (Rebate, Mejor Oferta, Web Transferencia, Tienda Nube, Out of Cards), markup y estado. Filtro de auditoría por usuario, tipo y rango de fechas.

## Botones y acciones

- **Exportar**: exporta el listado.
- **Calcular Web Transf.**: cálculo masivo (si tenés permiso).
- **Resetear Precios Gremio**: elimina todos los precios gremio manuales (si tenés permiso).
- Editar en línea: precios gremio, cuotas, web/transferencia, markup sugerido; ✓ guarda, ✗ cancela.
- **Toggle Rebate**, **Toggle Web Transferencia**, **Toggle Out of Cards**.
- Asignar color a un producto o a varios seleccionados.
- Configurar cuotas individuales desde el ícono de configuración.
- Agregar producto a la banlist.

## Preguntas frecuentes

**¿Qué diferencia hay entre vista Normal y Cuotas?**
El botón **Normal / 📊 Cuotas** alterna las columnas de cuotas.

**¿Cómo cambio el precio gremio entre ARS y USD?**
Usá el botón **💵 Gremio USD / 💰 Gremio ARS**.

**¿Por qué el markup c/ sell in + sell out de Web Transf. es distinto del de Gremio?**
Cada columna toma el sell out del canal por el que se vende ese precio (Tienda Nube para Web Transf., por fuera para Sugerido y Gremio) y, si es un % del precio, el precio de esa columna. El sell in es el mismo en todas.

**¿Qué hace Resetear Precios Gremio?**
Elimina todos los precios gremio cargados a mano y vuelve al cálculo automático.
