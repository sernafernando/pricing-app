# Gestión Full

Área: Reportes
Ruta: Reportes → Gestión Full
Permiso: Acceso a Productos o a Ventas ML (productos.ver o ml_ops.ver). Para editar el override hace falta ser PM/sub-PM del producto o admin.

## Para qué sirve

Planifica cuánto mandar a Full: una fila por producto ERP y familia MLAU, con Código ML, ventas, stocks y una sugerencia de envío que el PM puede pisar.

## Cómo se usa

Arriba dice **Gestión Full**. Hay pestañas **Planificación**, **Consulta envíos**, con permiso `gestion_full.depositos` **Depósito** (U/caja e import), y con `gestion_full.gestor` **Envío** (armar paquete, Excel ML/ops, asignar inbound_id). En Planificación: búsqueda, marca, categoría, presencia Full y el check de stock ERP.

Por defecto: **En Full** y **sin** filas con Stock ERP en 0. La tabla ordena por EAN y, si un mismo EAN tiene varios MLAU, esas filas van juntas con el mismo tinte.

## Filtros y columnas

Filtros:

- Búsqueda libre, marca exacta, categoría exacta.
- **Presencia Full:** En Full (default) = Stock Full > 0 **o** ventas Full 30d > 0. Fuera de Full = ambos en 0. Todos = sin ese filtro.
- **Mostrar sin stock ERP:** apagado por default; al activarlo incluye filas con Stock ERP 0.

Columnas: EAN, Descripción, Código ML (inventory_id), Familia (MLAU), ventas Full 7/14/21/30 días, ventas Colecta+Flex 7 y 30 días, Stock ERP, U/caja (unidades por caja cerrada, por producto ERP), Stock Full, Target (última recepción inbound a Full según ML), Sugerido, Override, Qty PM, Listo.

## Botones y acciones

- **Limpiar**: vuelve a búsqueda vacía, En Full, y oculta sin stock ERP.
- **Sugerido**: `min(Target − Stock Full, Stock ERP)` (mínimo 0): cuánto mandar para volver al último envío, sin pasarse del stock físico. Sin Target queda vacío.
- **Target**: se actualiza solo sábado y domingo (consulta gradual a ML del último ingreso a Full). Un admin puede forzar un refresh puntual.
- **Override**: solo PM/sub-PM del producto o admin. Se guarda al salir del campo (o Enter). Vaciar y salir borra el override; si está vacío, vale el Sugerido. Queda bloqueado cuando la fila está **Listo**.
- **Cerrar / Listo**: el PM congela Qty PM (`override` o Sugerido, tope stock ERP) y bloquea el override. Solo un usuario con `gestion_full.gestor` puede **Desbloquear**.
- **Envío (gestor):** **Sumar líneas Listo** al paquete, descargar **Excel ML** / **Excel ops**, multi-selección + `inbound_id` → **Asignar**. Cuando todas tienen inbound, el paquete queda locked. **Limpiar inbounds** habilita regenerar Excel.
- **Consulta envíos:** lista local por `inbound_id` (human id `{lunes}_{inbound_id}`) y detalle declarado vs recibido. Un worker cada 3h actualiza recepciones; cierra localmente a los 3 días sin novedades.

## Preguntas frecuentes

**¿Por qué el mismo EAN aparece varias veces?**
Porque tiene más de una familia MLAU. Cada una se planifica aparte (lleva su Código ML); el override es por fila.

**¿Quién ve la pantalla?**
Cualquiera con acceso a Productos o a Ventas ML. Todos ven todas las filas; el override está restringido.
