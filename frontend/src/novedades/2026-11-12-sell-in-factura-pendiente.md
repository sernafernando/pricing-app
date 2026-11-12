# Sell in por factura sin esperar la factura

Área: Sell in

## Resumen ejecutivo

Una línea de sell in por factura con % o monto por unidad ya se puede cargar antes de que llegue la factura del proveedor: queda esperando y empieza a aplicar sola cuando Compras vincula la factura de esa operación.

- Al buscar facturas en la línea aparecen también las operaciones que todavía no tienen la factura vinculada, marcadas «Esperando factura».
- Mientras espera, la línea no aplica nada. En la lista de Tacticals, el estado dice «Esperando factura» y la línea lo aclara en **Qué incluye**.
- Cuando Compras vincula la factura, el reintegro queda igual que si se hubiera cargado con la factura: aplica a las unidades de esa factura hasta que se vendan, y el estado pasa a Vigente.
- Una línea con monto total todavía necesita la factura vinculada para cargarse, porque reparte el monto sobre lo facturado.

## Cómo se usa

1. En **Nuevo tactical**, elegir **Sell in** y agregar una línea con alcance **Factura**.
2. Elegir **%** o **por unidad**.
3. En **+ Factura**, elegir la operación de Compras, aunque diga «Esperando factura».
4. Tocar **Crear tactical**. Cuando Compras vincule la factura, la línea empieza a aplicar sola.
