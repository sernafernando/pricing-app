# Sell in: modo de costo manual

Área: Sell in

## Resumen ejecutivo

Ahora se puede cargar a mano la **cantidad** y el **costo unitario** del sell in de un producto, por ejemplo cuando el sell in quedó desfasado del stock actual y se quiere usar el costo de reposición.

- Al guardar se congela el costo actual del producto. Cada unidad manual descuenta ese costo menos el costo cargado.
- Si el costo cargado es mayor que el costo del producto, la diferencia se suma al costo de la venta (recargo).
- La cantidad cargada reemplaza las unidades que les quedaban a los lotes. Las compras posteriores se usan cuando se terminan las unidades manuales.
- Necesita el permiso `sell_in.costo_manual`.

## Cómo se usa

1. Abrir **Lotes sell in** de un producto e ir a **Modo de costo**.
2. En **Cambiar a**, elegir **Manual**.
3. Elegir la fecha en **Desde** y cargar **Cantidad** y **Costo unitario**.
4. Tocar **Ver cómo queda**: la vista previa muestra el costo congelado y cuánto descuenta (o suma) cada unidad.
5. Tocar **Confirmar cambio**. En la lista de lotes aparece **Carga manual #n**, y los lotes reemplazados dicen **Reemplazado**.
