# Costo SI en la auditoría de stock, el ranking y la ficha del producto

Área: Productos

## Resumen ejecutivo

La **Auditoría de stock** de Publicaciones ML y el **Ranking de productos** ahora valúan el stock al **costo SI** (promedio ponderado con los sell in de las facturas de compra) en lugar del costo de lista. La **ficha del producto** muestra el **Costo SI** al lado del costo de lista. En **Notificaciones** y en la **Rentabilidad** de Ventas por fuera y Tienda Nube, un costo desconocido dice **Sin costo** en vez de "N/A" o $0.

## Cómo se usa

No hay que hacer nada: las pantallas toman el costo nuevo solas.

## A tener en cuenta

- Un producto sin costo SI usa su costo de lista; en la ficha se marca "(de lista)".
- Un producto con stock y sin ningún costo conocido no suma a los totales: el ranking avisa "N productos sin costo" y la auditoría lo cuenta aparte.
- En Rentabilidad, las ventas sin costo suman al monto vendido pero no al costo, la ganancia ni el markup; la tarjeta avisa cuántas son.
- Un combo vale la suma de sus componentes por la cantidad de cada uno.
- Ningún precio cambia.
