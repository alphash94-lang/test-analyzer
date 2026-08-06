"""Add a durable encrypted KIS access-token cache.

Revision ID: w9l2m3n4o5p6
Revises: v8k1l2m3n4o5
"""

import sqlalchemy as sa
from alembic import op

revision = "w9l2m3n4o5p6"
down_revision = "v8k1l2m3n4o5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "kis_access_tokens",
        sa.Column("credential_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("encrypted_token", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("credential_fingerprint"),
    )


def downgrade() -> None:
    op.drop_table("kis_access_tokens")
