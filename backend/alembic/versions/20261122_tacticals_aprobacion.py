"""tacticals approval: the 'pendiente' state on tacticals and their line engines, who approved, tacticals.aprobar

Revision ID: 20261122_tacticals_aprobacion
Revises: 20261129_costo_si_compras_sospechosas
Create Date: 2026-11-22

Owner (L30): "también hay que hacer un sistema de validación para las cargas de los tacticals, tienen que quedar con
un filtro de pendientes de aprobación para que alejandro los revise y los apruebe y que no apliquen de una". A new
load starts `pendiente` and applies to nothing until it is approved (`app.services.tacticals.aprobar`).

- `tacticals.estado` gains `'pendiente'` (CHECK `ck_tacticals_estado`), and two columns: `aprobado_por` (FK
  `usuarios` ON DELETE RESTRICT, indexed) and `aprobado_at` (timestamptz). Both NULL: every existing tactical keeps
  its state and reads as approved before approval existed (S7).
- `sell_in_bonos_marca`, `sell_in_compras` and `sell_out_campanas`: the `estado` CHECK gains `'pendiente'`. Every
  money reader already takes only `estado = 'activa'`, so a pending line applies to nothing. No row changes.
- Permission `tacticals.aprobar`, seeded like `compras_022_permiso_aprobar_nc`: granted to NO role. It is opt-in
  (`permisos_service.OPT_IN_PERMISSION_CODES`): a SUPERADMIN gets it only through a per-user override (L31: "lo más
  probable es que el permiso se lo de a alejandro solo"). The migration does not touch users.

DOWNGRADE refuses (RAISE, nothing changed) while a pending tactical or line exists: the restored CHECKs would reject
it. Otherwise it removes the permission (with its grants and overrides), the columns and puts the CHECKs back.

LOCK NOTE: each CHECK swap (validated against the table's rows) and the ADD COLUMN with its FK take an ACCESS
EXCLUSIVE lock on their table, which the `sell_out.drain` and `sell_in.bono` workers read, for as long as the
validation scan takes (a few thousand rows). Upgrade and downgrade run with `lock_timeout = '5s'` and the deploy is
retried; the previous value is saved and restored (same pattern as 20261105_tacticals). Every step is idempotent.
"""

from typing import List, Sequence, Union

from alembic import op

revision: str = "20261122_tacticals_aprobacion"
down_revision: Union[str, None] = "20261129_costo_si_compras_sospechosas"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LOCK_TIMEOUT = "5s"

# Also declared by `app.models.tactical` / `app.models.sell_in` / `app.models.sell_out` (the parity tests compare).
ESTADO_TACTICAL = "estado IN ('activo', 'anulado', 'pendiente')"
ESTADO_TACTICAL_PREVIO = "estado IN ('activo', 'anulado')"
ESTADO_LINEA = "estado IN ('activa', 'anulada', 'pendiente')"
ESTADO_LINEA_PREVIO = "estado IN ('activa', 'anulada')"
LINEAS = ("sell_in_bonos_marca", "sell_in_compras", "sell_out_campanas")

CODIGO = "tacticals.aprobar"
PERMISO = {
    "codigo": CODIGO,
    "nombre": "Aprobar tacticals",
    "descripcion": (
        "Aprobar un tactical cargado (y los bonos, compras y campañas de sell in / sell out cargados sueltos): "
        "hasta que se aprueba no aplica a nada. No lo recibe ningún rol ni el superadmin: se da por usuario."
    ),
}


def _check(tabla: str, nombre: str, expresion: str) -> str:
    return (
        f"ALTER TABLE {tabla} DROP CONSTRAINT IF EXISTS {nombre}; "
        f"ALTER TABLE {tabla} ADD CONSTRAINT {nombre} CHECK ({expresion})"
    )


UPGRADE_TACTICALS = """
ALTER TABLE tacticals ADD COLUMN IF NOT EXISTS aprobado_por INTEGER NULL;
ALTER TABLE tacticals ADD COLUMN IF NOT EXISTS aprobado_at TIMESTAMP WITH TIME ZONE NULL;
DO $fk$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'tacticals_aprobado_por_fkey'
                 AND connamespace = current_schema()::regnamespace) THEN
    ALTER TABLE tacticals ADD CONSTRAINT tacticals_aprobado_por_fkey
      FOREIGN KEY (aprobado_por) REFERENCES usuarios (id) ON DELETE RESTRICT;
  END IF;
END
$fk$;
CREATE INDEX IF NOT EXISTS ix_tacticals_aprobado_por ON tacticals (aprobado_por)
"""

UPGRADE_PERMISO = f"""
INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico, created_at)
VALUES ('{CODIGO}', '{PERMISO["nombre"]}', '{PERMISO["descripcion"]}', 'productos', 85, true, NOW())
ON CONFLICT (codigo) DO NOTHING
"""

DOWNGRADE_GUARD = f"""
DO $guard$
BEGIN
  IF EXISTS (SELECT 1 FROM tacticals WHERE estado = 'pendiente')
     OR EXISTS (SELECT 1 FROM sell_in_bonos_marca WHERE estado = 'pendiente')
     OR EXISTS (SELECT 1 FROM sell_in_compras WHERE estado = 'pendiente')
     OR EXISTS (SELECT 1 FROM sell_out_campanas WHERE estado = 'pendiente') THEN
    RAISE EXCEPTION 'downgrade of {revision} refused: loads pending approval exist';
  END IF;
END
$guard$
"""

DOWNGRADE_PERMISO = [
    f"DELETE FROM roles_permisos_base WHERE permiso_id IN (SELECT id FROM permisos WHERE codigo = '{CODIGO}')",
    f"DELETE FROM usuarios_permisos_override WHERE permiso_id IN (SELECT id FROM permisos WHERE codigo = '{CODIGO}')",
    f"DELETE FROM permisos WHERE codigo = '{CODIGO}'",
]

DOWNGRADE_TACTICALS = """
DROP INDEX IF EXISTS ix_tacticals_aprobado_por;
ALTER TABLE tacticals DROP COLUMN IF EXISTS aprobado_at;
ALTER TABLE tacticals DROP COLUMN IF EXISTS aprobado_por
"""


def _run(statements: List[str]) -> None:
    # Plain SQL (works in offline `--sql` mode); restores the caller's lock_timeout.
    op.execute("SELECT set_config('tacticals.lock_timeout_previo', current_setting('lock_timeout'), true)")
    op.execute(f"SELECT set_config('lock_timeout', '{LOCK_TIMEOUT}', true)")
    for statement in statements:
        op.execute(statement)
    op.execute("SELECT set_config('lock_timeout', current_setting('tacticals.lock_timeout_previo'), true)")


def upgrade() -> None:
    _run(
        [
            _check("tacticals", "ck_tacticals_estado", ESTADO_TACTICAL),
            UPGRADE_TACTICALS,
            *(_check(tabla, f"ck_{tabla}_estado", ESTADO_LINEA) for tabla in LINEAS),
            UPGRADE_PERMISO,
        ]
    )


def downgrade() -> None:
    _run(
        [
            DOWNGRADE_GUARD,
            *DOWNGRADE_PERMISO,
            *(_check(tabla, f"ck_{tabla}_estado", ESTADO_LINEA_PREVIO) for tabla in LINEAS),
            DOWNGRADE_TACTICALS,
            _check("tacticals", "ck_tacticals_estado", ESTADO_TACTICAL_PREVIO),
        ]
    )
