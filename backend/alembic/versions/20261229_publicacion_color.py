"""publicacion_color: per-team ML color of one publication (seleccion-por-publicacion S3)

Revision ID: 20261229_publicacion_color
Revises: 20261225_sell_out_programas
Create Date: 2026-11-02

Owner: "los colores lo mismo aplican a todo el producto, eso debería cambiar ahora". Publicaciones ML paints one
publication (MLA) in a team layer. Its effective color is its own row here, otherwise its product's
`producto_color.color_ml` in that layer. `producto_color` is untouched and nothing is migrated: every product keeps
its color, and every publication keeps showing it until someone paints that publication.

- `publicacion_color`: `equipo_id` (FK `equipo.id`), `item_id` VARCHAR(30) (the MLA; no FK, the publications live in
  the ML store database), `color_ml` VARCHAR(20) NOT NULL (unpainting deletes the row), `updated_by` (FK
  `usuarios.id`), `updated_at`. Unique (`equipo_id`, `item_id`); indexed by each FK column and `item_id`.

DOWNGRADE refuses (RAISE, nothing changed) while a row exists: dropping it would silently lose painted colors.

LOCK NOTE: CREATE TABLE with foreign keys to `equipo` and `usuarios` takes SHARE ROW EXCLUSIVE on both until the
deploy transaction commits; writes to them wait meanwhile (bounded by `lock_timeout`, retried by the deploy).
Upgrade and downgrade run with `lock_timeout = '5s'`, saving and restoring the previous value because `env.py` runs
every pending revision in ONE transaction. Every step is idempotent.
"""

from typing import List, Sequence, Union

from alembic import op

revision: str = "20261229_publicacion_color"
down_revision: Union[str, None] = "20261225_sell_out_programas"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LOCK_TIMEOUT = "5s"

UPGRADE = [
    """
    CREATE TABLE IF NOT EXISTS publicacion_color (
      id SERIAL PRIMARY KEY,
      equipo_id INTEGER NOT NULL REFERENCES equipo (id),
      item_id VARCHAR(30) NOT NULL,
      color_ml VARCHAR(20) NOT NULL,
      updated_by INTEGER REFERENCES usuarios (id),
      updated_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
      CONSTRAINT uq_publicacion_color_equipo_item UNIQUE (equipo_id, item_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_publicacion_color_id ON publicacion_color (id)",
    "CREATE INDEX IF NOT EXISTS ix_publicacion_color_equipo_id ON publicacion_color (equipo_id)",
    "CREATE INDEX IF NOT EXISTS ix_publicacion_color_item_id ON publicacion_color (item_id)",
    "CREATE INDEX IF NOT EXISTS ix_publicacion_color_updated_by ON publicacion_color (updated_by)",
]

DOWNGRADE = [
    """
    DO $$
    BEGIN
      -- Nested: one IF with AND still plans the EXISTS, which fails once the table is gone.
      IF to_regclass('publicacion_color') IS NOT NULL THEN
        IF EXISTS (SELECT 1 FROM publicacion_color) THEN
          RAISE EXCEPTION 'publicacion_color has painted publications; clear them before downgrading';
        END IF;
      END IF;
    END
    $$
    """,
    "DROP TABLE IF EXISTS publicacion_color",
]


def _run(statements: List[str]) -> None:
    # Plain SQL (works in offline `--sql` mode); restores the caller's lock_timeout.
    op.execute("SELECT set_config('publicacion_color.lock_timeout_previo', current_setting('lock_timeout'), true)")
    op.execute(f"SELECT set_config('lock_timeout', '{LOCK_TIMEOUT}', true)")
    for statement in statements:
        op.execute(statement)
    op.execute("SELECT set_config('lock_timeout', current_setting('publicacion_color.lock_timeout_previo'), true)")


def upgrade() -> None:
    _run(UPGRADE)


def downgrade() -> None:
    _run(DOWNGRADE)
