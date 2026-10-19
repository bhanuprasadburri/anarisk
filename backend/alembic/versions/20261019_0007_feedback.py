"""Feedback table: user submissions (bugs, feature requests, content issues) with an
authorized admin view.

ADDITIVE only: a new table (plus indexes) — no existing rows or schemas are touched.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-19 00:00:00.000007
"""
from alembic import op
import sqlalchemy as sa

revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'feedback',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('organization_id', sa.Uuid(), nullable=True),
        sa.Column('brand_id', sa.Uuid(), nullable=True),
        sa.Column('category', sa.String(length=32), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('page_ref', sa.String(length=500), nullable=True),
        sa.Column('related_case_id', sa.Uuid(), nullable=True),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_feedback_user_id_users'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_feedback_organization_id_organizations'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['brand_id'], ['brands.id'], name=op.f('fk_feedback_brand_id_brands'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['related_case_id'], ['investigation_cases.id'], name=op.f('fk_feedback_related_case_id_investigation_cases'), ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_feedback')),
        sa.CheckConstraint("category IN ('bug', 'feature', 'content', 'other')", name=op.f('ck_feedback_category_values')),
        sa.CheckConstraint("status IN ('open', 'resolved')", name=op.f('ck_feedback_status_values')),
    )
    op.create_index('ix_feedback_org_created', 'feedback', ['organization_id', sa.text('created_at DESC')], unique=False)
    op.create_index('ix_feedback_status_created', 'feedback', ['status', sa.text('created_at DESC')], unique=False)


def downgrade() -> None:
    op.drop_index('ix_feedback_status_created', table_name='feedback')
    op.drop_index('ix_feedback_org_created', table_name='feedback')
    op.drop_table('feedback')
