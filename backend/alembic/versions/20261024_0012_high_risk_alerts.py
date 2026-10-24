"""Persist one high-risk alert per risk assessment.

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-24
"""
from alembic import op
import sqlalchemy as sa

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "high_risk_alerts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("assessment_id", sa.UUID(), nullable=False),
        sa.Column("entity_id", sa.UUID(), nullable=False),
        sa.Column("rule_version", sa.String(length=64), nullable=False),
        sa.Column("risk_score", sa.Float(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["assessment_id"], ["risk_assessments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["entity_id"], ["digital_entities.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("assessment_id", name="uq_high_risk_alert_assessment"),
        sa.CheckConstraint("risk_score >= 0 AND risk_score <= 1", name="risk_range"),
    )
    op.create_index("ix_high_risk_alerts_entity_created", "high_risk_alerts", ["entity_id", sa.text("created_at DESC")])
    op.execute('ALTER TABLE "high_risk_alerts" ENABLE ROW LEVEL SECURITY')


def downgrade() -> None:
    # Keep RLS enabled by dropping the table instead of disabling its protection.
    op.drop_index("ix_high_risk_alerts_entity_created", table_name="high_risk_alerts")
    op.drop_table("high_risk_alerts")
