"""merge tickets and logistica heads

Revision ID: 20251226_merge_01
Revises: 20251224_180000, 20251226_tickets_01
Create Date: 2025-12-26 12:36:19.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20251226_merge_01'
down_revision = ('20251224_180000', '20251226_tickets_01')
branch_labels = None
depends_on = None


def upgrade():
    # Merge migration - no changes needed
    pass


def downgrade():
    # Merge migration - no changes needed
    pass
