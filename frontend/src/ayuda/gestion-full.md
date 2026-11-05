# Gestión Full

Área: Reportes
Ruta: Reportes → Gestión Full
Permiso: Acceso a Productos o a Ventas ML (productos.ver o ml_ops.ver). Para editar el override hace falta ser PM/sub-PM del producto o admin.

## Para qué sirve

Planifica cuánto mandar a Full: una fila por producto ERP y familia MLAU, con Código ML, ventas, stocks y una sugerencia de envío que el PM puede pisar.

## Cómo se usa

Arriba dice **Gestión Full**. Hay pestañas **Planificación**, **Consulta envíos**, con permiso `gestion_full.depositos` **Depósito** (U/caja e import), y con `gestion_full.gestor` **Envío** (armar paquete, Excel ML/ops, asignar inbound_id, quitar líneas del envío). En Planificación: búsqueda, filtros de producto (Marca / Categoría / PM, multi-selección; sin Subcategoría), presencia Full, stock ERP y **Solo Listo**.

En **Depósito**, por defecto ves **Pendientes**: productos sin U/caja que ya están en el **paquete de la semana** y/o marcados **Listo** (así el Excel no se traba). La columna Motivo dice Paquete / Listo. Con **Todos** cargás el catálogo ERP (búsqueda + import) como antes.

Por defecto: **En Full** y **sin** filas con Stock ERP en 0. La tabla ordena por EAN y, si un mismo EAN tiene varios MLAU, esas filas van juntas con el mismo tinte.

## Filtros y columnas

Filtros:

- Búsqueda libre: EAN, descripción, Código ML (`inventory_id`), MLAU o **family_id** exacto (el id numérico de familia de ML).
- **Marca / Categoría / PM:** multi-selección con listas que se cruzan (mismo panel que Métricas/Ventas ML). No hay Subcategoría.
- **Presencia Full:** En Full (default) = Stock Full > 0 **o** ventas Full 30d > 0. Fuera de Full = ambos en 0. Todos = sin ese filtro.
- **Mostrar sin stock ERP:** apagado por default; al activarlo incluye filas con Stock ERP 0.
- **Solo Listo:** muestra solo filas con **Listo** activo (hasta que el gestor complete el envío y se liberen, o se desbloqueen).

Columnas: EAN, Descripción, Código ML (inventory_id), Familia (MLAU), ventas Full 7/14/21/30 días, ventas Colecta+Flex 7 y 30 días, Stock ERP, U/caja (unidades por caja cerrada, por producto ERP), Stock Full, Target (última recepción inbound a Full según ML), Sugerido, Override, Qty PM, Listo.

## Botones y acciones

- **Limpiar**: vuelve a búsqueda vacía, sin marcas/categorías/PM, En Full, oculta sin stock ERP y apaga Solo Listo.
- **Sugerido**: `min(Target − Stock Full, Stock ERP)` (mínimo 0): cuánto mandar para volver al último envío, sin pasarse del stock físico. Sin Target queda vacío.
- **Target**: se actualiza solo sábado y domingo (consulta gradual a ML del último ingreso a Full). Un admin puede forzar un refresh puntual.
- **Override**: solo PM/sub-PM del producto o admin. Se guarda al salir del campo (o Enter). Vaciar y salir borra el override; si está vacío, vale el Sugerido. Queda bloqueado cuando la fila está **Listo**.
- **Cerrar / Listo**: el PM congela Qty PM (`override` o Sugerido, tope stock ERP) y bloquea el override. Solo un usuario con `gestion_full.gestor` puede **Desbloquear**.
- **Envío (gestor):** **Sumar líneas Listo** agrega al paquete todas las filas cerradas (server-side, sin tope de 500). **Después de exportar el Excel**, el Listo nuevo del PM **no entra** a este paquete: queda para el próximo envío; Sumar solo puede re-capear hacia abajo líneas que ya estaban. En la grilla podés editar **Qty export** (tope stock ERP) antes de exportar. Descargar **Excel ML** / **Excel ops** exige que el stock ERP cubra la qty a enviar de cada línea; si no, el export falla nombrando los productos y hay que sacar o bajar esos SKUs del paquete antes de reintentar. Multi-selección + `inbound_id` → **Asignar**. Multi-selección → **Quitar del envío** saca esas líneas del paquete (con aviso de cuántas). Cuando todas las líneas con qty≥1 tienen inbound, el paquete queda locked y se liberan los Listo de esas filas. **Limpiar inbounds** habilita regenerar Excel.
- **Consulta envíos:** lista local por `inbound_id` (human id `{lunes}_{inbound_id}`) y detalle declarado vs recibido. Un worker cada 3h actualiza recepciones; cierra localmente a los 3 días sin novedades **después de la primera recepción** (no cierra si los polls a ML fallan).

## Preguntas frecuentes

**¿Por qué el mismo EAN aparece varias veces?**
Porque tiene más de una familia MLAU. Cada una se planifica aparte (lleva su Código ML); el override es por fila.

**¿Quién ve la pantalla?**
Cualquiera con acceso a Productos o a Ventas ML. Todos ven todas las filas; el override está restringido.
