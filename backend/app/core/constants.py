"""
Constantes globales de la aplicación.

SYSTEM_USERNAME: username del usuario "Sistema" usado por procesos automáticos
(sync ERP, cron jobs, etc.) para que la auditoría no se atribuya a un usuario real.

VARIANZA_TC_THRESHOLD_ARS: umbral en ARS por debajo del cual la varianza de tipo de
cambio (F2) no se considera pendiente ni puede ser resuelta. Usado tanto por
_pedido_response (router) como por resolver_varianza_tc (service).
"""

from decimal import Decimal

SYSTEM_USERNAME = "sistema"

# F2 — Umbral de varianza TC: abs(varianza_tc_neta) debe superar este valor (ARS)
# para que varianza_tc_pendiente=True y el endpoint resolver-varianza-tc actúe.
VARIANZA_TC_THRESHOLD_ARS: Decimal = Decimal("1.00")


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


# The business's own timezone. Timestamps are stored as UTC (`timestamptz`),
# which is right, but a DAY is a local idea: a sale at 22:00 in Buenos Aires
# is already the next day in UTC. Filtering "the 10th" against UTC midnight
# silently moves every evening sale to the following day -- three hours of
# business, every single day, landing on the wrong side of the boundary.
#
# Anything that turns a `YYYY-MM-DD` a human typed into a range MUST resolve
# its midnights here, not in UTC.
BUSINESS_TIMEZONE = "America/Argentina/Buenos_Aires"
