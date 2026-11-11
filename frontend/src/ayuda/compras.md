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

## Botones y acciones

Varían por pestaña.

## Preguntas frecuentes

**¿Por qué no veo todas las pestañas?**
Cada pestaña pide un permiso propio.

**¿Se puede abrir una pestaña específica por link?**
Sí, usando ?tab= en la URL (por ejemplo ?tab=ordenes-pago).

**¿Qué hace Actualizar OC?**
En el detalle del pedido, **Actualizar OC** vuelve a traer del ERP el contenido de las órdenes de compra ya vinculadas (líneas y cantidades del espejo). No corrige ni borra recepciones ya cargadas en Depósito: si la OC cambió en GBP, el saldo pendiente se recalcula sobre lo que ya ingresó.

**¿Se puede vincular más de una factura ERP a un pedido?**
Sí. En el detalle del pedido, **Facturas del ERP** lista cada `ct_transaction` vinculada, permite **Desvincular** una por una y **Vincular otra**. La misma factura también puede quedar documentada en varios pedidos; el sell-in de líneas solo se arma cuando esa factura queda ligada a un solo pedido.
