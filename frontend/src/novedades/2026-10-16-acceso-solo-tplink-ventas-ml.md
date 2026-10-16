# Ventas ML: acceso solo a TP-Link

Área: Ventas ML

## Resumen ejecutivo

Hay un permiso nuevo, **Acceso solo TP-Link**. En **Ventas ML**, el usuario que lo tiene ve solo las ventas de la tienda **TP-Link**, calculadas con el **costo TP** (lista 8).

- **Solo ventas de TP-Link:** el listado, las tarjetas y el CSV muestran únicamente las ventas de la tienda TP-Link.
- **Costo TP, Total TP y Markup TP:** reemplazan a los valores de Gauss en la tabla, en las tarjetas, en el detalle de la venta y del pack, y en el CSV exportado.
- **Sin datos de Gauss:** no se muestra el **Total Gauss**, el markup de Gauss ni el aviso de divergencias.
- **Los datos de la venta siguen visibles:** el **Neto ML**, los cargos de Mercado Libre y el resto del detalle de cada venta se ven igual que antes.
- **Ventas sin costo TP:** si falta el costo TP de una venta, el **Total TP** muestra **—** con la palabra **incompleto**, nunca 0. La tarjeta **TP incompleto** cuenta las ventas que todavía no tienen un Total TP usable: las incompletas, las que se están recalculando y las pendientes. La tarjeta **Total TP** no suma las ventas incompletas.
- **Tema TP-Link:** este permiso también muestra la aplicación con los colores y el logo de TP-Link.
- **Es un permiso opcional:** ningún rol lo incluye y los superadministradores tampoco lo reciben automáticamente. Hay que asignarlo a mano a cada usuario.
- **Para el resto de los usuarios no cambia nada.**

## Cómo se usa

1. Ir a **Gestión → Admin** y entrar a la pestaña **Usuarios**.
2. Elegir el usuario.
3. En **Ver permisos**, elegir la vista **Por permiso**.
4. Buscar la fila **Acceso solo TP-Link** y hacer clic en **Conceder**.
5. El usuario ve el cambio al recargar la página.

> Para quitar el permiso, hacer clic en **Resetear** en la misma fila.
