# Sell in: el panel del bono muestra las facturas que no se aplicaron

Área: Productos

## Resumen ejecutivo

El panel de un bono suma el grupo **Con factura, sin aplicar**. Muestra las operaciones con productos del bono que tienen la factura del proveedor dentro del rango del bono pero todavía no generaron su sell in. Hasta ahora esas operaciones no aparecían en ningún grupo.

Cada operación dice por qué no se aplicó:

- **Error al aplicar:** el proceso automático falló al aplicarla. Se muestra el error y cuántas veces se intentó.
- **Sin líneas de la marca en la factura** (o de la categoría, o de los modelos): la factura vinculada no tiene productos del bono, aunque sí se recibieron.
- **En cola:** todavía no se procesó; se aplica en unos minutos.

## Cómo se usa

1. Abrir **Productos → Sell in**, pestaña de bonos, y hacer clic en un bono.
2. Revisar el grupo **Con factura, sin aplicar** y el motivo de cada operación.
