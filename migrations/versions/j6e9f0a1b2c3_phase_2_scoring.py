"""Add explainable Phase 2 filters and scoring evidence.

Revision ID: j6e9f0a1b2c3
Revises: i5d8e9f0a1b2
Create Date: 2026-07-29 14:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "j6e9f0a1b2c3"
down_revision: str | None = "i5d8e9f0a1b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("score_snapshots") as batch_op:
        batch_op.add_column(
            sa.Column(
                "score_scope",
                sa.String(length=40),
                nullable=False,
                server_default="PHASE1_LEGACY",
            )
        )
        batch_op.add_column(
            sa.Column(
                "individual_entry_score",
                sa.Numeric(precision=7, scale=3),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "filter_state",
                sa.String(length=32),
                nullable=False,
                server_default="NOT_VERIFIED",
            )
        )
        batch_op.add_column(
            sa.Column(
                "recommendation_computable",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.add_column(
            sa.Column(
                "missing_core_data",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'[]'"),
            )
        )
        batch_op.add_column(
            sa.Column(
                "explanation",
                sa.Text(),
                nullable=False,
                server_default=("Phase 2 이전 점수 행으로 구성요소 근거가 없습니다."),
            )
        )
        batch_op.create_check_constraint(
            "ck_individual_entry_score_range",
            "individual_entry_score IS NULL OR "
            "(individual_entry_score >= 0 AND "
            "individual_entry_score <= 100)",
        )
        batch_op.alter_column("score_scope", server_default=None)
        batch_op.alter_column("filter_state", server_default=None)
        batch_op.alter_column(
            "recommendation_computable",
            server_default=None,
        )
        batch_op.alter_column("missing_core_data", server_default=None)
        batch_op.alter_column("explanation", server_default=None)

    op.create_table(
        "forced_filter_results",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("score_snapshot_id", sa.Integer(), nullable=False),
        sa.Column("filter_code", sa.String(length=80), nullable=False),
        sa.Column("filter_name", sa.String(length=120), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("is_blocking", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("raw_value", sa.Numeric(precision=30, scale=10)),
        sa.Column("raw_text", sa.Text()),
        sa.Column("source_provider", sa.String(length=120)),
        sa.Column("evidence_date", sa.Date()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["score_snapshot_id"],
            ["score_snapshots.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "score_snapshot_id",
            "filter_code",
            name="uq_forced_filter_snapshot_code",
        ),
    )
    op.create_table(
        "score_components",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("score_snapshot_id", sa.Integer(), nullable=False),
        sa.Column("score_name", sa.String(length=80), nullable=False),
        sa.Column("component_code", sa.String(length=80), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("raw_value", sa.Numeric(precision=30, scale=10)),
        sa.Column("raw_text", sa.Text()),
        sa.Column("normalized_value", sa.Numeric(precision=7, scale=3)),
        sa.Column("weight", sa.Numeric(precision=7, scale=3)),
        sa.Column("contribution", sa.Numeric(precision=7, scale=3)),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("source_kind", sa.String(length=40), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.CheckConstraint(
            "normalized_value IS NULL OR "
            "(normalized_value >= 0 AND normalized_value <= 100)",
            name="ck_score_component_normalized_range",
        ),
        sa.CheckConstraint(
            "weight IS NULL OR weight > 0",
            name="ck_score_component_positive_weight",
        ),
        sa.CheckConstraint(
            "contribution IS NULL OR contribution >= 0",
            name="ck_score_component_nonnegative_contribution",
        ),
        sa.ForeignKeyConstraint(
            ["score_snapshot_id"],
            ["score_snapshots.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "score_snapshot_id",
            "score_name",
            "component_code",
            name="uq_score_component_snapshot_code",
        ),
    )
    op.create_table(
        "valuation_comparisons",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("score_snapshot_id", sa.Integer(), nullable=False),
        sa.Column("metric_code", sa.String(length=80), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("current_value", sa.Numeric(precision=30, scale=10)),
        sa.Column("industry_median", sa.Numeric(precision=30, scale=10)),
        sa.Column("historical_median", sa.Numeric(precision=30, scale=10)),
        sa.Column("industry_percentile", sa.Numeric(precision=7, scale=3)),
        sa.Column("historical_percentile", sa.Numeric(precision=7, scale=3)),
        sa.Column("comparison_level", sa.String(length=40)),
        sa.Column("classification_code", sa.String(length=80)),
        sa.Column("sample_size", sa.Integer(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["score_snapshot_id"],
            ["score_snapshots.id"],
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "industry_percentile IS NULL OR "
            "(industry_percentile >= 0 AND industry_percentile <= 100)",
            name="ck_valuation_industry_percentile_range",
        ),
        sa.CheckConstraint(
            "historical_percentile IS NULL OR "
            "(historical_percentile >= 0 AND historical_percentile <= 100)",
            name="ck_valuation_historical_percentile_range",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "score_snapshot_id",
            "metric_code",
            name="uq_valuation_comparison_snapshot_metric",
        ),
    )


def downgrade() -> None:
    op.drop_table("valuation_comparisons")
    op.drop_table("score_components")
    op.drop_table("forced_filter_results")
    with op.batch_alter_table("score_snapshots") as batch_op:
        batch_op.drop_constraint(
            "ck_individual_entry_score_range",
            type_="check",
        )
        batch_op.drop_column("explanation")
        batch_op.drop_column("missing_core_data")
        batch_op.drop_column("recommendation_computable")
        batch_op.drop_column("filter_state")
        batch_op.drop_column("individual_entry_score")
        batch_op.drop_column("score_scope")
