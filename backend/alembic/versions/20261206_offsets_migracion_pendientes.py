"""offsets_migracion_pendientes: the legacy offsets the migration could not carry over, for review

Revision ID: 20261206_offsets_migracion_pendientes
Revises: 20261205_ml_ops_divergence_quarantine
Create Date: 2026-10-27

sell-in-sell-out T22a. Owner: "lo que no se pueda migrar directo haceme un detalle y guardamelo en una tabla que
mañana lo revisamos y en todo caso los hago cargar a mano". `app.scripts.migrar_offsets_a_sell_out --apply` keeps
one row per offset it did not migrate, with the offset's own detail (scope, amount and currency, dates, caps,
channels, user) and the reason; an offset that migrates on a later run leaves the table.

- `offset_id` is UNIQUE (a re-run updates the row) and has NO foreign key: the detail must survive the offset
  being deleted, which is what the review may decide.
- The money columns keep the legacy `offsets_ganancia` types (double precision), so the review shows the very
  values the offset had.

A new, empty table: no lock on an existing one. The downgrade drops it; both steps are idempotent.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20261206_offsets_migracion_pendientes"
down_revision: Union[str, None] = "20261205_ml_ops_divergence_quarantine"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS offsets_migracion_pendientes (
    id SERIAL PRIMARY KEY,
    offset_id INTEGER NOT NULL,
    tipo_offset VARCHAR(20),
    descripcion VARCHAR(255),
    marca VARCHAR(100),
    categoria VARCHAR(100),
    subcategoria_id INTEGER,
    item_id INTEGER,
    grupo_id INTEGER,
    monto DOUBLE PRECISION,
    porcentaje DOUBLE PRECISION,
    moneda VARCHAR(3),
    tipo_cambio DOUBLE PRECISION,
    fecha_desde DATE,
    fecha_hasta DATE,
    max_unidades INTEGER,
    max_monto_usd DOUBLE PRECISION,
    aplica_ml BOOLEAN,
    aplica_fuera BOOLEAN,
    aplica_tienda_nube BOOLEAN,
    usuario_id INTEGER,
    motivo TEXT NOT NULL,
    avisos TEXT,
    registrado_en TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_offsets_migracion_pendientes_offset_id UNIQUE (offset_id)
)
"""


def upgrade() -> None:
    op.execute(CREATE_TABLE)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS offsets_migracion_pendientes")
