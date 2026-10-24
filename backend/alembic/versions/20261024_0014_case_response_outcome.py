"""Track the operational response to a case, separate from its analytical disposition (Round 2 §7).

response_outcome records what was done about a confirmed threat (no action / report drafted /
report submitted / removal observed). "removal_observed" is only meaningful with verification
evidence, so a CHECK constraint requires response_evidence_id for that value.

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-24
"""
from alembic import op
import sqlalchemy as sa

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("investigation_cases", sa.Column("response_outcome", sa.String(length=32), nullable=True))
    op.add_column("investigation_cases", sa.Column("response_outcome_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("investigation_cases", sa.Column("response_outcome_by_id", sa.UUID(), nullable=True))
    op.add_column("investigation_cases", sa.Column("response_evidence_id", sa.UUID(), nullable=True))

    op.create_foreign_key(
        "fk_cases_response_outcome_by", "investigation_cases", "users",
        ["response_outcome_by_id"], ["id"], ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_cases_response_evidence", "investigation_cases", "evidence_records",
        ["response_evidence_id"], ["id"], ondelete="SET NULL",
    )
    op.create_check_constraint(
        op.f("ck_case_removal_evidence"), "investigation_cases",
        "response_outcome <> 'removal_observed' OR response_evidence_id IS NOT NULL",
    )
    op.create_index("ix_cases_response_outcome", "investigation_cases", ["response_outcome"])


def downgrade() -> None:
    op.drop_index("ix_cases_response_outcome", table_name="investigation_cases")
    op.drop_constraint("ck_case_removal_evidence", "investigation_cases", type_="check")
    op.drop_constraint("fk_cases_response_evidence", "investigation_cases", type_="foreignkey")
    op.drop_constraint("fk_cases_response_outcome_by", "investigation_cases", type_="foreignkey")
    op.drop_column("investigation_cases", "response_evidence_id")
    op.drop_column("investigation_cases", "response_outcome_by_id")
    op.drop_column("investigation_cases", "response_outcome_at")
    op.drop_column("investigation_cases", "response_outcome")
