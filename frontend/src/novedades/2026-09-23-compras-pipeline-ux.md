# Compras: pipeline de pedidos, facturas, Depósito y faltantes

Área: Compras

Desarrollado por Gabe.

## Resumen ejecutivo

En **Compras** ahora se ve de un vistazo si hay OC vinculada, si la factura está cargada en GBP y el estado del Match de los artículos por IA. Las alertas de factura y de faltantes llegan **dentro de Pricing** (banner + campanita), sin WhatsApp.

**Importante:** tener el número de factura en el pedido **no** es lo mismo que “cargada en ERP”. La alerta sale solo cuando Administración tilda el check y pasan 5 minutos sin que se arrepienta.

Si Depósito marca **faltantes**, avisa al responsable. Ese aviso **no se apaga con OK**: hay que escribir **qué hacer** para resolverlo. Cuando se escribe la resolución, el pedido pasa a **Faltantes con resolución**, Depósito recibe esas instrucciones y puede terminar el control. El tab **Con faltantes** muestra **solo los sin resolución**; los resueltos viven en **Faltantes con resolución**.

También hay multi-OC, deshacer recibido, tipo mercadería/servicio, y en control se puede dejar observación y foto.

## Cómo se usa

### Chips en la lista de Pedidos

Entrá a **Administración → Compras**. En **Proceso** ves chips (no son el estado financiero del pedido):

- **OC**: el pedido está vinculado a una OC en Pricing.
- **Número** (atenuado): hay constancia del número de factura, pero **todavía** no se cargó a GBP.
- **Factura**: al menos una factura tiene el check **Cargada en ERP**.
- **Match**: estado del último job de OC Match.

Si hay **varias OCs**, además del chip OC pueden verse etiquetas `#…` con cada OC vinculada. El eje logístico (Por recibir / Recibido / Faltantes / Faltantes con resolución / Controlado) va aparte del estado de pago.

El listado de **Pedidos** arranca **sin cancelados**. **Cancelado** sigue en el filtro si lo necesitás. También podés filtrar **recibido**, **con faltantes** y **controlado**.

### Constancia de número ≠ cargada en ERP

Subir el PDF/imagen, que OC Match termine bien, o cargar el número a mano, **solo deja constancia**. Eso **no** prende el chip Factura y **no** dispara alerta.

El NV o número de pedido del proveedor (`pedidos_documento`) sigue siendo texto: no tiene check de cargada.

En el **detalle** del pedido, cada factura es número + check **Cargada en ERP**. El texto viejo de facturas no cuenta como cargada.

### Check “Cargada en ERP” y alerta (5 minutos)

1. Tildá **Cargada en ERP** cuando esa factura ya está en el ERP. El chip **Factura** se prende al toque.
2. Arranca un timer de **5 minutos**. Si el check sigue tildado al finalizar, llega la alerta in-app **solo** a quienes tienen `administracion.ver_alertas_factura`. El rol **ADMIN no alcanza** por sí solo (Chicho asigna el permiso). El aviso lo dispara el cron `python -m app.scripts.dispatch_factura_cargada_alerts`; sin crontab no llega.
3. Si destildás **antes** de que dispare, se cancela el aviso. La fila **no** se borra.
4. Destildar **después** de que ya llegó el aviso apaga el chip; el banner que ya viste no se retracta solo — en ese caso hay que avisar a mano.

### Borrar el número es otro reloj

Borrar la fila de constancia es **otro** timer de 5 minutos, desde que se **creó** esa fila — no desde el check. Destildar no es borrar. Pasados esos 5 minutos, borrar queda bloqueado; destildar sigue permitido.

### Faltantes: del Depósito al PM y vuelta

1. En **Recepción / Depósito**, al marcar **con faltantes**, el texto de qué falta es **obligatorio**. Depósito elige el **responsable** (por defecto el actual). Llega alerta a esa persona.
2. Esa alerta **no** se cierra para siempre con Ver ni con la X: **Ver** abre el pedido (sin descartarla); **X** y **Posponer** la ocultan 1 hora y después vuelve si sigue sin resolución. En la campanita no hay acción de borrar para este aviso.
3. El responsable escribe en el detalle **qué hay que hacer** (texto obligatorio) y guarda. El pedido pasa a **Faltantes con resolución**.
4. Depósito recibe el aviso **faltantes resueltos** con esas instrucciones. **Con faltantes** solo muestra los **sin** resolución; los ya resueltos están en **Faltantes con resolución**.
5. En control (también si está todo OK) se puede dejar **observación** y **foto**.

> Si marcás faltantes y el responsable no escribe la resolución, el aviso **sigue**. No alcanza con leerlo y darle OK.

### Depósito: filtros, docs y deshacer

Tab **Recepción / Depósito** (permiso `deposito.recibir_mercaderia`). Los **servicios** no aparecen ahí.

- **Por recibir** lista lo **pagado** y, por defecto, también **cuenta corriente**. El toggle **Incluir cuenta corriente** viene **prendido**; lo podés apagar si no querés ver CC.
- **Docs** abre los **adjuntos del pedido**.
- Si marcaste **recibido** por error: **deshacer recibido** (vuelve a pagado o CC). **Controlado** no se deshace.
- Si la factura está cargada en ERP, ves un badge **Factura cargada**. En la fila también ves número de factura y pedido del proveedor cuando hay datos.

### Varias OCs en el mismo pedido

> Al vincular, fijate bien: **Desvincular OC saca todas** de una vez (hoy no hay desvínculo de una sola).

1. Vincular una OC **agrega**, no reemplaza. En Depósito hay **un bloque por cada OC**.
2. Si la OC está vinculada pero el ERP no trae líneas, el bloque **sigue visible** (“OC no encontrada en ERP”).
3. El pedido pasa a **Controlado** cuando están **todas** las OCs controladas.

### Tipo mercadería o servicio

Al **crear** el pedido podés elegir **mercadería** (pasa por OC/Depósito) o **servicio** (no estorba la cola de recepción). Después del alta, el tipo lo corrige un admin si hace falta.

### Alertas in-app

Factura cargada, faltantes y faltantes resueltos son solo in-app (banner + campanita). Si hay muchas, ves las primeras y **+N más**. En factura cargada, **Ver** y la **X** descartan el aviso. En faltantes, **Ver** solo abre el pedido; la **X** pospone 1 hora. El aviso de faltantes se apaga de verdad cuando el responsable escribe la resolución.

> Si una OC no aparece en el ERP, no la desvinculés “para limpiar” sin hablarlo: el bloque vacío es a propósito.

¿Dudas? Consultale a **Gabe**.
