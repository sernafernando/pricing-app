# Compras

Área: Administración
Ruta: Administración → Compras
Permiso: Cualquiera de los permisos de Compras abre la página; cada pestaña pide el suyo (administracion.ver_ordenes_compra, administracion.ver_cuentas_corrientes, deposito.recibir_mercaderia, tesoreria.gestionar_cheques, administracion.eliminar_compras_basura).

## Para qué sirve

Gestiona las compras y pagos a proveedores: pedidos, órdenes de pago, notas de crédito, cuentas corrientes, reconciliación, catálogo, depósito, cheques, match de OC y papelera.

## Cómo se usa

Arriba dice **Compras**. Las pestañas (según permisos) son: **Pedidos**, **Órdenes de Pago**, **Notas de Crédito**, **CC Proveedores**, **Reconciliación**, **Catálogo SD**, **Depósito**, **Cheques**, **OC Match** y **Papelera**.

Cada pestaña carga su propio contenido. La pestaña activa se puede cambiar por la URL (?tab=...).

## Filtros y columnas

Varían por pestaña.

En **Pedidos** y **Depósito** podés filtrar por número de pedido, **Nº OC** (poh_id, campo aparte), **Producto / EAN** en líneas de la OC vinculada, y **Creado por** (selector de usuarios que ya crearon pedidos). El número de pedido y el de OC no se mezclan: un `503` en OC no trae el pedido `P-…-00503`.

## Botones y acciones

Varían por pestaña.

## Preguntas frecuentes

**¿Por qué no veo todas las pestañas?**
Cada pestaña pide un permiso propio.

**¿Se puede abrir una pestaña específica por link?**
Sí, usando ?tab= en la URL (por ejemplo ?tab=ordenes-pago).

**¿Qué hace Actualizar OC?**
En el detalle del pedido, **Actualizar OC** vuelve a traer del ERP el contenido de las órdenes de compra ya vinculadas (ítems, cantidades y flag de procesado en GBP) y **saca del espejo** las líneas cuyo `pod_id` ya no existe en GBP (típico cuando en el ERP cambian un ítem y reemplazan la línea). El **saldo pendiente** de cada línea baja a 0 cuando GBP marcó la línea como procesada (`pod_isprocessed`), aunque `pod_confirmedqty` siga en 0 — eso es el proceso administrativo del ERP, distinto del control de depósito en Pricing. Se puede usar mientras el pedido está pendiente de controlar (p. ej. `recibido`). Si ya hay control de depósito (`con_faltantes` o `controlado`), el botón queda bloqueado: refrescar el espejo dejaría inconsistentes los ingresos ya cargados. En Depósito, **Revertir control** (mismo permiso `deposito.recibir_mercaderia`) vuelve el pedido a `recibido`, borra las tandas de control y habilita de nuevo Actualizar OC / recontrolar.

**¿Se pueden registrar retiros/recepciones parciales en Depósito?**
Sí, en pedidos **con OC** todavía en *Por recibir* / *Por retirar* (chip de Proceso en Pedidos, según `requiere_envio`). Por cada línea cargás cuánto se retiró/recibió y confirmás con **Guardar este retiro** / **Guardar esta recepción** (no cierra el pedido). Con parciales guardados, el chip de Proceso en Pedidos y el badge de Depósito pasan a verde **Recibiendo** / **Retirando**. Cuando el acumulado cubre el total, Guardar se deshabilita y hay que pulsar **Marcar pedido como recibido/retirado completo** para pasar a *Sin controlar*. **Deshacer recibido/retiro** vuelve al eje por recibir/retirar y borra ese progreso.

**¿Se puede vincular más de una factura ERP a un pedido?**
Sí. En el detalle del pedido, **Facturas del ERP** lista cada factura vinculada con su **número de factura** (y el id interno GBP como dato secundario), permite **Desvincular** una por una y **Vincular otra**. La misma factura también puede quedar documentada en varios pedidos; el sell-in de líneas solo se arma cuando esa factura queda ligada a un solo pedido.

**¿Se puede cambiar la fecha de pago estimada después de aprobar?**
Sí. En **Ver detalle**, con permiso de gestionar órdenes de compra, **Editar** en Fecha pago estimada (también en borrador / pagado parcial / pagado). Órdenes de pago usa esa fecha para priorizar vencimientos; sirve si el pago se difiere de común acuerdo o si el originador no la cargó.

**¿Por qué el botón Cerrar del detalle del pedido queda siempre a la vista?**
En **Ver detalle**, el contenido largo (líneas, facturas, OC) hace scroll adentro del modal; la barra de acciones con **Cerrar** queda fija abajo del diálogo para no tener que bajar hasta el final.
