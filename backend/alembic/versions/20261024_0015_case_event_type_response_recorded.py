"""Widen case_events.event_type to include the new response_recorded member.

The case_event_type CHECK constraint was baked into the initial schema with a
hard-coded value list, so enum members added later in Python were rejected by the
database. This rebuilds the constraint from the current Python enum and drops a
legacy constraint name variant that would collide under the naming convention.

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-24
"""
import sqlalchemy as sa
from alembic import op

from app.models.enums import CaseEventType

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None

# The initial schema created this by hand; its stored name already carries the
# convention prefix (ck_<table>_<column>). op.f() marks the name final so alembic
# does not re-apply ck_%(table_name)s_%(constraint_name)s on drop/create.
_CONSTRAINT = "ck_case_events_case_event_type"


def upgrade() -> None:
    op.drop_constraint(op.f(_CONSTRAINT), "case_events", type_="check")
    values = ", ".join(f"'{m.value}'" for m in CaseEventType)
    op.create_check_constraint(
        op.f(_CONSTRAINT),
        "case_events",
        sa.text(f"event_type IN ({values})"),
    )


def downgrade() -> None:
    op.drop_constraint(op.f(_CONSTRAINT), "case_events", type_="check")
    values = ", ".join(f"'{m.value}'" for m in CaseEventType if m is not CaseEventType.RESPONSE_RECORDED)
    op.create_check_constraint(
        op.f(_CONSTRAINT),
        "case_events",
        sa.text(f"event_type IN ({values})"),
    )
