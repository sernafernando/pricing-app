# Notificaciones

Área: Otras pantallas
Ruta: Sin entrada en el menú; se llega desde la campana de notificaciones.
Permiso: Pedile a un administrador acceso a Notificaciones (reportes.ver_notificaciones).

## Para qué sirve

Muestra las notificaciones del sistema (por ejemplo, facturas cargadas en Compras, markup bajo, stock bajo), separadas por familia en pestañas, con filtros por PM, urgencia y estado de lectura.

## Cómo se usa

Arriba dice **Notificaciones**. Se muestra el total y la cantidad de no leídas. Debajo están las pestañas **Todas**, **Compras** (facturas, faltantes y diferencias de monto de los pedidos), **Markup**, **Técnicas** (alertas internas del sistema) y **Otras**; cada pestaña muestra cuántas no leídas tiene. Hay filtros por PM, urgencia (Urgente/Crítico/Advertencia/Info), solo no leídas y ordenamiento (por urgencia, fecha o markup). Se puede ver agrupada por producto/markup o como lista.

En la vista de lista las páginas se piden de a 20, así que con **Siguiente** llegás hasta la notificación más vieja. Las notificaciones de Compras muestran su propio título y mensaje (pedido, proveedor y factura), nunca un producto.

Al expandir una notificación se marca como leída automáticamente y se ven más detalles (incluido el precio de venta seteado). En las de markup bajo, **Costo de la Venta** y **Costo Actual** son el costo SI (promedio con sell in) de ese momento; si el costo no se conocía dice **Sin costo**. También hay botones para marcar todas como leídas o no leídas, y acciones **Revisada**, **Ignorar**, **Resuelta** y **Eliminar**.

En la vista agrupada, cada acción se aplica a todo el grupo de una sola vez, aunque tenga miles de notificaciones. **Ignorar** pide una confirmación y crea la regla para no volver a notificar ese producto con ese markup.

## Filtros y columnas

Filtros: pestaña de familia (Todas, Compras, Markup, Técnicas, Otras), PM, urgencia, solo no leídas, agrupada/lista, ordenamiento.

## Botones y acciones

- **Marcar todas leídas** / **Marcar todas no leídas** (solo las de la pestaña elegida).
- **Limpiar leídas**.
- **Revisada**, **Ignorar**, **Resuelta** y **Eliminar** en cada notificación.
- Expandir para ver detalles.

## Preguntas frecuentes

**¿Cómo llego a esta pantalla?**
Desde la campana de notificaciones en la barra superior. La campana también tiene las pestañas por familia.

**No encuentro una factura de Compras, ¿dónde está?**
Abrí la pestaña **Compras** en la campana o en esta pantalla: muestra solo esas notificaciones, aunque haya muchas de markup más nuevas.

**¿Qué significa "solo no leídas"?**
Filtra para mostrar únicamente las notificaciones que todavía no leíste.
