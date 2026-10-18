"""tool_analyses (persisted investigation-tool runs) and background monitoring scheduler
columns + sync-run history (next_run_at/retry_count/last_run_status on monitoring_targets,
monitoring_sync_runs table). The schedule is stored in the database so it survives
restarts and works across multiple worker processes (claims use FOR UPDATE SKIP LOCKED).

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-17 00:00:00.000001
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- tool analyses ----
    op.create_table(
        'tool_analyses',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('organization_id', sa.Uuid(), nullable=True),
        sa.Column('created_by_id', sa.Uuid(), nullable=True),
        sa.Column('tool', sa.String(length=32), nullable=False),
        sa.Column('subject', sa.String(length=255), nullable=False),
        sa.Column('input_summary', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('findings', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('risk_score', sa.Float(), nullable=True),
        sa.Column('severity', sa.String(length=16), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=True),
        sa.Column('methodology_version', sa.String(length=32), nullable=False),
        sa.Column('entity_id', sa.Uuid(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_tool_analyses_organization_id_organizations'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], name=op.f('fk_tool_analyses_created_by_id_users'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['entity_id'], ['digital_entities.id'], name=op.f('fk_tool_analyses_entity_id_digital_entities'), ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_tool_analyses')),
        sa.CheckConstraint("tool IN ('email', 'job_offer', 'social_profile', 'url')", name=op.f('ck_tool_analyses_tool_values')),
    )
    op.create_index(op.f('ix_tool_analyses_org_created'), 'tool_analyses', ['organization_id', 'created_at'], unique=False)
    op.create_index(op.f('ix_tool_analyses_org_tool'), 'tool_analyses', ['organization_id', 'tool'], unique=False)
    op.create_index(op.f('ix_tool_analyses_organization_id'), 'tool_analyses', ['organization_id'], unique=False)
    op.create_index(op.f('ix_tool_analyses_created_by_id'), 'tool_analyses', ['created_by_id'], unique=False)
    op.create_index(op.f('ix_tool_analyses_entity_id'), 'tool_analyses', ['entity_id'], unique=False)

    # ---- background monitoring scheduler ----
    op.add_column('monitoring_targets', sa.Column('next_run_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('monitoring_targets', sa.Column('retry_count', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('monitoring_targets', sa.Column('last_run_status', sa.String(length=16), nullable=True))
    op.create_index('ix_monitoring_targets_due', 'monitoring_targets', ['monitoring_status', 'next_run_at'], unique=False)

    # ---- monitoring sync run history ----
    op.create_table(
        'monitoring_sync_runs',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('target_id', sa.Uuid(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('triggered_by', sa.String(length=16), nullable=False),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('success', 'failed')", name=op.f('ck_monitoring_sync_runs_status_values')),
        sa.CheckConstraint("triggered_by IN ('manual', 'scheduler')", name=op.f('ck_monitoring_sync_runs_triggered_by_values')),
        sa.ForeignKeyConstraint(['target_id'], ['monitoring_targets.id'], name=op.f('fk_monitoring_sync_runs_target_id_monitoring_targets'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_monitoring_sync_runs')),
    )
    op.create_index(op.f('ix_monitoring_sync_runs_target_id'), 'monitoring_sync_runs', ['target_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_monitoring_sync_runs_target_id'), table_name='monitoring_sync_runs')
    op.drop_table('monitoring_sync_runs')
    op.drop_index('ix_monitoring_targets_due', table_name='monitoring_targets')
    op.drop_column('monitoring_targets', 'last_run_status')
    op.drop_column('monitoring_targets', 'retry_count')
    op.drop_column('monitoring_targets', 'next_run_at')
    op.drop_index(op.f('ix_tool_analyses_entity_id'), table_name='tool_analyses')
    op.drop_index(op.f('ix_tool_analyses_created_by_id'), table_name='tool_analyses')
    op.drop_index(op.f('ix_tool_analyses_organization_id'), table_name='tool_analyses')
    op.drop_index(op.f('ix_tool_analyses_org_tool'), table_name='tool_analyses')
    op.drop_index(op.f('ix_tool_analyses_org_created'), table_name='tool_analyses')
    op.drop_table('tool_analyses')
