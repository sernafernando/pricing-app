"""compras_041: nullable progress_phase on OC-match jobs

Revision ID: compras_041_oc_match_progress_phase
Revises: compras_040_oc_match
Create Date: 2026-09-21

UX-only stage stamp between extract/match/excel. Status CHECK is unchanged.
down_revision must be the unique alembic head at merge (branch tip
`compras_040_oc_match`; rehang if develop advanced).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "compras_041_oc_match_progress_phase"
down_revision: Union[str, None] = "compras_040_oc_match"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "compras_oc_match_jobs",
        sa.Column("progress_phase", sa.String(length=20), nullable=True),
    )
    op.create_check_constraint(
        "ck_oc_match_jobs_progress_phase",
        "compras_oc_match_jobs",
        "progress_phase IS NULL OR progress_phase IN ('extracting','matching','excel')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_oc_match_jobs_progress_phase",
        "compras_oc_match_jobs",
        type_="check",
    )
    op.drop_column("compras_oc_match_jobs", "progress_phase")
