# ML Ads

Área: Reportes
Ruta: Reportes → ML Ads
Permiso: Acceso a Métricas ML y, además, permiso para ver ganancias (ml_metricas.ver_ganancia); gestionar aportes pide ml_metricas.gestionar_aportes_ads.

## Para qué sirve

Reúne la publicidad de MercadoLibre en pestañas:

- **Aportes**: los aportes que las marcas hacen a las campañas de Product Ads. Ese monto deja de restarse en Métricas ML. Cada aporte puede ser un porcentaje o un monto fijo sobre un rango de fechas, con una forma de liquidación.
- **Display**: las campañas de Display de la cuenta, con su costo, su rendimiento y las ventas que MercadoLibre les atribuye.

Arriba dice **ML Ads** y debajo están las pestañas **Aportes** y **Display**. La pantalla abre en **Aportes**; el link a la pestaña Display la abre directo.

## Pestaña Aportes


Arriba de la pestaña dice **Aportes de marcas (Ads ML)** y aclara que lo que una marca paga de una campaña de Product Ads deja de restarse en Métricas ML.

Elegí el rango de fechas (Desde/Hasta). Se muestran tarjetas KPI: Costo Ads del período, Aporte de marcas, Costo neto y Campañas con aporte.

Debajo hay un buscador por campaña, un filtro **Todas / Con aporte / Sin aporte** y un filtro por anunciante. La tabla lista las campañas con costo del período, aporte, neto y los aportes cargados. Debajo del nombre de cada campaña van su anunciante y su ID; el estado es un punto verde (**Activa**) o gris (**Pausada**). Cada aporte cargado ocupa una línea con valor, liquidación (**Todo** o **Diferencia**), rango y, si tenés permiso de gestión, editar y borrar; esas partes quedan alineadas entre filas. El botón **Aporte** de la última columna agrega un aporte a esa campaña.

El botón **Agregar aporte** (si tenés permiso) crea un aporte nuevo.

### Cargar un aporte

- **Marca**: es obligatoria y se elige de la lista de marcas, la misma que usan Productos y Sell-in. Así los totales de una marca no se parten por cómo se escribió.
- **Canal**: va después de la marca. **Product Ads** carga el aporte a una campaña de Product Ads. **Display** carga el aporte a una campaña de Display, o a **Toda la cuenta Display** del anunciante: en ese caso cubre todas sus campañas de Display en el rango.
- **Resumen de Display**: con Canal **Display**, el formulario dice cuánto gastó Display en el rango y cuánto cubre el aporte. Por ejemplo: "En el rango, Display gastó $ 1.200.000,00; este aporte cubre $ 300.000,00".
- **Al editar**: el canal y la campaña quedan fijos. Para cambiarlos, borrá el aporte y cargalo de nuevo.
- **El monto incluye IVA**: aparece con un monto fijo. Marcalo si copiaste el monto de una factura con IVA; se guarda sin IVA, que es como viene el costo de Ads.
- **Monto mayor al costo**: si un monto fijo que "Se recibe todo" supera el costo de la campaña en el rango, el neto queda negativo. Para guardarlo tenés que marcar **Confirmo que el aporte supera el costo de la campaña en el rango** (en un aporte a toda la cuenta de Display dice "de la cuenta de Display"). Si después cambiás el canal, la campaña, el tipo, el monto, si incluye IVA, las fechas o cómo se liquida, la casilla se desmarca y se vuelve a pedir.
- **Aviso de datos**: si el rango termina después del último día con datos de Ads, el formulario lo avisa. El aporte que cuenta va a cambiar cuando lleguen esos días.

### Vista Por aporte

Debajo de la descripción hay un selector **Por campaña / Por aporte**. **Por campaña** es la tabla de siempre. **Por aporte** lista cada aporte cargado del rango, de Product Ads y de Display:

- **Tarjetas**: **Aportes del período** (total, cuántas marcas y aportes), **Product Ads** y **Display** (cada uno con el porcentaje de su costo que cubren) y **Sin campaña**: el costo de Product Ads sin campaña, que ningún aporte cubre.
- **Por marca**: cuánto aportó cada marca en el rango y su parte del total, de mayor a menor. La barra violeta es una marca que solo aporta a Display.
- **Filtros**: buscador por marca o campaña, **Marca** y **Todos / Product Ads / Display**.
- **Columnas**: Marca, Canal, Campaña / Alcance (un aporte de Display a toda la cuenta dice **Toda la cuenta Display** y **Cuenta completa**), Tipo, Valor, Rango, Cubre en el período, Cargado (quién lo cargó y cuándo, y si se editó) y Acciones.
- **Acciones**: el lápiz edita el aporte, de Product Ads o de Display; el reloj abre su historial; el tacho lo borra.
- **Historial del aporte** (reloj, no hace falta permiso de gestión): cada cambio del aporte, del más viejo al más nuevo, con quién lo hizo y cuándo (hora de Argentina). **Cargado** muestra con qué se cargó; **Editado** muestra solo lo que cambió, con el valor anterior tachado. Un aporte borrado sale de la lista, así que su historial ya no se abre desde la pantalla (queda guardado quién lo borró y cuándo).
- Un aporte cargado antes de que existiera el registro de cambios muestra como **Cargado** a quien figura como su creador.

