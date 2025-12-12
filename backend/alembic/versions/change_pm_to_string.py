"""change pm to string

Revision ID: change_pm_string
Revises: add_extra_fields_notif
Create Date: 2025-11-27

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'change_pm_string'
down_revision = 'add_extra_fields_notif'
branch_labels = None
depends_on = None


def upgrade():
    # Cambiar el tipo de columna pm de Numeric a String
    op.alter_column('notificaciones', 'pm',
                    type_=sa.String(100),
                    existing_type=sa.Numeric(10, 2),
                    nullable=True)


def downgrade():
    # Revertir a Numeric
    op.alter_column('notificaciones', 'pm',
                    type_=sa.Numeric(10, 2),
                    existing_type=sa.String(100),
                    nullable=True)
