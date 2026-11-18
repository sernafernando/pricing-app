# Conectar ChatGPT

Área: Otras pantallas
Ruta: Sin entrada en el menú; se configura desde ChatGPT y la aplicación muestra la pantalla de autorización (/mcp/autorizar).
Permiso: Pedile a un administrador el permiso para conectar ChatGPT (mcp.conectar).

## Para qué sirve

Permite que ChatGPT consulte Pricing en tu nombre. Desde un chat podés preguntar, por ejemplo, cómo vienen las ventas de una marca o qué publicaciones tienen poco stock, y ChatGPT busca la respuesta en Pricing.

- Las consultas son de **solo lectura**: ChatGPT no puede cambiar precios, publicaciones ni ningún otro dato.
- Trabaja **con tus mismos permisos**: ve lo mismo que ves vos en la aplicación, ni más ni menos. Si no podés ver costos o ganancias, ChatGPT tampoco.
- Puede consultar publicaciones de Mercado Libre, métricas de Mercado Libre, ventas de Mercado Libre y por fuera, la auditoría de stock, y productos con sus precios.
- Puede armar tablas de promociones por publicación: la promoción actual, las sugeridas por tipo (las mismas que marca el panel como **Sugerida**), la mejor de ellas (la de mayor markup con sell in), el precio de venta y cuánto mejora el markup, en puntos y en %. Se puede filtrar por PM con el nombre, por ejemplo: *"haceme una tabla con los productos de Eli, promoción actual y mejor promoción con precio de venta y markup con sell in"*. Si el nombre coincide con más de un PM, ChatGPT pregunta cuál.

## Cómo se usa

Necesitás una cuenta de ChatGPT Plus o Pro.

1. En ChatGPT, entrá a **Settings → Apps/Connectors → Advanced** y activá **Developer mode**.
2. Volvé a **Settings → Apps/Connectors** y creá un conector nuevo.
3. Poné un nombre (por ejemplo, Pricing) y en la dirección del servidor escribí `https://<dominio de pricing>/api/mcp`, con el mismo dominio con el que entrás a la aplicación.
4. En autenticación elegí **OAuth** y guardá.
5. ChatGPT abre la aplicación. Si no tenés la sesión iniciada, ingresá con tu usuario y contraseña de siempre.
6. Revisá la pantalla **Conectar con Pricing** y tocá **Permitir**. ChatGPT vuelve a abrirse con el conector listo.

> Si tocás **Cancelar**, no se crea ninguna conexión y ChatGPT queda sin acceso.

## Mensajes que pueden aparecer

- **El pedido de conexión venció o ya se usó. Volvé a conectar desde ChatGPT.** El pedido dura unos minutos y sirve una sola vez. Repetí la conexión desde ChatGPT.
- **No tenés permiso para conectar ChatGPT (mcp.conectar). Pedíselo a un administrador.** Tu usuario no tiene el permiso para conectar ChatGPT.

## Revocar una conexión

Un administrador puede cortar el acceso en cualquier momento: **Gestión → Admin → Usuarios**, elegir el usuario, tocar **Editar** y, en la sección **Conexiones de IA (MCP)**, tocar **Revocar** en la conexión y confirmar con **Sí, revocar**. ChatGPT deja de poder consultar desde ese momento; para volver a usarlo hay que conectarlo de nuevo.

Si a un usuario se le quita el permiso **mcp.conectar** o se lo desactiva, sus conexiones dejan de funcionar.

## Preguntas frecuentes

**¿ChatGPT puede modificar algo en Pricing?**
No. Todas las consultas son de solo lectura.

**¿Ve más de lo que veo yo?**
No. Usa tus mismos permisos, así que ve exactamente lo que ves vos en la aplicación.

**¿Tengo que crear un usuario o una contraseña nueva?**
No. Ingresás con tu usuario de siempre.
