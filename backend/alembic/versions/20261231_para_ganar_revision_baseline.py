"""para_ganar: persist competition baseline for P5 evaluation

Revision ID: 20261231_para_ganar_revision_baseline
Revises: 20261230_para_ganar_periodicidad_descartado
Create Date: 2026-12-31

Stores rank/price/suggestion_status/in_top/fecha_consulta so later runs
compare current competition state vs the previous evaluation (R1–R3).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261231_para_ganar_revision_baseline"
down_revision: Union[str, None] = "20261230_para_ganar_periodicidad_descartado"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "para_ganar_revision_mla",
        sa.Column("competition_baseline", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("para_ganar_revision_mla", "competition_baseline")
