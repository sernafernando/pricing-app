# Sell in por factura con monto total sin esperar la factura

Área: Sell in

## Resumen ejecutivo

Una línea de sell in por factura con **monto total** ya se puede cargar antes de que llegue la factura del proveedor. Amplía «Sell in por factura sin esperar la factura», que valía solo para % o monto por unidad: ahora vale también para el monto total.

- Al cargarla, el monto queda guardado y la línea no aplica nada mientras espera. En la lista de Tacticals, el estado dice «Esperando factura».
- Cuando Compras vincula la factura, el monto se reparte sobre lo facturado igual que si se hubiera cargado con la factura, y el estado pasa a Vigente.
- Mientras espera, la línea no tiene **Ver ventas**, porque todavía no hay ventas.
- Si se anula o se edita el tactical antes de que llegue la factura, la línea que espera se anula o se cambia como cualquier otra.

## Cómo se usa

1. En **Nuevo tactical**, elegir **Sell in** y agregar una línea con alcance **Factura**.
2. Dejar **monto total** y poner el monto.
3. En **+ Factura**, elegir la operación de Compras, aunque diga «Esperando factura».
4. Tocar **Crear tactical**. Cuando Compras vincule la factura, el monto se reparte solo.
