# La IA ahora puede modificar Pricing, con confirmación y Deshacer

Área: Gestión

## Resumen ejecutivo

Los administradores pueden pedirle a la IA conectada (Claude, Claude Code, Cursor o Gemini CLI; ChatGPT solo si tu plan permite acciones en conectores) que haga cambios: aplicar o quitar promociones, pausar o activar publicaciones y cambiar precios de lista, en cuotas y mayoristas. Cada orden lleva sus propios límites, ningún precio se mueve más de 10% de una vez, nada se aplica sin que confirmes el plan, y todo queda en la pantalla nueva **Acciones IA**, donde se puede deshacer. La escritura de la IA arranca **apagada**.

## Qué cambia

- Permiso nuevo **mcp.escribir**, solo para administradores. Quien tiene solo **mcp.conectar** sigue consultando, sin modificar.
- La pantalla **Conectar con Pricing** dice **consultar y MODIFICAR** cuando la conexión va a poder hacer cambios.
- La IA primero muestra un plan con lo que va a cambiar y aplica solo cuando confirmás.
- Cada orden tiene que decir sus límites: máximo de items, % de cambio máximo (hasta 10%) y markup mínimo.
- Pantalla nueva **Gestión → Acciones IA**: la lista de todo lo que hizo la IA, con **Deshacer**, y el interruptor que enciende o apaga la escritura de la IA.

## Cómo se usa

1. Entrá a **Gestión → Acciones IA** y encendé **Escritura de la IA**.
2. Volvé a conectar tu aplicación de IA para que pida el permiso de modificar, y tocá **Permitir** en la pantalla que dice **consultar y MODIFICAR**.
3. Pedile el cambio a la IA con sus límites, por ejemplo: *"aplicá todas las promos que mejoran 5%, máximo 30 publicaciones, markup mínimo 12%"*.
4. Revisá el plan que te muestra la IA y confirmá.
5. Para deshacer, en **Acciones IA** tocá **Deshacer** en la fila (o **Deshacer plan** para toda la orden), escribí el motivo, tocá **Preparar** y después **Confirmar**.

> El paso a paso está en **Ayuda → Acciones IA** y **Ayuda → Conectar una IA (ChatGPT, Claude, Cursor o Gemini)**.
