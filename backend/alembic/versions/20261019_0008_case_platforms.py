"""Add investigation_cases.platforms (JSONB array of platform keys).

ADDITIVE only: one new NOT NULL column with an '[]' default — no existing rows are modified
beyond receiving the empty default, and no data is dropped.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-19 00:00:00.000008
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'investigation_cases',
        sa.Column('platforms', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='[]'),
    )


def downgrade() -> None:
    # Dropping the column loses the platform tags an investigation recorded.
    op.drop_column('investigation_cases', 'platforms')
