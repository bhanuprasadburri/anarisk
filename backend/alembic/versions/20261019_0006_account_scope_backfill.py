"""Account brand-scope backfill: organization-less non-admin users get a personal
organization plus the standard brand "Self".

Public registration previously created accounts with organization_id = NULL, which the
brand scope predicate treats as "no data access". Migration 0006 gives every existing
non-admin account in that state a usable personal scope.

This is an ADDITIVE data migration: it only inserts organizations/brands and sets
users.organization_id. It never updates or deletes existing rows.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-19 00:00:00.000006
"""
import uuid as uuid_mod

from alembic import op
import sqlalchemy as sa

revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.text(
        "SELECT id, email FROM users WHERE organization_id IS NULL AND role::text <> 'administrator'"
    )).fetchall()
    for row in rows:
        org_id = str(uuid_mod.uuid4())
        email_local = (row.email or "user").split("@")[0][:40] or "user"
        bind.execute(
            sa.text(
                """
                INSERT INTO organizations (id, name, slug, description, is_active, created_at, updated_at)
                VALUES (:org_id, 'Personal', :slug, :desc, true, now(), now())
                """
            ),
            {
                "org_id": org_id,
                "slug": f"personal-{email_local}-{org_id[:8]}",
                "desc": "Personal workspace for an individual account (created by scope backfill).",
            },
        )
        bind.execute(
            sa.text(
                """
                INSERT INTO brands (id, organization_id, name, slug, description,
                                    is_active, is_synthetic, created_at, updated_at)
                VALUES (:brand_id, :org_id, 'Self', 'self', :desc, true, false, now(), now())
                """
            ),
            {
                "brand_id": str(uuid_mod.uuid4()),
                "org_id": org_id,
                "desc": "Personal brand scope for an individual account.",
            },
        )
        bind.execute(
            sa.text("UPDATE users SET organization_id = :org_id WHERE id = :user_id"),
            {"org_id": org_id, "user_id": str(row.id)},
        )


def downgrade() -> None:
    # Data backfill: intentionally a no-op. Removing the created organizations/brands
    # would destroy user data that may have been written against them since.
    pass
