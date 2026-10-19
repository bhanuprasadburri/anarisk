"""Enable RLS on AnaRisk tables so Supabase browser Data API access is denied by default.

The React client uses Supabase Auth, not the Data API, for application records. FastAPI
uses the trusted PostgreSQL owner connection and applies AnaRisk's existing authorization
rules. No anon/authenticated policies are created: if a table is exposed through the Data
API later, it stays inaccessible until explicit policies are reviewed and added.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-19
"""
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

_TABLES = (
    "audit_logs",
    "brands",
    "brand_references",
    "case_assignments",
    "case_entities",
    "case_escalations",
    "case_events",
    "case_evidence",
    "case_notes",
    "collection_records",
    "data_sources",
    "detection_signals",
    "digital_entities",
    "email_delivery_logs",
    "email_verification_tokens",
    "entity_relationships",
    "evidence_records",
    "feedback",
    "integration_configs",
    "investigation_cases",
    "monitoring_sync_runs",
    "monitoring_targets",
    "notifications",
    "organizations",
    "password_reset_tokens",
    "risk_assessments",
    "tool_analyses",
    "users",
)


def upgrade() -> None:
    for table in _TABLES:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')


def downgrade() -> None:
    # Keep RLS enabled even if the application revision is rolled back. Turning it off
    # could expose application tables through the Supabase Data API.
    pass
