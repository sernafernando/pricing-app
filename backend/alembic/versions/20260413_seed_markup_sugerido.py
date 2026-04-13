"""seed markup_sugerido from existing markup_porcentaje values

Revision ID: 20260413_seed_sug
Revises: 20260413_perm_sug
Create Date: 2026-04-13
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260413_seed_sug"
down_revision = "20260413_perm_sug"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Copiar markup_porcentaje a markup_sugerido donde aún es NULL
    op.execute(
        """
        UPDATE markups_tienda_brand
        SET markup_sugerido = markup_porcentaje
        WHERE markup_sugerido IS NULL
        """
    )
    op.execute(
        """
        UPDATE markups_tienda_producto
        SET markup_sugerido = markup_porcentaje
        WHERE markup_sugerido IS NULL
        """
    )


def downgrade() -> None:
    # Volver a NULL los que copiamos
    op.execute("UPDATE markups_tienda_brand SET markup_sugerido = NULL")
    op.execute("UPDATE markups_tienda_producto SET markup_sugerido = NULL")
