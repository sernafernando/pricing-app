"""Create weather_history table

Revision ID: 20260303_weather
Revises: lluvia_001
Create Date: 2026-03-03
"""

import sqlalchemy as sa
from alembic import op

revision = "20260303_weather"
down_revision = "lluvia_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "weather_history",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("temp", sa.Float(), nullable=False),
        sa.Column("feels_like", sa.Float(), nullable=False),
        sa.Column("temp_min", sa.Float(), nullable=False),
        sa.Column("temp_max", sa.Float(), nullable=False),
        sa.Column("humidity", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(100), nullable=False),
        sa.Column("icon", sa.String(10), nullable=False),
        sa.Column("wind_speed", sa.Float(), nullable=False),
        sa.Column("rain_1h", sa.Float(), nullable=False, server_default="0"),
        sa.Column("is_rainy", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("city", sa.String(100), nullable=False),
        sa.Column("lat", sa.Float(), nullable=False),
        sa.Column("lon", sa.Float(), nullable=False),
        sa.Column("weather_dt", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("idx_weather_history_created_at", "weather_history", ["created_at"])
    op.create_index("idx_weather_history_is_rainy", "weather_history", ["is_rainy"])


def downgrade() -> None:
    op.drop_index("idx_weather_history_is_rainy", table_name="weather_history")
    op.drop_index("idx_weather_history_created_at", table_name="weather_history")
    op.drop_table("weather_history")
