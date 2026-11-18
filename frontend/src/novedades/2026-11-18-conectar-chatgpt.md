# Conectar ChatGPT a Pricing

Área: Gestión

## Resumen ejecutivo

Ahora se puede conectar ChatGPT (cuentas Plus o Pro) a Pricing para hacerle preguntas sobre los datos de la aplicación. Las consultas son de solo lectura y ChatGPT trabaja con los mismos permisos del usuario que lo conecta. Se ingresa con el usuario de siempre y cualquier conexión se puede revocar desde el panel de administración.

## Qué cambia

- ChatGPT puede consultar publicaciones de Mercado Libre, métricas de Mercado Libre, ventas de Mercado Libre y por fuera, la auditoría de stock, y productos con sus precios.
- Solo lectura: no puede cambiar precios, publicaciones ni ningún otro dato.
- Con tus mismos permisos: ve lo mismo que ves vos en la aplicación.
- Para conectarlo hace falta el permiso **mcp.conectar**.
- En **Gestión → Admin → Usuarios → Editar** hay una sección nueva, **Conexiones de IA (MCP)**, con las conexiones activas del usuario y un botón **Revocar**.

## Cómo se usa

1. En ChatGPT, activá **Developer mode** en **Settings → Apps/Connectors → Advanced**.
2. Creá un conector con la dirección `https://<dominio de pricing>/api/mcp` y autenticación **OAuth**.
3. Ingresá a Pricing con tu usuario de siempre y tocá **Permitir**.
4. Preguntale a ChatGPT lo que necesites consultar.

> El paso a paso completo está en **Ayuda → Conectar ChatGPT**.
