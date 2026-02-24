"""
Constantes globales de la aplicación.

SYSTEM_USERNAME: username del usuario "Sistema" usado por procesos automáticos
(sync ERP, cron jobs, etc.) para que la auditoría no se atribuya a un usuario real.
"""

SYSTEM_USERNAME = "sistema"


def get_system_user_id(db) -> int:
    """
    Obtiene el ID del usuario sistema desde la base de datos.

    Se resuelve dinámicamente (no hardcodeado) porque el ID puede variar
    entre ambientes (dev, staging, production).

    Args:
        db: Sesión de SQLAlchemy

    Returns:
        ID del usuario sistema

    Raises:
        RuntimeError: Si el usuario sistema no existe (correr migración 20260224_system_user)
    """
    from app.models.usuario import Usuario

    usuario = db.query(Usuario).filter(Usuario.username == SYSTEM_USERNAME).first()
    if not usuario:
        raise RuntimeError(f"Usuario sistema '{SYSTEM_USERNAME}' no encontrado. Ejecutar: alembic upgrade head")
    return usuario.id
