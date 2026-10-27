"""Who and source of a change of `etiquetas_envio.logistica_id`, for the history trigger.

The trigger (`logistica_historial_sql`) reads three settings when it records a change. Every write path of
`logistica_id` calls `marcar_origen_logistica` in the same transaction and before the UPDATE reaches the
database (before assigning the column or running the bulk update).

The settings are transaction-local (`set_config(..., true)`): they end with the commit or rollback. A
session-level setting would stay on the pooled connection and credit later changes to this user and source.
"""

from typing import Literal, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

OrigenLogistica = Literal["asignar", "masivo", "pistoleado", "manual", "deshacer"]

_SET_CONFIG = text(
    "SELECT set_config('app.logistica_usuario_id', :usuario_id, true), "
    "set_config('app.logistica_operador_id', :operador_id, true), "
    "set_config('app.logistica_origen', :origen, true)"
)


def marcar_origen_logistica(
    db: Session,
    origen: OrigenLogistica,
    usuario_id: Optional[int],
    operador_id: Optional[int] = None,
) -> None:
    """Sets who (`usuario_id`, `operador_id`) and `origen` for the logistics changes of the current transaction.

    No-op off Postgres (SQLite unit tests have neither `set_config` nor the trigger).
    """
    if db.get_bind().dialect.name != "postgresql":
        return
    db.execute(
        _SET_CONFIG,
        {
            "usuario_id": "" if usuario_id is None else str(usuario_id),
            "operador_id": "" if operador_id is None else str(operador_id),
            "origen": origen,
        },
    )
