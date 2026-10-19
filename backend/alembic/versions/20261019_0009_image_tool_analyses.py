"""Widen tool_analyses.tool CHECK to allow the new 'image' tool.

ADDITIVE only: the constraint is relaxed from
  tool IN ('email', 'job_offer', 'social_profile', 'url')
to also accept 'image'. No rows are modified or removed.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-19 00:00:00.000009
"""
from alembic import op

revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None

_OLD = "tool IN ('email', 'job_offer', 'social_profile', 'url')"
_NEW = "tool IN ('email', 'job_offer', 'social_profile', 'url', 'image')"


def upgrade() -> None:
    op.drop_constraint(op.f('ck_tool_analyses_tool_values'), 'tool_analyses', type_='check')
    op.create_check_constraint(op.f('ck_tool_analyses_tool_values'), 'tool_analyses', _NEW)


def downgrade() -> None:
    # No-op on purpose: narrowing the CHECK would fail (or force rewriting rows) once any
    # 'image' analysis exists, and rewriting persisted findings would falsify audit history.
    # The widened constraint accepts every pre-upgrade value, so it is forward- and
    # backward-compatible as-is.
    pass
