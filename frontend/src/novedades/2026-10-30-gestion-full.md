# Gestión Full

Área: Reportes

## Resumen ejecutivo

Nueva pantalla **Reportes → Gestión Full** para planificar cuánto mandar a Full por producto y código Full (`inventory_id`). Muestra ventas Full y Colecta+Flex, stocks, el último envío a Full (Target), una sugerencia de reposición y un override editable para PM.

## Cómo se usa

1. Abrir **Reportes → Gestión Full**.
2. Filtrar por búsqueda, marca o categoría si hace falta (por defecto se ven todas las filas).
3. Revisar **Target** (última recepción a Full) y **Sugerido** (cuánto falta para volver a ese Target).
4. Si sos PM/sub-PM del producto o admin, completar **Override** y salir del campo (o Enter) para guardar.

## Para tener en cuenta

- El mismo EAN puede aparecer varias veces si tiene más de un `inventory_id`; van juntas con el mismo tinte.
- Target se actualiza solo el fin de semana (consulta gradual a ML). Un admin puede forzar un refresh puntual.
- Sin Target, Sugerido queda vacío. Si Full ya tiene stock ≥ Target, Sugerido es 0.
- Override vacío = vale el Sugerido.
