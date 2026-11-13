# Actualizar OC: ítems reemplazados y procesado GBP

Área: Compras

## Resumen ejecutivo

**Actualizar OC** ahora refleja mejor el ERP: saca del espejo las líneas cuyo `pod_id` ya no existe en GBP (cuando cambian un ítem), y el **saldo pendiente** baja a 0 si la línea quedó **procesada** en GBP aunque `confirmed` siga en 0. En el detalle ves la columna **GBP** y un aviso si el sync tocó líneas.

## Cómo se usa

1. Abrí el pedido en **Compras → Pedidos** (estado pendiente de controlar, p. ej. `recibido`).
2. Pulsá **Actualizar OC**.
3. Revisá líneas: ítems nuevos/reemplazados, chip **Procesada** y saldo en 0 cuando GBP ya cerró la línea.
