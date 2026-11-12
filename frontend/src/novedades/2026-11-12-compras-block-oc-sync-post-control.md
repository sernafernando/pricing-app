# Actualizar OC bloqueado tras control de depósito

Área: Compras

## Resumen ejecutivo

**Actualizar OC** ya no corre cuando el pedido está `con_faltantes` o `controlado`. Así el espejo del ERP no se desvía de lo que Depósito ya contó. Si el pedido solo está `recibido` (arribo, aún sin controlar), el refresh sigue disponible.

## Cómo se usa

1. Abrí el pedido en **Compras → Pedidos**.
2. Si está pendiente de controlar, **Actualizar OC** sigue activo.
3. Si ya hay control (faltantes o controlado), el botón aparece deshabilitado con el motivo en el tooltip.
