"""rma_borrar_revisado: who and when reviewed a case marked "para borrar pedido"

Revision ID: 20261230_rma_borrar_revisado
Revises: 20261229_publicacion_color
Create Date: 2026-11-03

Owner: "una vista sencilla de rma donde se vean los pedidos que se marcan para borrar ... y que tenga un tilde cuando
ya se revisó para que no aparezca más". Two nullable columns on `rma_casos`: `borrar_revisado_at` (TIMESTAMPTZ) and
`borrar_revisado_por_id` (FK `usuarios.id`, indexed). Existing rows stay null, so every marked case starts pending.

LOCK NOTE: ADD COLUMN (nullable, no default) is metadata-only, but it and the FK take ACCESS EXCLUSIVE on
`rma_casos` and SHARE ROW EXCLUSIVE on `usuarios` until the deploy transaction commits. Upgrade and downgrade run with
`lock_timeout = '5s'`, saving and restoring the previous value because `env.py` runs every pending revision in ONE
transaction. Every step is idempotent. Downgrade drops the review marks (they only hide rows from a view).
"""

from typing import List, Sequence, Union

from alembic import op

revision: str = "20261230_rma_borrar_revisado"
down_revision: Union[str, None] = "20261229_publicacion_color"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LOCK_TIMEOUT = "5s"

UPGRADE = [
    "ALTER TABLE rma_casos ADD COLUMN IF NOT EXISTS borrar_revisado_at TIMESTAMPTZ",
    "ALTER TABLE rma_casos ADD COLUMN IF NOT EXISTS borrar_revisado_por_id INTEGER REFERENCES usuarios (id)",
    "CREATE INDEX IF NOT EXISTS ix_rma_casos_borrar_revisado_por_id ON rma_casos (borrar_revisado_por_id)",
]

DOWNGRADE = [
    "DROP INDEX IF EXISTS ix_rma_casos_borrar_revisado_por_id",
    "ALTER TABLE rma_casos DROP COLUMN IF EXISTS borrar_revisado_por_id",
    "ALTER TABLE rma_casos DROP COLUMN IF EXISTS borrar_revisado_at",
]


def _run(statements: List[str]) -> None:
    # Plain SQL (works in offline `--sql` mode); restores the caller's lock_timeout.
    op.execute("SELECT set_config('rma_borrar_revisado.lock_timeout_previo', current_setting('lock_timeout'), true)")
    op.execute(f"SELECT set_config('lock_timeout', '{LOCK_TIMEOUT}', true)")
    for statement in statements:
        op.execute(statement)
    op.execute("SELECT set_config('lock_timeout', current_setting('rma_borrar_revisado.lock_timeout_previo'), true)")


def upgrade() -> None:
    _run(UPGRADE)


def downgrade() -> None:
    _run(DOWNGRADE)
