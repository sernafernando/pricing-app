# Control de reparación

Área: Productos
Ruta: Productos → Control reparación (/ml-repair-control)
Permiso: ml_ops.ver

Pantalla de control (solo lectura) de las corridas del job de reparación de publicaciones (envío y SKU). Permite ver corrida por corrida y MLA por MLA qué se hizo, y detectar escrituras indebidas.

## Para qué sirve

- Listar las corridas recientes con sus contadores (revisados, cambiados, omitidos, errores).
- Filtrar por tipo (Envío/SKU), estado, rango de fechas.
- Abrir una corrida para ver el desglose por motivo y los eventos (MLA, título ML, descripción ERP, acción, motivo, antes → después).
- Buscar un MLA para ver todos sus eventos en todas las corridas y las escrituras confirmadas en ML.
- Título y descripción se leen en vivo de `ml_items` / `productos_erp` (no se guardan en el event).

## Filtros

- Tipo, Estado, Desde/Hasta.
- Buscar MLA: muestra la línea de tiempo de ese MLA y las escrituras confirmadas en ML.

## Notas

- Solo lectura: no escribe en ML ni en las tablas de reparación.
- Los motivos (detail) incluyen: stale_ml_item, status_not_modifiable, full_fulfillment, flex_refused, flex_refused_unchanged, rate_limited, pacer_deadline, max_writes_cap, has_variations, shipping_put, flex_enabled, seller_sku, o texto crudo de ML. Un `changed` de SKU sin motivo es un event viejo (antes de persistir `seller_sku`).
