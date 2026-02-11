"""Add offset_flex to pricing_constants

Revision ID: 20260211_offset_flex
Revises: 20260210_asig_tracking
Create Date: 2026-02-11

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260211_offset_flex'
down_revision = '20260210_asig_tracking'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('pricing_constants',
        sa.Column('offset_flex', sa.Numeric(12, 2), nullable=True)
    )


def downgrade():
    op.drop_column('pricing_constants', 'offset_flex')
