# Conectar una IA (ChatGPT, Claude, Cursor o Gemini)

Área: Otras pantallas
Ruta: Sin entrada en el menú; se configura desde la aplicación de IA y Pricing muestra la pantalla de autorización (/mcp/autorizar).
Permiso: Pedile a un administrador el permiso para conectar aplicaciones de IA (mcp.conectar).

## Para qué sirve

Permite que una aplicación de inteligencia artificial consulte Pricing en tu nombre. Desde un chat podés preguntar, por ejemplo, cómo vienen las ventas de una marca o qué publicaciones tienen poco stock, y la IA busca la respuesta en Pricing.

Se pueden conectar:

- **ChatGPT** (cuentas Plus o Pro).
- **Claude**, en la web (claude.ai) o en la aplicación de escritorio.
- **Claude Code**, desde la terminal.
- **Cursor**, el editor de código.
- **Gemini CLI**, desde la terminal. La aplicación Gemini (gemini.google.com) y Gemini Enterprise todavía no se pueden conectar.

En todos los casos:

- Las consultas son de **solo lectura**: la IA no puede cambiar precios, publicaciones ni ningún otro dato.
- Trabaja **con tus mismos permisos**: ve lo mismo que ves vos en la aplicación, ni más ni menos. Si no podés ver costos o ganancias, la IA tampoco.
- Puede consultar publicaciones de Mercado Libre, métricas de Mercado Libre, ventas de Mercado Libre y por fuera, la auditoría de stock, y productos con sus precios.
- Puede armar tablas de promociones por publicación: la promoción actual, las sugeridas por tipo (las mismas que marca el panel como **Sugerida**), la mejor de ellas (la de mayor markup con sell in), el precio de venta y cuánto mejora el markup, en puntos y en %. Se puede filtrar por PM con el nombre, por ejemplo: *"haceme una tabla con los productos de Eli, promoción actual y mejor promoción con precio de venta y markup con sell in"*. Si el nombre coincide con más de un PM, la IA pregunta cuál.

## Cómo se usa

La dirección del servidor es siempre `https://<dominio de pricing>/api/mcp`, con el mismo dominio con el que entrás a la aplicación. Al final de cada paso a paso se abre Pricing: si no tenés la sesión iniciada, ingresá con tu usuario y contraseña de siempre, revisá la pantalla **Conectar con Pricing** y tocá **Permitir**.

### ChatGPT

1. En ChatGPT, entrá a **Settings → Apps/Connectors → Advanced** y activá **Developer mode**.
2. Volvé a **Settings → Apps/Connectors** y creá un conector nuevo.
3. Poné un nombre (por ejemplo, Pricing) y la dirección del servidor.
4. En autenticación elegí **OAuth** y guardá.
5. Autorizá en Pricing. ChatGPT vuelve a abrirse con el conector listo.

### Claude (web o escritorio)

1. En Claude, entrá a **Customize → Connectors**, tocá **+ Add** y elegí **Add custom connector**. En planes Team o Enterprise lo agrega un Owner desde **Organization settings → Connectors**; después cada persona lo conecta.
2. Poné un nombre (por ejemplo, Pricing) y la dirección del servidor.
3. En las opciones de autenticación dejá **Use Claude's published identity**. No hace falta cargar ningún código de cliente.
4. Tocá **Connect** y autorizá en Pricing. La pantalla de autorización dice que la conexión vuelve a **claude.ai**.

### Claude Code

1. En la terminal, ejecutá:
   ```
   claude mcp add --transport http pricing https://<dominio de pricing>/api/mcp
   ```
2. Dentro de Claude Code escribí `/mcp`, elegí **pricing** y tocá **Authenticate**.
3. Se abre el navegador: autorizá en Pricing. La pantalla de autorización dice que la conexión vuelve a **localhost (en esta computadora)**.

### Cursor

1. Abrí el archivo `~/.cursor/mcp.json` (o `.cursor/mcp.json` dentro de un proyecto) y agregá:
   ```json
   {
     "mcpServers": {
       "pricing": {
         "url": "https://<dominio de pricing>/api/mcp",
         "auth": { "CLIENT_ID": "pricing-mcp-cursor" }
       }
     }
   }
   ```
   `pricing-mcp-cursor` es el código fijo de Cursor para Pricing. No lleva contraseña de cliente.
2. En Cursor, entrá a **Settings → MCP**. Debajo de **pricing** tocá **Needs login** (o **Connect**).
3. Se abre el navegador: autorizá en Pricing. La pantalla de autorización dice que la conexión vuelve a **localhost (en esta computadora)**, o a **www.cursor.com** si usás Cursor en la web.

### Gemini CLI

1. Abrí el archivo `~/.gemini/settings.json` y agregá:
   ```json
   {
     "mcpServers": {
       "pricing": {
         "httpUrl": "https://<dominio de pricing>/api/mcp",
         "oauth": { "enabled": true, "clientId": "pricing-mcp-gemini-cli" }
       }
     }
   }
   ```
   `pricing-mcp-gemini-cli` es el código fijo de Gemini CLI para Pricing. No lleva contraseña de cliente.
2. Dentro de Gemini CLI escribí `/mcp auth pricing`.
3. Se abre el navegador: autorizá en Pricing. La pantalla de autorización dice que la conexión vuelve a **localhost (en esta computadora)**.

> Si tocás **Cancelar**, no se crea ninguna conexión y la IA queda sin acceso.

> Tocá **Permitir** solo si vos acabás de iniciar la conexión desde tu propia aplicación de IA. Si te llega un link de autorización que no pediste, cancelalo: quien lo mandó podría usar tu acceso.

Claude Code, Cursor y Gemini CLI quedan conectados **en esa computadora**. Si usás otra computadora, conectalos de nuevo desde ahí; cada una aparece como una conexión aparte.

## Mensajes que pueden aparecer

- **El pedido de conexión venció o ya se usó. Volvé a conectar desde la aplicación de IA.** El pedido dura unos minutos y sirve una sola vez. Repetí la conexión desde la IA.
- **No tenés permiso para conectar aplicaciones de IA (mcp.conectar). Pedíselo a un administrador.** Tu usuario no tiene el permiso para conectar aplicaciones de IA.
- **redirect_uri no permitido para este cliente** o **cliente no autorizado**: la aplicación de IA o su configuración no está habilitada. Revisá que el código de cliente esté escrito tal cual (Cursor y Gemini CLI) y avisale a un administrador.

## Revocar una conexión

Un administrador puede cortar el acceso en cualquier momento: **Gestión → Admin → Usuarios**, elegir el usuario, tocar **Editar** y, en la sección **Conexiones de IA (MCP)**, tocar **Revocar** en la conexión y confirmar con **Sí, revocar**. La IA deja de poder consultar desde ese momento; para volver a usarla hay que conectarla de nuevo.

Si a un usuario se le quita el permiso **mcp.conectar** o se lo desactiva, todas sus conexiones dejan de funcionar.

## Preguntas frecuentes

**¿La IA puede modificar algo en Pricing?**
No. Todas las consultas son de solo lectura.

**¿Ve más de lo que veo yo?**
No. Usa tus mismos permisos, así que ve exactamente lo que ves vos en la aplicación.

**¿Tengo que crear un usuario o una contraseña nueva?**
No. Ingresás con tu usuario de siempre.

**¿Puedo usar la aplicación Gemini del celular o de gemini.google.com?**
Todavía no. Por ahora Gemini se conecta solo con Gemini CLI.
