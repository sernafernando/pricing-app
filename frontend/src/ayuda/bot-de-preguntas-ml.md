# Bot de Preguntas ML

Área: Soporte
Ruta: Soporte → Bot de Preguntas ML
Permiso: Pedile a un administrador acceso al bot de preguntas (ml_bot.ver; responder pide ml_bot.responder; configurar pide ml_bot.config; encender/apagar pide ml_bot.on_off; mensajes piden ml_bot.messages.ver).

## Para qué sirve

Es el panel del bot que responde preguntas de pre-venta en MercadoLibre. Permite ver las preguntas recibidas y sus respuestas en borrador, tomar el control (take-over), editar/publicar respuestas, ver mensajes post-venta, gestionar pendientes administrativos y configurar el bot.

## Cómo se usa

Arriba dice **Bot de Preguntas ML**. Hay botones **Activar** y **Apagar** para encender/apagar el bot (si tenés permiso) y el botón **Actualizar**.

Las pestañas (según permisos) son: **Preguntas**, **Mensajes**, **Pendientes** y **Configuración**.

En **Preguntas** se listan las preguntas con filtros por estado y razón de fallback. Cada fila se expande para ver el detalle y el historial del comprador. Se pueden tomar (take-over), poner en espera (hold), editar la respuesta, guardar y publicar, o publicar ahora. Las respuestas se publican automáticamente tras una ventana de espera; el contador regresivo se muestra en la fila.

En **Mensajes** se ven las conversaciones post-venta agrupadas por pack/comprador, con el texto, el estado del bot y la posibilidad de tomar control, editar y enviar (si está habilitado).

En **Pendientes** se gestionan las solicitudes administrativas (CUIT, etc.) con estados Nuevo/En progreso/Resuelto/Cancelado, asignación, resolución con CUIT y cancelación con motivo.

En **Configuración** (si tenés permiso) se editan los parámetros del bot, los proveedores LLM y los ejemplos de entrenamiento (few-shot).

## Filtros y columnas

Preguntas: filtro por estado y razón de fallback. Mensajes: filtro por comprador, pack, sin pack, leídos, estado del bot, incluir moderados. Pendientes: filtro por estado, origen y validez de CUIT.

## Botones y acciones

- Encender/apagar bot.
- **Actualizar**: recarga.
- Tomar control, poner en espera, editar, guardar, publicar ahora.
- En mensajes: tomar control, editar respuesta, enviar.
- En pendientes: tomar, liberar, resolver (con CUIT), cancelar (con motivo), crear manual.
- En configuración: guardar parámetros, agregar/quitar proveedores, crear/eliminar ejemplos.

## Preguntas frecuentes

**¿Por qué no veo la pestaña Configuración?**
Pide el permiso ml_bot.config.

**¿El bot publica solo?**
Sí, tras una ventana de espera. Podés tomar control para revisar/editar antes de que se publique.

**¿Qué es "Pendientes"?**
Solicitudes administrativas derivadas por el bot (por ejemplo cambio de CUIT para facturación).
