"""Add versioned national intelligence tables.

Revision ID: 20260719_0002
Revises: 20260718_0001
Create Date: 2026-07-19

The migration is intentionally idempotent because some existing environments may have
created these tables through SQLAlchemy metadata before Alembic ownership was added.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260719_0002"
down_revision: Union[str, Sequence[str], None] = "20260718_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS property_intelligence_scores (
            id INTEGER PRIMARY KEY,
            organization_id INTEGER NOT NULL,
            lead_id INTEGER NOT NULL,
            property_id INTEGER NOT NULL,
            market_key VARCHAR(140) NOT NULL,
            opportunity_score FLOAT NOT NULL DEFAULT 0,
            distress_score FLOAT NOT NULL DEFAULT 0,
            equity_score FLOAT NOT NULL DEFAULT 0,
            buyer_demand_score FLOAT NOT NULL DEFAULT 0,
            data_confidence FLOAT NOT NULL DEFAULT 0,
            ownership_verified BOOLEAN NOT NULL DEFAULT FALSE,
            projected_assignment_fee FLOAT,
            reasons_json JSON NOT NULL DEFAULT '[]',
            warnings_json JSON NOT NULL DEFAULT '[]',
            source_summary_json JSON NOT NULL DEFAULT '{}',
            calculated_at TIMESTAMP NOT NULL,
            updated_at TIMESTAMP NOT NULL,
            CONSTRAINT uq_property_intelligence_org_property UNIQUE (organization_id, property_id)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_property_intelligence_scores_organization_id ON property_intelligence_scores (organization_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_property_intelligence_scores_lead_id ON property_intelligence_scores (lead_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_property_intelligence_scores_property_id ON property_intelligence_scores (property_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_property_intelligence_scores_market_key ON property_intelligence_scores (market_key)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_property_intelligence_scores_opportunity_score ON property_intelligence_scores (opportunity_score)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_property_intelligence_scores_calculated_at ON property_intelligence_scores (calculated_at)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS national_intelligence_runs (
            id INTEGER PRIMARY KEY,
            organization_id INTEGER NOT NULL,
            status VARCHAR(30) NOT NULL DEFAULT 'running',
            trigger VARCHAR(40) NOT NULL DEFAULT 'manual',
            properties_seen INTEGER NOT NULL DEFAULT 0,
            properties_scored INTEGER NOT NULL DEFAULT 0,
            properties_skipped INTEGER NOT NULL DEFAULT 0,
            high_priority_count INTEGER NOT NULL DEFAULT 0,
            result_json JSON NOT NULL DEFAULT '{}',
            error TEXT,
            started_at TIMESTAMP NOT NULL,
            completed_at TIMESTAMP
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_national_intelligence_runs_organization_id ON national_intelligence_runs (organization_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_national_intelligence_runs_status ON national_intelligence_runs (status)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS national_intelligence_runs")
    op.execute("DROP TABLE IF EXISTS property_intelligence_scores")
