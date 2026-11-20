"""MCP write layer (delivery 2): guards, plan -> confirm -> apply, audit and undo, shared by the MCP write tools and
the app's "Acciones IA" undo. Every write goes through the app's own endpoints, as the user (app.mcp.loopback)."""
