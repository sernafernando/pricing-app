"""tacticals: the header of a brand deal; tactical_id on its lines' engines; hidden groups; per-unit cost bonuses

Revision ID: 20261105_tacticals
Revises: 20261104_catalog_competition_refresh_pending
Create Date: 2026-11-04

Tacticals T1. Owner: "hay que mejorar el sistema de carga de programa (ahora llamado "tactical") y de campaña" and "el
grupo se creaba automáticamente, y no hace falta que el usuario vea los grupos".

- `tacticals`: the header (`app.models.tactical`). `updated_at` is kept by a BEFORE UPDATE trigger on the existing
  `sell_out_set_updated_at()` function (20261105), like the programs'.
- `tactical_id BIGINT NULL` on `sell_out_campanas`, `sell_in_bonos_marca` and `sell_in_compras`, FK ON DELETE
  RESTRICT, indexed, with `tactical_linea SMALLINT NULL`: the 1-based line of the tactical the row was created from
  (a per-product line creates several rows with the same number). CHECK `ck_<table>_tactical_linea`: both NULL, or
  both set with the line >= 1. Every existing row stays NULL: no backfill. The bonus and purchase update triggers do not read
  the column, so setting it queues nothing.
- `offset_grupos.oculto BOOLEAN NOT NULL DEFAULT false`: a group a tactical line creates for its own products.
- `ck_sell_in_bonos_marca_costo_venta` no longer requires `tipo = 'porcentaje'`: a cost bonus may be a fixed ARS amount
  per sold unit (`app.services.sell_in.bonos_costo.unitario`). Still ARS, still brand / category / models.

DOWNGRADE refuses (RAISE, nothing changed) while a tactical or a per-unit cost bonus exists: dropping them would lose
what was loaded or break the restored CHECK. Otherwise it puts 20261212's CHECK back and drops the columns, the
flag and the table.

LOCK NOTE: CREATE TABLE's FK to `usuarios` takes SHARE ROW EXCLUSIVE on `usuarios` until the deploy commits. Each
ADD COLUMN (nullable or constant default: no rewrite) with its FK, and the CHECK swap (validated against the existing
bonuses), take an ACCESS EXCLUSIVE lock on its table, which the `sell_out.drain` and `sell_in.bono` workers read;
CREATE INDEX (not CONCURRENTLY: inside the migration transaction) blocks writes while it builds over a few thousand
rows. Upgrade and downgrade run with `lock_timeout = '5s'` and the deploy is retried; the previous value is saved and
restored because `env.py` runs every pending revision in ONE transaction (same pattern as 20261225). Every step is
idempotent.
"""

from typing import List, Sequence, Union

from alembic import op

revision: str = "20261105_tacticals"
down_revision: Union[str, None] = "20261104_catalog_competition_refresh_pending"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LOCK_TIMEOUT = "5s"

# Also declared by `app.models.tactical` (the schema parity test compares them).
TIPO = "tipo IN ('sell_in', 'sell_out')"
ESTADO = "estado IN ('activo', 'anulado')"
TC_MODO = (
    "(moneda = 'ARS' AND tc_modo IS NULL AND tipo_cambio IS NULL) OR "
    "(moneda = 'USD' AND tc_modo IS NOT NULL AND ("
    "(tc_modo = 'fijo' AND tipo_cambio IS NOT NULL) OR "
    "(tc_modo IN ('dia_venta', 'al_cobro') AND tipo_cambio IS NULL)))"
)
COSTO_VENTA = (
    "(base = 'factura' AND NOT incluye_iva) "
    "OR (base = 'costo_venta' AND moneda = 'ARS' AND alcance IN ('marca', 'categoria', 'modelos'))"
)
# 20261212's, put back by the downgrade.
COSTO_VENTA_PREVIO = (
    "(base = 'factura' AND NOT incluye_iva) "
    "OR (base = 'costo_venta' AND tipo = 'porcentaje' AND moneda = 'ARS' AND alcance IN ('marca', 'categoria', 'modelos'))"
)
TACTICAL_LINEA = "(tactical_id IS NULL AND tactical_linea IS NULL) OR (tactical_id IS NOT NULL AND tactical_linea IS NOT NULL AND tactical_linea >= 1)"
LINEAS = ("sell_out_campanas", "sell_in_bonos_marca", "sell_in_compras")

