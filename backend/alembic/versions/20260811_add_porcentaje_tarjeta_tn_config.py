"""seed porcentaje_tarjeta_tn into tienda_config

The gap between the card price published on Tienda Nube and the transfer price
used to live in TWO hardcoded literals that had to agree but were never linked:

  * the `* 0.75` "transf." hint in the Tienda/Productos grids, and
  * the `useState(25)` publish default in `TnPublishModal`.

They are inverses of each other (publish does `transf * (1 + P/100)`, the grid
renders the value that syncs back down), so a single source of truth is the
only way they can stay consistent. This key becomes that source.

Seeded at 25 — deliberately NOT 0 — so the Tienda Nube publish default keeps
its current behaviour the moment this lands. `GET /markups-tienda/config/{clave}`
degrades a missing row to 0, so a 0 seed would be indistinguishable from "not
configured" and would silently publish at the bare transfer price.

`markup_web_tarjeta` (the Web Tarjeta column) is a SEPARATE knob and is left
untouched here — the two are expected to hold different values.

Revision ID: 20260811_porcentaje_tarjeta_tn
Revises: compras_039_dac_pata_destino
Create Date: 2026-08-11 00:00:00.000000

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260811_porcentaje_tarjeta_tn"
down_revision = "compras_039_dac_pata_destino"
branch_labels = None
depends_on = None


def upgrade():
    # ON CONFLICT targets the unique index ix_tienda_config_clave created by
    # 20251215_create_tienda_config_table, so re-running is a no-op and an
    # operator who already set the value by hand is never overwritten.
    op.execute("""
        INSERT INTO tienda_config (clave, valor, descripcion)
        VALUES (
            'porcentaje_tarjeta_tn',
            25,
            'Diferencia % entre el precio tarjeta publicado en Tienda Nube y el precio transferencia'
        )
        ON CONFLICT (clave) DO NOTHING;
    """)


def downgrade():
    op.execute("""
        DELETE FROM tienda_config WHERE clave = 'porcentaje_tarjeta_tn';
    """)
