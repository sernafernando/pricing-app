"""Live definition of the trigger that keeps the history of `etiquetas_envio.logistica_id`.

Every change of a label's logistics (old value IS DISTINCT FROM new) inserts one row in
`etiquetas_envio_logistica_historial`. It is a ROW trigger, so the bulk `query.update` of the mass assignment
records one row per changed label, and no write path can skip it.

Who and source come from transaction-local settings the write path sets before the UPDATE
(`set_config(name, value, true)`):

- `app.logistica_usuario_id`: the panel user (integer);
- `app.logistica_operador_id`: the operator (integer);
- `app.logistica_origen`: asignar / masivo / pistoleado / manual.

A missing, empty or malformed setting is recorded as NULL and never blocks the change: the history must not
make a label write fail. The ids carry no foreign key for the same reason.

The migration `20261203_etiquetas_logistica_historial` installs a frozen copy of `UPGRADE_SQL` and
`DOWNGRADE_SQL`; changing them here requires a new migration (the frozen-copy test enforces it).
"""

from typing import List

FUNCTION = "etiquetas_envio_logistica_historial_registrar"
TRIGGER = "trg_etiquetas_envio_logistica_historial"


def _setting_int(name: str) -> str:
    # At most 9 digits: always fits INTEGER, so a bad value can never raise.
    return (
        f"CASE WHEN current_setting('{name}', true) ~ '^[0-9]{{1,9}}$' "
        f"THEN current_setting('{name}', true)::integer END"
    )


UPGRADE_SQL: List[str] = [
    f"""
CREATE OR REPLACE FUNCTION {FUNCTION}() RETURNS TRIGGER AS $trg$
BEGIN
    INSERT INTO etiquetas_envio_logistica_historial
        (shipping_id, logistica_anterior_id, logistica_nueva_id, usuario_id, operador_id, origen)
    VALUES (
        NEW.shipping_id,
        OLD.logistica_id,
        NEW.logistica_id,
        {_setting_int("app.logistica_usuario_id")},
        {_setting_int("app.logistica_operador_id")},
        NULLIF(current_setting('app.logistica_origen', true), '')
    );
    RETURN NULL;
END;
$trg$ LANGUAGE plpgsql
""",
    f"""
CREATE TRIGGER {TRIGGER}
AFTER UPDATE OF logistica_id ON etiquetas_envio
FOR EACH ROW
WHEN (OLD.logistica_id IS DISTINCT FROM NEW.logistica_id)
EXECUTE FUNCTION {FUNCTION}()
""",
]

DOWNGRADE_SQL: List[str] = [
    f"DROP TRIGGER IF EXISTS {TRIGGER} ON etiquetas_envio",
    f"DROP FUNCTION IF EXISTS {FUNCTION}()",
]
