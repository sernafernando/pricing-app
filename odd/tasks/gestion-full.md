# Gestión Full

Área: Reportes
Ruta: Reportes → Gestión Full
Permiso: Acceso a Productos o a Ventas ML (productos.ver o ml_ops.ver). Para editar el override hace falta ser PM/sub-PM del producto o admin.

## Para qué sirve

Planifica cuánto mandar a Full: una fila por producto ERP y código Full (`inventory_id`), con ventas, stocks y una sugerencia de envío que el PM puede pisar.

## Cómo se usa

Arriba dice **Gestión Full**. La barra tiene búsqueda (EAN, descripción o inventory_id) y filtros opcionales de marca y categoría. Por defecto se ven todas las filas; los filtros son opcionales.

La tabla ordena por EAN y, si un mismo EAN tiene varios `inventory_id`, esas filas van siempre una debajo de la otra con el mismo tinte suave.

## Filtros y columnas

Filtros: búsqueda libre, marca exacta, categoría exacta.

Columnas: EAN, Descripción, Código ML (inventory_id), Familia (MLAU), ventas Full 7/14/21/30 días, ventas Colecta+Flex 7 y 30 días, Stock ERP, Stock Full, Target (última recepción inbound a Full según ML), Sugerido, Override.

## Botones y acciones

- **Limpiar**: saca búsqueda y filtros.
- **Sugerido**: `Target − Stock Full` (mínimo 0): cuánto mandar para volver al último envío. Sin Target queda vacío.
- **Target**: se actualiza solo sábado y domingo (consulta gradual a ML del último ingreso a Full). Un admin puede forzar un refresh puntual.
- **Override**: solo PM/sub-PM del producto o admin. Se guarda al salir del campo (o Enter). Vaciar y salir borra el override; si está vacío, vale el Sugerido.

## Preguntas frecuentes

**¿Por qué el mismo EAN aparece varias veces?**
Porque tiene más de un código Full (`inventory_id`). Cada uno se manda aparte; el override es por fila.

**¿Quién ve la pantalla?**
Cualquiera con acceso a Productos o a Ventas ML. Todos ven todas las filas; el override está restringido.
