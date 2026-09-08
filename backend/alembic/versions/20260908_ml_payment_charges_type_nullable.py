"""ml_payment_charges.type is nullable -- ML sends it null

Order 4430760076 carries a `meli_fee` charge with no `type` at all (older
data). While the column was NOT NULL the mapper rejected that charge,
`map_payment` returned a MappingError, and the WHOLE payment was dropped:
the sale showed no net at all, forever, because one line of six was
missing one field.

The seller-vs-buyer predicate already reads a missing type as "not one of
the buyer's types", which is the safe side -- an untyped charge counts as
ours rather than silently leaving the money out.

Revision ID: 20260908_ml_payment_charges_type_nullable
Revises: 20260907_drop_ml_iibb_aliquots
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260908_ml_payment_charges_type_nullable"
down_revision: Union[str, None] = "20260907_drop_ml_iibb_aliquots"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("ml_payment_charges", "type", existing_type=sa.String(length=30), nullable=True)


def downgrade() -> None:
    # Reversible only while no untyped row exists; that is the state this
    # migration was written to leave behind, not one to assume.
    op.alter_column("ml_payment_charges", "type", existing_type=sa.String(length=30), nullable=False)
