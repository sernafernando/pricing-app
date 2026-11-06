"""sell in: a cost bonus over a total split across its products (sell_in_bonos_marca.monto_total, sell_in_bono_repartos)

Revision ID: 20261108_sell_in_bono_monto_total
Revises: 20261107_sell_out_reparto_criterio
Create Date: 2026-11-06

Tactical monto total (S4). Owner, on sell in: "sí, es para los dos"; the orchestrator: "Negative total is rejected for
sell in with a clear validation message (descuento_ars >= 0 stays)", down_revision = the sell out reparto_criterio
migration.

- `sell_in_bonos_marca.tipo` may be `monto_total` (`ck_sell_in_bonos_marca_tipo` rewritten); such a bonus carries no
  `monto_unit` nor `porcentaje` (`ck_sell_in_bonos_marca_monto_segun_tipo` rewritten).
- `monto_total NUMERIC(18, 2) NULL` and `reparto_criterio VARCHAR(16) NULL` (sell out's vocabulary: `iguales`,
  `unidades`, `costo`). CHECK `ck_sell_in_bonos_marca_monto_total`: a `monto_total` bonus has a total > 0, a criterion,
  `base = 'costo_venta'` and no cap (the total is its cap); any other bonus has neither. Every existing bonus stays
  NULL in both.
- `sell_in_bono_repartos (bono_id, item_id, monto > 0)`: the fixed shares of an `iguales` / `costo` bonus, one per
  product, CASCADE with the bonus. `item_id` has no FK to `productos_erp`, like `sell_in_bono_items`. An `unidades`
  bonus stores none (`app.services.sell_in.bonos_costo` spreads its total over every unit).

No trigger changes: the app queues a total bonus whose total, criterion or shares change (`bonos_crud`); the bonus
insert trigger already queues a new one.

DOWNGRADE refuses (RAISE, nothing changed) while a `monto_total` bonus exists: dropping its columns would leave a bonus
the engine cannot read. Otherwise it drops the table, the CHECK and the columns and puts back the previous CHECKs.

LOCK NOTE: ADD COLUMN (nullable, no default: no rewrite), the CHECK rewrites (validated over a few hundred bonuses) and
the new table's FK take an ACCESS EXCLUSIVE lock on `sell_in_bonos_marca`, which the `sell_in.bono` worker reads.
Upgrade and downgrade run with `lock_timeout = '5s'` and the deploy is retried; the previous value is saved and
restored because `env.py` runs every pending revision in ONE transaction (same pattern as
20261107_sell_out_reparto_criterio). Every step is idempotent.
"""

from typing import List, Sequence, Union

from alembic import op

revision: str = "20261108_sell_in_bono_monto_total"
down_revision: Union[str, Sequence[str], None] = "20261107_sell_out_reparto_criterio"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LOCK_TIMEOUT = "5s"

_TABLA = "sell_in_bonos_marca"

TIPO_ANTES = "tipo IN ('por_unidad', 'porcentaje')"
TIPO = "tipo IN ('por_unidad', 'porcentaje', 'monto_total')"
MONTO_SEGUN_TIPO_ANTES = (
    "(tipo = 'por_unidad' AND monto_unit IS NOT NULL AND monto_unit > 0 AND porcentaje IS NULL) "
    "OR (tipo = 'porcentaje' AND porcentaje IS NOT NULL AND porcentaje > 0 AND porcentaje <= 100 "
    "AND monto_unit IS NULL)"
)
MONTO_SEGUN_TIPO = MONTO_SEGUN_TIPO_ANTES + " OR (tipo = 'monto_total' AND monto_unit IS NULL AND porcentaje IS NULL)"
MONTO_TOTAL = (
    "(tipo = 'monto_total' AND monto_total IS NOT NULL AND monto_total > 0 "
    "AND reparto_criterio IS NOT NULL AND reparto_criterio IN ('iguales', 'unidades', 'costo') "
    "AND base = 'costo_venta' "
    "AND tope_unidades IS NULL AND tope_monto IS NULL) "
    "OR (tipo <> 'monto_total' AND monto_total IS NULL AND reparto_criterio IS NULL)"
)


def _check(nombre: str, expresion: str) -> List[str]:
    return [
        f"ALTER TABLE {_TABLA} DROP CONSTRAINT IF EXISTS {nombre}",
        f"ALTER TABLE {_TABLA} ADD CONSTRAINT {nombre} CHECK ({expresion})",
    ]


UPGRADE = [
    f"ALTER TABLE {_TABLA} ADD COLUMN IF NOT EXISTS monto_total NUMERIC(18, 2)",
    f"ALTER TABLE {_TABLA} ADD COLUMN IF NOT EXISTS reparto_criterio VARCHAR(16)",
    *_check("ck_sell_in_bonos_marca_tipo", TIPO),
    *_check("ck_sell_in_bonos_marca_monto_segun_tipo", MONTO_SEGUN_TIPO),
    *_check("ck_sell_in_bonos_marca_monto_total", MONTO_TOTAL),
    """
CREATE TABLE IF NOT EXISTS sell_in_bono_repartos (
  id BIGSERIAL PRIMARY KEY,
  bono_id BIGINT NOT NULL REFERENCES sell_in_bonos_marca (id) ON DELETE CASCADE,
  item_id INTEGER NOT NULL,
  monto NUMERIC(18, 2) NOT NULL,
  CONSTRAINT uq_sell_in_bono_repartos_bono_item UNIQUE (bono_id, item_id),
  CONSTRAINT ck_sell_in_bono_repartos_monto_positivo CHECK (monto > 0)
)
""",
]

DOWNGRADE_GUARD = f"""
DO $guard$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = current_schema() AND table_name = '{_TABLA}' AND column_name = 'monto_total'
  ) THEN
    IF EXISTS (SELECT 1 FROM {_TABLA} WHERE tipo = 'monto_total') THEN
      RAISE EXCEPTION 'downgrade of {revision} refused: sell-in bonuses of tipo monto_total exist';
    END IF;
  END IF;
END
$guard$
"""

DOWNGRADE = [
    DOWNGRADE_GUARD,
    "DROP TABLE IF EXISTS sell_in_bono_repartos",
    f"ALTER TABLE {_TABLA} DROP CONSTRAINT IF EXISTS ck_sell_in_bonos_marca_monto_total",
    *_check("ck_sell_in_bonos_marca_monto_segun_tipo", MONTO_SEGUN_TIPO_ANTES),
    *_check("ck_sell_in_bonos_marca_tipo", TIPO_ANTES),
    f"ALTER TABLE {_TABLA} DROP COLUMN IF EXISTS reparto_criterio",
    f"ALTER TABLE {_TABLA} DROP COLUMN IF EXISTS monto_total",
]


def _run(statements: List[str]) -> None:
    # Plain SQL (works in offline `--sql` mode); restores the caller's lock_timeout.
    op.execute("SELECT set_config('sell_in_bono_total.lock_timeout_previo', current_setting('lock_timeout'), true)")
    op.execute(f"SELECT set_config('lock_timeout', '{LOCK_TIMEOUT}', true)")
    for statement in statements:
        op.execute(statement)
    op.execute("SELECT set_config('lock_timeout', current_setting('sell_in_bono_total.lock_timeout_previo'), true)")


def upgrade() -> None:
    _run(UPGRADE)


def downgrade() -> None:
    _run(DOWNGRADE)