UPGRADE_TACTICALS = f"""
CREATE TABLE IF NOT EXISTS tacticals (
  id BIGSERIAL PRIMARY KEY,
  tipo VARCHAR(16) NOT NULL,
  nombre VARCHAR(200) NOT NULL,
  marca VARCHAR(100) NOT NULL,
  referencia VARCHAR(200),
  fecha_desde DATE NOT NULL,
  fecha_hasta DATE NOT NULL,
  moneda VARCHAR(3) NOT NULL,
  tc_modo VARCHAR(16),
  tipo_cambio NUMERIC(18, 6),
  incluye_iva BOOLEAN NOT NULL DEFAULT false,
  acumulable BOOLEAN NOT NULL DEFAULT true,
  nota TEXT,
  estado VARCHAR(16) NOT NULL DEFAULT 'activo',
  usuario_id INTEGER NOT NULL REFERENCES usuarios (id) ON DELETE RESTRICT,
  created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
  updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
  CONSTRAINT ck_tacticals_tipo CHECK ({TIPO}),
  CONSTRAINT ck_tacticals_estado CHECK ({ESTADO}),
  CONSTRAINT ck_tacticals_fechas CHECK (fecha_hasta >= fecha_desde),
  CONSTRAINT ck_tacticals_moneda CHECK (moneda IN ('ARS', 'USD')),
  CONSTRAINT ck_tacticals_tc_modo CHECK ({TC_MODO}),
  CONSTRAINT ck_tacticals_tc_positivo CHECK (tipo_cambio IS NULL OR tipo_cambio > 0)
);
CREATE INDEX IF NOT EXISTS ix_tacticals_marca ON tacticals (marca);
CREATE INDEX IF NOT EXISTS ix_tacticals_fechas ON tacticals (fecha_desde, fecha_hasta);
DROP TRIGGER IF EXISTS tacticals_updated_at ON tacticals;
CREATE TRIGGER tacticals_updated_at
BEFORE UPDATE ON tacticals
FOR EACH ROW EXECUTE FUNCTION sell_out_set_updated_at()
"""


def _upgrade_linea(tabla: str) -> str:
    return f"""
ALTER TABLE {tabla} ADD COLUMN IF NOT EXISTS tactical_id BIGINT;
ALTER TABLE {tabla} DROP CONSTRAINT IF EXISTS fk_{tabla}_tactical_id;
ALTER TABLE {tabla} ADD CONSTRAINT fk_{tabla}_tactical_id
  FOREIGN KEY (tactical_id) REFERENCES tacticals (id) ON DELETE RESTRICT;
CREATE INDEX IF NOT EXISTS ix_{tabla}_tactical_id ON {tabla} (tactical_id);
ALTER TABLE {tabla} ADD COLUMN IF NOT EXISTS tactical_linea SMALLINT;
ALTER TABLE {tabla} DROP CONSTRAINT IF EXISTS ck_{tabla}_tactical_linea;
ALTER TABLE {tabla} ADD CONSTRAINT ck_{tabla}_tactical_linea CHECK ({TACTICAL_LINEA})
"""


def _downgrade_linea(tabla: str) -> str:
    return f"""
ALTER TABLE {tabla} DROP CONSTRAINT IF EXISTS ck_{tabla}_tactical_linea;
ALTER TABLE {tabla} DROP COLUMN IF EXISTS tactical_linea;
DROP INDEX IF EXISTS ix_{tabla}_tactical_id;
ALTER TABLE {tabla} DROP CONSTRAINT IF EXISTS fk_{tabla}_tactical_id;
ALTER TABLE {tabla} DROP COLUMN IF EXISTS tactical_id
"""


UPGRADE_GRUPOS = "ALTER TABLE offset_grupos ADD COLUMN IF NOT EXISTS oculto BOOLEAN NOT NULL DEFAULT false"
DOWNGRADE_GRUPOS = "ALTER TABLE offset_grupos DROP COLUMN IF EXISTS oculto"


def _check_costo_venta(expresion: str) -> str:
    return f"""
ALTER TABLE sell_in_bonos_marca
  DROP CONSTRAINT IF EXISTS ck_sell_in_bonos_marca_costo_venta,
  ADD CONSTRAINT ck_sell_in_bonos_marca_costo_venta CHECK ({expresion})
"""


# Fails loudly rather than silently losing what was loaded. Reads only what exists (idempotent).
DOWNGRADE_GUARD = f"""
DO $guard$
BEGIN
  IF to_regclass('tacticals') IS NOT NULL AND EXISTS (SELECT 1 FROM tacticals) THEN
    RAISE EXCEPTION 'downgrade of {revision} refused: tacticals exist';
  END IF;
  IF EXISTS (SELECT 1 FROM sell_in_bonos_marca WHERE base = 'costo_venta' AND tipo = 'por_unidad') THEN
    RAISE EXCEPTION 'downgrade of {revision} refused: per-unit cost bonuses exist';
  END IF;
END
$guard$
"""
DOWNGRADE_TACTICALS = "DROP TABLE IF EXISTS tacticals"  # its indexes and trigger go with it


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
            UPGRADE_TACTICALS,
            *(_upgrade_linea(tabla) for tabla in LINEAS),
            UPGRADE_GRUPOS,
            _check_costo_venta(COSTO_VENTA),
        ]
    )


def downgrade() -> None:
    _run(
        [
            DOWNGRADE_GUARD,
            _check_costo_venta(COSTO_VENTA_PREVIO),
            DOWNGRADE_GRUPOS,
            *(_downgrade_linea(tabla) for tabla in LINEAS),
            DOWNGRADE_TACTICALS,
        ]
    )
