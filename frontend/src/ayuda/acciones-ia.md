# Acciones IA

Área: Gestión
Ruta: Gestión → Acciones IA
Permiso: Pedile a un administrador el permiso para que la IA modifique Pricing (mcp.escribir). Por ahora lo tienen solo los administradores.

## Para qué sirve

Muestra todo lo que una IA conectada (ChatGPT, Claude, Cursor o Gemini CLI) cambió en Pricing: quién se lo pidió, desde qué aplicación, qué cambió (antes → después), por qué y cómo salió. Desde acá se puede **deshacer** cualquier cambio de la IA y se enciende o apaga la escritura de la IA para todos.

## Cómo se usa

1. Arriba está **Escritura de la IA**. Con el interruptor en **Apagada**, ninguna IA puede modificar nada (solo consultar). Tocalo para encenderla o apagarla; el cambio vale en el momento.
2. Abajo está la lista de acciones, de la más nueva a la más vieja. Usá los filtros para encontrar una.
3. Para deshacer una acción tocá **Deshacer** en su fila. Para deshacer todo lo que la IA hizo en una misma orden tocá **Deshacer plan**.
4. Escribí el **Motivo** (es obligatorio y queda registrado) y tocá **Preparar**.
5. Revisá el plan: cada fila dice **Lista** (se va a deshacer) o **Bloqueada** con el motivo (no se toca). El plan vence a los 15 minutos.
6. Tocá **Confirmar**. Se muestra el resultado de cada fila y la lista se actualiza: la acción original queda como **Deshecha** y aparece una acción nueva que la deshace.

> Si aparece **Bloqueado por el servidor (kill switch)**, la escritura de la IA está cortada desde el servidor y el interruptor no se puede usar. Avisale a quien administra el servidor.

## Filtros y columnas

Filtros:

- **Usuario**: quién le pidió el cambio a la IA.
- **Cliente**: la aplicación de IA (por ejemplo, Claude o ChatGPT).
- **Tool**: la herramienta que usó la IA (por ejemplo, `precio_lista_cambiar`).
- **Resultado**: OK, Rechazada, Bloqueada, Ambigua, Error o Denegada.
- **Desde** / **Hasta**: rango de fechas.

Columnas:

- **Fecha**, **Usuario**, **Cliente**.
- **Acción**: aplicar o quitar promo, pausar, activar, precio de lista, precio en cuotas, markup masivo o precio mayorista. Si la acción deshace otra, dice **Deshace #** con el número de la original.
- **Objetivo**: el producto o la publicación.
- **Antes → después**: los valores que cambiaron.
- **Motivo**: lo que explicó la IA al hacer el cambio.
- **Resultado**: cómo salió. Debajo puede decir **Deshecha** o el detalle de un rechazo.

## Botones y acciones

- **Interruptor de escritura**: enciende o apaga la escritura de la IA para todos los usuarios.
- **Deshacer**: aparece solo en las acciones que salieron bien, que se pueden deshacer y que todavía no se deshicieron.
- **Deshacer plan**: deshace todas las acciones de una misma orden de la IA.
- **Preparar**, **Confirmar**, **Cancelar**, **Cerrar**: los pasos de la ventana de deshacer.
- **Anterior** / **Siguiente**: páginas de 50 acciones.

## Mensajes que pueden aparecer

- **El plan venció o ya se usó. Prepará uno nuevo.** Pasaron más de 15 minutos o el plan ya se confirmó. Tocá **Preparar** otra vez.
- **La escritura de la IA está apagada (kill switch): no se puede deshacer ahora.** Deshacer también es una escritura: encendé la escritura o esperá a que el servidor la libere.
- **No tenés permiso para ver ni deshacer las acciones de la IA (mcp.escribir).** Tu usuario no tiene el permiso.
- Filas **Bloqueadas** al preparar: por ejemplo **el precio cambió desde la acción** (alguien lo cambió después, así que no se pisa), **ML ya no ofrece esa promo** (no se puede volver a aplicar) o **ya deshecha**.

## Preguntas frecuentes

**¿Se puede deshacer todo?**
Casi todo. Una promo que Mercado Libre ya no ofrece no se puede volver a aplicar, y un precio que alguien cambió después de la IA no se pisa: esas filas salen como **Bloqueadas** con el motivo.

**¿Deshacer pasa por los mismos controles que la IA?**
Sí. Deshacer usa el mismo plan con confirmación, los mismos permisos y queda registrado como una acción nueva.

**¿Apagar la escritura corta las conexiones?**
No. La IA sigue pudiendo consultar; solo deja de poder modificar. Para cortar una conexión, ver **Conectar una IA**.
