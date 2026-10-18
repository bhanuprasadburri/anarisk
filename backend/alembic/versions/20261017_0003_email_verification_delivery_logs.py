"""email verification (users.email_verified_at + email_verification_tokens) and
email_delivery_logs (honest record of every outbound email attempt).

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-17 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- users.email_verified_at ----
    op.add_column('users', sa.Column('email_verified_at', sa.DateTime(timezone=True), nullable=True))

    # ---- email verification tokens (hash-only, single use) ----
    op.create_table(
        'email_verification_tokens',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('token_hash', sa.String(length=128), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_email_verification_tokens_user_id_users'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_email_verification_tokens')),
        sa.UniqueConstraint('token_hash', name=op.f('uq_email_verification_tokens_token_hash')),
    )
    op.create_index(op.f('ix_email_verification_tokens_user'), 'email_verification_tokens', ['user_id'], unique=False)

    # ---- email delivery log ----
    op.create_table(
        'email_delivery_logs',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=True),
        sa.Column('template', sa.String(length=64), nullable=False),
        sa.Column('recipient', sa.String(length=320), nullable=False),
        sa.Column('subject', sa.String(length=255), nullable=False),
        sa.Column('provider', sa.String(length=32), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_email_delivery_logs_user_id_users'), ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_email_delivery_logs')),
        sa.CheckConstraint("status IN ('sent', 'failed', 'skipped')", name=op.f('ck_email_delivery_logs_status_values')),
    )
    op.create_index(op.f('ix_email_delivery_logs_created'), 'email_delivery_logs', ['created_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_email_delivery_logs_created'), table_name='email_delivery_logs')
    op.drop_table('email_delivery_logs')
    op.drop_index(op.f('ix_email_verification_tokens_user'), table_name='email_verification_tokens')
    op.drop_table('email_verification_tokens')
    op.drop_column('users', 'email_verified_at')
