# Compras: pipeline de pedidos, facturas, Depósito y faltantes

Área: Compras

Desarrollado por Gabe.

## Resumen ejecutivo

En **Compras** ahora se ve de un vistazo si hay OC vinculada, si la factura está cargada en GBP y el estado del Match de los artículos por IA. Las alertas de factura y de faltantes llegan **dentro de Pricing** (banner + campanita), sin WhatsApp.

**Importante:** tener el número de factura en el pedido **no** es lo mismo que “cargada en ERP”. La alerta sale solo cuando Administración tilda el check y pasan 5 minutos sin que se arrepienta.

Si Depósito marca **faltantes**, avisa al responsable. Ese aviso **no se apaga con OK**: hay que escribir **qué hacer** para resolverlo (quien recibe la notificación será responsable de indicar qué debe hacer Depósito con el problema). Cuando se escribe la resolución, el pedido pasa a **Faltantes con resolución**, Depósito recibe esas instrucciones y puede terminar el control. Ojo: el tab **Con faltantes** ahora muestra **solo los sin resolución** (los resueltos viven en **Faltantes con resolución**). También hay multi-OC, deshacer recibido, tipo mercadería/servicio, y en control se puede dejar observación y foto.

## Cómo se usa

### Chips en la lista de Pedidos

1. Entrá a **Administración → Compras**. En **Proceso** ves chips (no son el estado financiero del pedido):
   - **OC**: el pedido está vinculado a una OC en Pricing.
   - **Número** (atenuado): hay constancia del número de factura, pero **todavía** no se cargó a GBP.
   - **Factura**: al menos una factura tiene el check **Cargada en ERP**.
   - **Match**: estado del último job de OC Match.
2. Si hay **varias OCs**, además del chip OC pueden verse etiquetas `#…` con cada OC vinculada.
3. El eje logístico (Por recibir / Recibido / Faltantes / Faltantes con resolución / Controlado) va aparte del estado de pago.

### Constancia de número ≠ cargada en ERP

1. Subir el PDF/imagen, que OC Match termine bien, o cargar el número a mano, **solo deja constancia**. Eso **no** prende el chip Factura y **no** dispara alerta.
2. El NV o número de pedido del proveedor (`pedidos_documento`) sigue siendo texto: no tiene check de cargada.
3. En el **detalle** del pedido, cada factura es número + check **Cargada en ERP**. El texto viejo de facturas no cuenta como cargada.

### Check “Cargada en ERP” y alerta (5 minutos)

1. Tildá **Cargada en ERP** cuando esa factura ya está en el ERP. El chip **Factura** se prende al toque.
2. Arranca un timer de **5 minutos**. Si el check sigue tildado al finalizar el timer, llega la alerta in-app a quienes tienen el permiso `administracion.ver_alertas_factura`.
3. Si destildás **antes** de que dispare, se cancela el aviso. La fila **no** se borra (usar en caso de tildar sin querer).
4. Destildar **después** de que ya llegó el aviso apaga el chip; el banner que ya viste no se retracta solo. En ese caso hay que avisar a mano a quien corresponda (por ejemplo si se cargó mal).

### Borrar el número es otro reloj

Borrar la fila de constancia es **otro** timer de 5 minutos, desde que se **creó** esa fila — no desde el check. Destildar no es borrar. Pasados esos 5 minutos, borrar queda bloqueado; destildar sigue permitido. Esto es para el caso en que se hayan subido documentos equivocados al pedido.

### Faltantes: del Depósito al PM y vuelta

1. En **Recepción / Depósito**, al marcar **con faltantes**, el texto de qué falta es **obligatorio**. Llega alerta al **responsable** del pedido.
2. Esa alerta **no** se cierra con OK ni con Posponer de forma definitiva: **Ver** abre el pedido; **Posponer** la oculta 1 hora desde la marca y después vuelve. En la campanita no hay acción de borrar para este aviso.
3. El responsable escribe en el detalle **qué hay que hacer** para resolver (texto obligatorio) y guarda. El pedido pasa a **Faltantes con resolución** (el estado financiero sigue en con faltantes).
4. Depósito recibe el aviso **faltantes resueltos** con esas instrucciones. En Depósito, **Con faltantes** solo muestra los **sin** resolución; los ya resueltos aparecen en **Faltantes con resolución** para poder terminar el control.
5. En control (también si está todo OK) se puede dejar **observación** y **foto** (adjunto).

> Si marcás faltantes y el responsable no escribe la resolución, el aviso al PM (o al responsable) **sigue**. No alcanza con leerlo y darle OK.

### Depósito: filtros, docs y deshacer

1. Tab **Recepción / Depósito** (permiso `deposito.recibir_mercaderia`). Los **servicios** no aparecen ahí.
2. **Por recibir** lista lo **pagado**. El toggle **Incluir cuenta corriente** suma CC.
3. **Docs** abre los **adjuntos del pedido**.
4. Si marcaste **recibido** por error: **deshacer recibido** (vuelve a pagado o CC). **Controlado** no se deshace.
5. Si la factura está cargada en ERP, ves un badge **Factura cargada** (misma familia visual que Controlado). En la fila también ves número de factura y pedido del proveedor cuando hay datos.

### Varias OCs en el mismo pedido

> Al vincular, fijate bien: **Desvincular OC saca todas** de una vez (hoy no hay desvínculo de una sola).

1. Vincular una OC **agrega**, no reemplaza. En Depósito hay **un bloque por cada OC**.
2. Si la OC está vinculada pero el ERP no trae líneas, el bloque **sigue visible** (“OC no encontrada en ERP”).
3. El pedido pasa a **Controlado** cuando están **todas** las OCs controladas.
4. **Desvincular OC** saca **todas** las OCs de una vez (se está planificando desvínculo por OC).

### Tipo mercadería o servicio

Al **crear** el pedido podés elegir **mercadería** (pasa por OC/Depósito) o **servicio** (no estorba la cola de recepción). Después del alta, el tipo lo corrige un admin si hace falta.

### Alertas in-app

Factura cargada, faltantes y faltantes resueltos son solo in-app (banner + campanita). Si hay muchas, ves las primeras y **+N más**. Cada uno descarta las suyas (salvo faltantes al PM, que exige resolución).

> Si una OC no aparece en el ERP, no la desvinculés “para limpiar” sin hablarlo: el bloque vacío es a propósito.

¿Dudas? Consultale a **Gabe**.
