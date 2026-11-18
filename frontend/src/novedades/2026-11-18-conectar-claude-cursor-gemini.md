# Conectar Claude, Cursor y Gemini CLI a Pricing

Área: Gestión

## Resumen ejecutivo

Además de ChatGPT, ahora se puede conectar Pricing a **Claude** (web y escritorio), **Claude Code**, **Cursor** y **Gemini CLI**. Funciona igual que con ChatGPT: solo lectura, con los mismos permisos de quien lo conecta, ingresando con el usuario de siempre, y cualquier conexión se puede revocar desde el panel de administración. La aplicación Gemini (gemini.google.com) y Gemini Enterprise todavía no se pueden conectar.

## Qué cambia

- Se pueden conectar Claude, Claude Code, Cursor y Gemini CLI, además de ChatGPT.
- La pantalla **Conectar con Pricing** ahora muestra adónde vuelve la conexión (por ejemplo **claude.ai**, o **localhost (en esta computadora)** para Claude Code, Cursor y Gemini CLI). Tocá **Permitir** solo si acabás de iniciar vos la conexión.
- Claude Code, Cursor y Gemini CLI quedan conectados en cada computadora por separado.
- Para conectarlas hace falta el mismo permiso de siempre, **mcp.conectar**.

## Cómo se usa

1. Agregá Pricing en tu aplicación de IA con la dirección `https://<dominio de pricing>/api/mcp`. En Cursor y Gemini CLI se usa además un código fijo (`pricing-mcp-cursor` o `pricing-mcp-gemini-cli`).
2. Ingresá a Pricing con tu usuario de siempre y tocá **Permitir**.
3. Preguntale a la IA lo que necesites consultar.

> El paso a paso de cada aplicación está en **Ayuda → Conectar una IA (ChatGPT, Claude, Cursor o Gemini)**.
