"""
Paquete `app.events` — SQLAlchemy event listeners registrados al startup.

Cada submódulo agrupa hooks de un dominio (ej: `rrhh_he_hooks` cubre fichadas
modificadas y cambios de turno que disparan recálculo de horas extras).

Importar el módulo es lo que dispara el `@event.listens_for(...)` — por eso
`app/main.py` hace `import app.events.rrhh_he_hooks` ANTES de incluir routers.
"""
