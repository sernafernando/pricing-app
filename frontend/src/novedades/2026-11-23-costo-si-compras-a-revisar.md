# Compras con precio sospechoso: fuera del costo SI hasta que alguien las revise

Área: Sell in / Sell out, Productos

## Resumen ejecutivo

Una factura de compra con un precio por unidad que parece un error de carga ya no arrastra el costo SI. Si el precio es menor a 1/10 o mayor a 10 veces el costo SI de ese momento, la compra queda **fuera del promedio** y aparece en la pestaña nueva **Compras a revisar**. Ahí alguien con permiso la **acepta**, y entonces entra al costo, o la **mantiene excluida**.

El primer caso es la factura 00128199 del producto 23: 312 unidades a ARS 15,14 cuando el costo era de USD 13,54. Esa factura había bajado su costo SI un 21%.

## Cómo se usa

- Entrá a **Sell in / Sell out** y abrí la pestaña **Compras a revisar**. El número al lado del nombre son las compras pendientes.
- Cada fila muestra:
  - el producto y la factura;
  - el precio por unidad tal como figura en la factura, en rojo, y debajo el mismo precio convertido con el tipo de cambio de ese día;
  - la referencia: el costo SI de antes de la factura, o el costo de lista si no había costo SI;
  - cuánto se aparta el precio de la referencia, por ejemplo "1/1.395 de la referencia".
- **Aceptar**: el precio es real. La compra entra al promedio y se recalculan el costo, las ventas y los markups del producto desde esa factura.
- **Mantener excluida**: el precio es un error. El costo sigue sin esa compra.
- Las dos piden confirmar y aceptan una nota.
- Si la factura se corrige en el sistema de gestión, se vuelve a evaluar sola al día siguiente.

> Decidir pide el permiso `costo_si.revisar`. Por ahora lo tienen los administradores. Sin ese permiso, la lista se ve sin los botones.
