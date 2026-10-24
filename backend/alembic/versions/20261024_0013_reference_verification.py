"""Record who verified an official brand asset and when (Round 2 §2).

Adds verification provenance to brand_references: the registering/verifying user,
the moment of verification, and a human-readable verification source. All columns
are nullable so pre-existing and connector-owned assets stay valid.

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-24
"""
from alembic import op
import sqlalchemy as sa

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("brand_references", sa.Column("verified_by", sa.UUID(), nullable=True))
    op.add_column("brand_references", sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("brand_references", sa.Column("verification_source", sa.Text(), nullable=True))
    op.create_foreign_key(
        "fk_brand_references_verified_by", "brand_references", "users", ["verified_by"], ["id"], ondelete="SET NULL"
    )


def downgrade() -> None:
    op.drop_constraint("fk_brand_references_verified_by", "brand_references", type_="foreignkey")
    op.drop_column("brand_references", "verification_source")
    op.drop_column("brand_references", "verified_at")
    op.drop_column("brand_references", "verified_by")
