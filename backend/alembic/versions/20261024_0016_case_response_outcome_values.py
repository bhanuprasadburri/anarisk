"""Add the value-list CHECK for investigation_cases.response_outcome.

Migration 0014 added the column as a bare VARCHAR(32); every other enum column
(case_status, severity, resolution_outcome, ...) carries a ck_<table>_<enum_name>
CHECK built from its Python enum. This closes the same invariant for
response_outcome so the database rejects values the API can never produce.

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-24
"""
from alembic import op
import sqlalchemy as sa

from app.models.enums import ResponseOutcome

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

# Same shape the metadata convention generates for enum_col(ResponseOutcome, "response_outcome"):
# ck_%(table_name)s_%(constraint_name)s with constraint_name = the enum name.
_CONSTRAINT = "ck_investigation_cases_response_outcome"


def upgrade() -> None:
    values = ", ".join(f"'{m.value}'" for m in ResponseOutcome)
    op.create_check_constraint(
        op.f(_CONSTRAINT),
        "investigation_cases",
        sa.text(f"response_outcome IN ({values})"),
    )


def downgrade() -> None:
    op.drop_constraint(op.f(_CONSTRAINT), "investigation_cases", type_="check")
