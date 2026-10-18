"""OTP hardening: attempts counter on email_verification_tokens.

Signup verification now uses a 6-digit OTP (HMAC-hashed at rest) instead of a long
link token; the attempts column backs the per-code wrong-attempt lockout.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-17 00:00:00.000005
"""
from alembic import op
import sqlalchemy as sa

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'email_verification_tokens',
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
    )


def downgrade() -> None:
    op.drop_column('email_verification_tokens', 'attempts')
