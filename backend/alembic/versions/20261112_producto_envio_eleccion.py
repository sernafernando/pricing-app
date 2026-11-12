"""producto_envio_eleccion: the shipping cost a PM chose for a product

Revision ID: 20261112_producto_envio_eleccion
Revises: 20261111_sell_in_bono_marca_categoria
Create Date: 2026-11-11

Publicaciones ML S7b: one row per product whose PM chose which shipping cost it uses instead of the MAX of its
active publications' ML list_cost (`max`, `mla` + the publication, `promedio`, `ponderado`). No row means `max`,
today's behavior, so the new table changes nothing until someone chooses. Applied by
`app.services.envio_real_service`.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261112_producto_envio_eleccion"
down_revision: Union[str, None] = "20261111_sell_in_bono_marca_categoria"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("SELECT set_config('lock_timeout', '5s', false)")
    op.create_table(
        "producto_envio_eleccion",
        sa.Column("item_id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("modo", sa.String(length=16), nullable=False),
        sa.Column("mla", sa.String(length=32), nullable=True),
        sa.Column("usuario_id", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("modo IN ('max', 'mla', 'promedio', 'ponderado')", name="ck_producto_envio_eleccion_modo"),
        sa.ForeignKeyConstraint(["item_id"], ["productos_erp.item_id"], name="fk_producto_envio_eleccion_item_id"),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuarios.id"], name="fk_producto_envio_eleccion_usuario_id"),
        sa.PrimaryKeyConstraint("item_id", name="pk_producto_envio_eleccion"),
    )
    op.create_index("ix_producto_envio_eleccion_usuario_id", "producto_envio_eleccion", ["usuario_id"])
    op.execute("SELECT set_config('lock_timeout', '0', false)")


def downgrade() -> None:
    op.drop_index("ix_producto_envio_eleccion_usuario_id", table_name="producto_envio_eleccion")
    op.drop_table("producto_envio_eleccion")
