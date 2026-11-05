"""sell in: the manual cost mode's surcharge may reach purchase lines through a pool

Revision ID: 20261106_sell_in_modo_manual
Revises: 20261106_gestion_full_ver
Create Date: 2026-11-06

Owner: "otro permiso aparte para poder setear cantidad y costo a mano [...] un costo a mano que sea el de reposición",
and a typed cost above the product's frozen cost is a signed surcharge (2026-11-02, D6 a of handoffs
`sell-in-costos-propuesta.md`). `20261227_sell_in_modos_producto` let only the manual block's own consumptions be
negative (`CHECK (descuento_ars >= 0 OR modo_id IS NOT NULL)`). A later `ponderado` or `ultimo` row takes the block's
units left into its pool, so a purchase line's consumption carries the pool's (negative) value too.

The sign rule moves from that CHECK into a trigger, because it depends on another table: a negative consumption is
allowed only when its product has a `manual` mode row. The modes are append-only (their triggers), so a row allowed
at insert stays allowed. Every other product still refuses a negative consumption, as before.

LOCK NOTE: dropping a CHECK and creating a trigger on `sell_in_consumos` take brief locks with no table scan; they
run with `lock_timeout = '5s'` like 20261227 (the sell-in drain reads and writes the table), restoring the previous
value.

Downgrade: deletes the negative purchase-line consumptions (they would break the restored CHECK) and puts the CHECK
back. Their sales lose that sell in until each product's next recompute.
"""

from typing import List, Sequence, Union

from alembic import op

revision: str = "20261106_sell_in_modo_manual"
down_revision: Union[str, None] = "20261106_gestion_full_ver"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LOCK_TIMEOUT = "5s"

UPGRADE = [
    """
    CREATE OR REPLACE FUNCTION sell_in_consumos_signo() RETURNS TRIGGER AS $trg$
    BEGIN
        IF NEW.modo_id IS NULL AND NOT EXISTS (
            SELECT 1 FROM sell_in_modos_producto m WHERE m.item_id = NEW.item_id AND m.modo = 'manual'
        ) THEN
            RAISE EXCEPTION 'sell_in_consumos: negative descuento_ars % on item % without a manual cost mode',
                NEW.descuento_ars, NEW.item_id
                USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
    END;
    $trg$ LANGUAGE plpgsql
    """,
    "DROP TRIGGER IF EXISTS trg_sell_in_consumos_signo ON sell_in_consumos",
    # No column list: a column-specific trigger would block dropping `modo_id` in 20261227's downgrade.
    "CREATE TRIGGER trg_sell_in_consumos_signo BEFORE INSERT OR UPDATE ON sell_in_consumos "
    "FOR EACH ROW WHEN (NEW.descuento_ars < 0) EXECUTE FUNCTION sell_in_consumos_signo()",
    "ALTER TABLE sell_in_consumos DROP CONSTRAINT IF EXISTS ck_sell_in_consumos_descuento_no_negativo",
]

DOWNGRADE = [
    "DELETE FROM sell_in_consumos WHERE descuento_ars < 0 AND modo_id IS NULL",
    "ALTER TABLE sell_in_consumos DROP CONSTRAINT IF EXISTS ck_sell_in_consumos_descuento_no_negativo",
    "ALTER TABLE sell_in_consumos ADD CONSTRAINT ck_sell_in_consumos_descuento_no_negativo "
    "CHECK (descuento_ars >= 0 OR modo_id IS NOT NULL)",
    "DROP TRIGGER IF EXISTS trg_sell_in_consumos_signo ON sell_in_consumos",
    "DROP FUNCTION IF EXISTS sell_in_consumos_signo()",
]


def _run(statements: List[str]) -> None:
    op.execute("SELECT set_config('sell_in_modo_manual.lock_timeout_previo', current_setting('lock_timeout'), true)")
    op.execute(f"SELECT set_config('lock_timeout', '{LOCK_TIMEOUT}', true)")
    for statement in statements:
        op.execute(statement)
    op.execute("SELECT set_config('lock_timeout', current_setting('sell_in_modo_manual.lock_timeout_previo'), true)")


def upgrade() -> None:
    _run(UPGRADE)


def downgrade() -> None:
    _run(DOWNGRADE)
