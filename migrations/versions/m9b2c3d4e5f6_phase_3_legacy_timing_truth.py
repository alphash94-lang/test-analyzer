"""Mark legacy Phase 3 metric timing as unverified.

Revision ID: m9b2c3d4e5f6
Revises: l8a1b2c3d4e5
Create Date: 2026-07-29 17:10:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "m9b2c3d4e5f6"
down_revision: str | None = "l8a1b2c3d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    legacy_snapshot_ids = (
        "SELECT id FROM market_regime_snapshots WHERE rule_version = 'phase3-rule-v1'"
    )
    op.execute(
        sa.text(
            "UPDATE market_metric_records SET data_timing = 'UNKNOWN' "
            f"WHERE market_regime_snapshot_id IN ({legacy_snapshot_ids})"
        )
    )
    op.execute(
        sa.text(
            "UPDATE market_contribution_records SET data_timing = 'UNKNOWN' "
            f"WHERE market_regime_snapshot_id IN ({legacy_snapshot_ids})"
        )
    )


def downgrade() -> None:
    legacy_snapshot_ids = (
        "SELECT id FROM market_regime_snapshots WHERE rule_version = 'phase3-rule-v1'"
    )
    op.execute(
        sa.text(
            "UPDATE market_metric_records SET data_timing = 'PREVIOUS_CLOSE' "
            f"WHERE market_regime_snapshot_id IN ({legacy_snapshot_ids})"
        )
    )
    op.execute(
        sa.text(
            "UPDATE market_contribution_records "
            "SET data_timing = 'PREVIOUS_CLOSE' "
            f"WHERE market_regime_snapshot_id IN ({legacy_snapshot_ids})"
        )
    )
