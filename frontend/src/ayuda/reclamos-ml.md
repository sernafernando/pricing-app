# Reclamos ML

Área: Soporte
Ruta: Soporte → Reclamos ML
Permiso: Pedile a un administrador acceso a RMA.

## Para qué sirve

Centraliza los reclamos de MercadoLibre: verlos, filtrarlos, sincronizarlos con ML y gestionar las devoluciones al local. También permite abrir el detalle de cada reclamo y vincularlo a un caso RMA.

## Cómo se usa

Arriba dice **Reclamos ML**. Si tenés permiso de gestión, el botón **Sincronizar ML** sincroniza con MercadoLibre (mientras trabaja dice **Sincronizando...**).

Si tenés acceso a RMA, hay dos pestañas: **Reclamos** y **Devoluciones al Local**.

En **Reclamos** ves tarjetas de estadísticas (Abiertos, En disputa, Acción requerida, Con caso RMA, Sin caso RMA) que funcionan como filtro. Debajo están los filtros: búsqueda por motivo, título, claim ID u order ID, estado (Todos/Abiertos/Cerrados), etapa (Reclamo/Disputa/Recontacto/Inactivo), tipo (Mediación/Devolución/Fulfillment/Cambio), responsable (Acción nuestra/Acción comprador/Acción mediador) y RMA (todos/Con caso RMA/Sin caso RMA). La tabla muestra Claim, Fecha, Tipo, Etapa, Motivo, Responsable, Vence, Msgs y RMA. Al tocar una fila se abre el detalle.

En **Devoluciones al Local** ves las devoluciones que van al local, con tarjetas por estado (Total al local, Pendientes, En camino, Entregadas) y filtro por estado de envío. La tabla muestra Claim, Fecha, Motivo, Estado envío, Tracking, Tipo envío, Etapa y RMA.

En el detalle se muestra el caso RMA asociado (si existe) y el reclamo completo, con botón para ir al caso o crearlo.

## Filtros y columnas

Ver arriba. Columnas de Reclamos: Claim, Fecha, Tipo, Etapa, Motivo, Responsable, Vence, Msgs, RMA. Columnas de Devoluciones: Claim, Fecha, Motivo, Estado envío, Tracking, Tipo envío, Etapa, RMA.

## Botones y acciones

- **Sincronizar ML**: sincroniza reclamos con MercadoLibre (si tenés permiso de gestión).
- Tocar una fila: abre el detalle.
- En el detalle: **Ir al caso** (si tiene RMA) o **Crear caso RMA**.

## Preguntas frecuentes

**¿Qué diferencia hay entre Reclamos y Devoluciones al Local?**
Reclamos muestra todos los reclamos; Devoluciones al Local muestra solo las devoluciones que van al local (seller_address).

**¿Cómo vinculo un reclamo a un RMA?**
Desde el detalle del reclamo, si no tiene RMA asociado y tenés permiso de gestión, podés ir a crear el caso RMA.
