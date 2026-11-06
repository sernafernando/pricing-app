# Tacticals y bonos de sell in: monto total repartido entre los productos

Área: Sell in

## Resumen ejecutivo

Ahora una línea de un tactical de sell in sobre productos, una marca o una categoría puede ser un **monto total** (por ejemplo, $ 1.200.000 para varios modelos de notebook) que baja el costo de las ventas y se reparte solo entre los productos de la línea en las fechas del tactical. Ya no hace falta pasarlo a un monto por unidad.

- Se elige cómo repartirlo, igual que en sell out: **Partes iguales por modelo**, **Según unidades vendidas** o **Proporcional al costo**.
- El total queda en pesos (ARS), porque el costo de cada venta está en pesos. En un tactical en USD se puede usar con **Tipo de cambio** **Fijo**: el importe se pasa a pesos a ese tipo de cambio.
- El total tiene que ser mayor que cero: en sell in no se descuenta un monto negativo.
- Una línea por factura sigue igual que antes: su monto total se reparte según lo facturado.
- Un bono de marca **Sobre el costo de la venta** también puede ser **Monto total**, y su panel muestra cuánto le tocó a cada producto.
- El reparto por criterio es para quien gestiona sell in (`sell_in.gestionar`) o un administrador, sin restricción de marca.

## Cómo se usa

1. En **Nuevo tactical**, elegir **Sell in** y cargar la línea con sus productos, una marca o una categoría.
2. En el monto de la línea, tocar **monto total** y escribir el importe.
3. Debajo de lo que incluye la línea, elegir cómo repartirlo. La línea no lleva topes: el total es el tope.
4. Tocar **Crear tactical**.

En un bono de marca:

- Elegir **Sobre el costo de la venta** y, en **Forma del monto**, **Monto total**.
- Escribir el **Monto total (ARS)** y elegir **Repartir el monto total**.
- Al abrir el bono, **Reparto del monto total** muestra la parte de cada producto. Con **Según unidades vendidas**, el total sigue las unidades vendidas en las fechas del bono.
