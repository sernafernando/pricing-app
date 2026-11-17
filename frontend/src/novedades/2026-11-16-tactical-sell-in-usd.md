# Tacticals de sell in en USD: monto por unidad y tope en dólares

Área: Sell in / Sell out

## Resumen ejecutivo

Un tactical de sell in en USD ya no obliga a cargar el monto en pesos: una línea **por unidad** o con **Tope monto** se carga en dólares, con cualquier tipo de cambio.

- **Fijo**: cada venta se pasa a pesos al tipo de cambio cargado.
- **Día de la venta**: cada venta usa el BNA de su fecha.
- **Al cobro**: se estima con el último BNA y se recalcula solo cada día; cuando cargás el cobro con su tipo de cambio, ese queda como definitivo.
- Mientras es estimado, el sell in se marca como estimado en **Ventas ML** (≈), en **Métricas ML** (≈ n) y en la lista de tacticals (≈ en el usado de la línea, el Avance y los KPIs), como el sell out.
- El tope de monto cuenta dólares.
- El recuadro del tope bajo las tiendas ahora lista el tope de **cada línea**, no solo el de la primera.

## Cómo se usa

1. En **Nuevo tactical**, elegí sell in, moneda **USD** y el tipo de cambio.
2. Cargá las líneas **por unidad** o con **Tope monto** en dólares.
3. Con **Al cobro**, cuando la marca pague, abrí **Cargar cobro** en la lista de tacticals y completá **Tipo de cambio del cobro** (obligatorio en ese caso).
4. Las ventas de esas líneas se recalculan solas a ese tipo de cambio.
