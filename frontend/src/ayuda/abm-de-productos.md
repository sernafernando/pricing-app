# ABM de productos

Área: Productos
Ruta: Productos → ABM de productos
Permiso: Acceso a Productos para verla; editar la parte general requiere el permiso del maestro de productos (productos.editar_maestro), editar las specs el de specs (productos.editar_specs) y cambiar las unidades por caja el de Depósitos de Gestión Full.

## Para qué sirve

Es el maestro propio de productos: todos los datos de cada producto en un solo lugar, para completarlos y corregirlos sin tocar GBP. Lo que se edita acá queda en el maestro propio; GBP no se modifica. Cada dato cambiado muestra al lado el valor que tiene GBP.

Para notebooks y PCs tiene además las **Specs técnicas** (procesador, memoria, pantalla, disco, sistema operativo, placa de video y, en PCs, gabinete, fuente, mother y refrigeración), para poder filtrar por ellas.

## Cómo se usa

1. A la izquierda está la lista de productos, ordenada por stock. Arriba elegí **Todos**, **Notebooks** o **PCs** (cada uno con su cantidad), buscá por nombre, EAN o código en **Buscar** o filtrá por **Marca**. **Specs incompletas** deja solo las notebooks y PCs a las que les falta algún dato. La columna **Specs** dice cuántos campos tiene completos cada una; la barra se pone verde cuando están todos. **Ver más** trae los siguientes.
2. Tocá un producto: a la derecha se abre su ficha con el nombre y, debajo, el item, la categoría, la marca y cuántas publicaciones de Mercado Libre tiene.
3. Cambiá lo que necesites y tocá **Guardar** (dice cuántos cambios va a guardar). Se guardan juntos los cambios de **General** y de **Specs técnicas**.

### Pestaña General

- **Identidad**: **Nombre**, **EAN**, **Código del fabricante**, **Marca**, **Categoría** y **Subcategoría**. La marca y la categoría se eligen de los maestros de marcas y categorías.
- **Logística y garantía**: **Garantía** (días), **Peso** (g), **Ancho**, **Largo** y **Alto** (cm) y **Unidades por caja**.
- Cada campo dice de dónde viene: **GBP** (el valor de GBP), **Overrideado** (lo cambiaron acá y es distinto de GBP) o **Sin dato**. Un campo overrideado muestra debajo **GBP:** con el valor de GBP y **Volver al valor de GBP**, que deja de nuevo el de GBP en el momento. Si vaciás un campo y guardás, también vuelve al de GBP.
- **Unidades por caja** es el mismo dato que se carga en **Gestión Full**: cambiarlo acá lo cambia allá. Para editarlo hace falta el permiso de Depósitos de Gestión Full; sin él se ve pero no se puede cambiar.
- **Tienda Nube**: el producto de Tienda Nube vinculado, con su nombre, id, SKU, precio y si está publicado. **Automático por SKU** quiere decir que lo vinculó la sincronización por SKU; **Manual**, que alguien lo eligió acá. **Cambiar** abre un buscador con sugeridos (**Mismo EAN** primero, después **Nombre parecido**) y la búsqueda por nombre o SKU; **Vincular** lo vincula al toque. **Desvincular** lo deja sin vínculo. Un vínculo manual no lo cambia la sincronización de TN.
- **Títulos y descripciones**: **Título ML**, **Título web**, **Descripción ML** y **Descripción web**. En **Tomar de** elegís de dónde sale cada texto: la publicación ganadora de Mercado Libre, **Tienda Nube**, **GBP**, el **Nombre** del producto o **Texto propio**. Un texto tomado de otro lado lo sigue cuando cambia; si lo escribís a mano pasa a **Texto propio** y queda fijo.
- **Precio, stock y canales · solo lectura**: costo de lista, **Costo SI** (el promedio con sell in que usan los cálculos; si el producto no tiene costo SI muestra el de lista con "(de lista)", y **Sin costo** si no hay ninguno), IVA, stock, precio de lista ML, proveedor, publicaciones vinculadas y si está publicado en Tienda Nube.

### Pestaña Specs técnicas (notebooks y PCs)

- Los campos van agrupados por componente, cada grupo con cuántos tiene completos. Cada campo dice de dónde salió: **ML** (la publicación ganadora), **ERP** (el nombre del producto), **Combo** (los componentes de la PC) o **Manual** (cargado a mano). Mientras no guardes, lo que escribiste dice **Manual · sin guardar**.
- Marcá **No aplica** en un campo que no corresponde (por ejemplo, la placa de video dedicada de una notebook que no tiene): queda vacío pero cuenta como completo.
- **Precargar de nuevo** vuelve a leer el producto de Mercado Libre, del nombre del ERP y del combo. Lo cargado a mano y lo marcado como **No aplica** no se pisa.

## Preguntas frecuentes

- **¿Cambiar un dato acá lo cambia en GBP?** No. GBP no se toca: el maestro guarda su propio valor y muestra el de GBP al lado.
- **¿Por qué no puedo editar?** Ver la pantalla solo requiere acceso a Productos. Editar la parte general, las specs y las unidades por caja requiere cada uno su permiso; pedíselo a un administrador.
- **¿Dónde más está esta ficha?** En **Publicaciones ML**, en el panel de un producto, pestaña **Ficha**.