### Filtros y columnas

Filtros: rango de fechas, búsqueda por campaña, segmento (todas/con aporte/sin aporte), anunciante.

Columnas: Campaña, Estado, Costo del período, Aporte, Neto, Aportes cargados y, con permiso de gestión, una última columna con el botón **Aporte**.

**Costo del período** suma el gasto de los anuncios de la campaña, el mismo que usa Métricas ML; así el **Neto** coincide con lo que Métricas ML descuenta.

### Botones y acciones

- **Agregar aporte**: crea un aporte (si tenés permiso de gestión).
- Ícono de editar: modifica un aporte.
- Ícono de borrar: elimina un aporte (con confirmación).
- **Aporte**: agrega un aporte a una campaña.

## Pestaña Display

Arriba a la derecha elegí el rango con **Desde** y **Hasta**; al lado se ve cuántos días tiene. **Actualizar** vuelve a pedir las cifras del rango. La pestaña **Display** muestra cuántas campañas están activas (por ejemplo **4 Activas**).

Se muestran cuatro tarjetas del período:

- **Costo Display**: lo gastado, sin IVA, como lo informa MercadoLibre.
- **Ventas atribuidas**: las ventas que MercadoLibre atribuye a Display, con las unidades vendidas y la variación contra el período anterior del mismo largo (por ejemplo **+18,4 % vs per. ant.**). Si a alguno de los dos períodos le faltan días de Display sin guardar, en lugar del porcentaje dice **Sin comparación** y cuántos días faltan.
- **ROAS consolidado**: ventas atribuidas / costo.
- **Impresiones & clics**: las impresiones, con los clics, el CTR, el alcance y el CPM.

Debajo, el gráfico **Costo diario por campaña** muestra lo gastado cada día, con una barra por día dividida por campaña. La leyenda lista las campañas que gastaron en el rango, con su total. Un día sin gasto vale cero; un día que todavía no se trajo de MercadoLibre queda vacío.

En la tabla **Campañas**, el filtro **Todas / Activas / Pausadas** y el buscador por nombre o ID filtran lo que ya está cargado.

Columnas: Campaña (con su ID), Estado, Objetivo, Vigencia, Costo, Impresiones, Alcance, Clics, CTR, CPM, CPC, Ventas atrib., Unid., ROAS. La fila **Total** suma las campañas visibles, dice cuántas son y cuántas están activas y pausadas, y recalcula CTR, CPM, CPC y ROAS sobre esas sumas. Abajo dice cuántas campañas se están mostrando del total.

Con la flecha al lado del nombre se abre la **tendencia diaria** de la campaña: su costo de cada día del rango, la **inversión promedio diaria** (lo gastado dividido por los días guardados del rango) y el **retorno diario pico** (el día con mejor ROAS). Una campaña sin días en el rango dice "Sin actividad en el período".

- Un **—** en CTR, CPC, CPM o ROAS quiere decir que no hay base para calcularlo (por ejemplo, una campaña sin clics no tiene CPC). No es cero. Una campaña sin actividad muestra sus ceros reales.
- El **Alcance**, como las demás cifras, es la suma del alcance de cada día: una persona alcanzada dos días (o por dos campañas) cuenta dos veces.
- Si faltan días de Display sin guardar en el rango, aparece un aviso: las cifras pueden estar incompletas. Si **Desde** queda después de **Hasta**, la pantalla pide un rango válido y no muestra cifras.

MercadoLibre conserva solo 90 días de métricas de Display; por eso se guardan a diario.

## Preguntas frecuentes

**¿Qué formas de liquidación hay?**
"Se recibe todo" (full) y "Se devuelve la diferencia" (refund_difference).

**Cargué un monto con IVA, ¿por qué se ve otro valor?**
Si marcaste **El monto incluye IVA**, se guarda sin IVA (dividido por 1,21), igual que el costo de Ads con el que se compara.

**¿Qué pasa si borro un aporte?**
Deja de verse en la tabla y el costo que cubría vuelve a descontarse en Métricas ML. El aporte no se pierde: queda guardado como borrado, con quién lo borró y cuándo, y se puede volver a cargar el mismo rango.

**¿Por qué veo un aviso de permiso?**
Esta pantalla pide el permiso para ver la ganancia de Métricas ML.
