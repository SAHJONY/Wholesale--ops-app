"""Move every remaining application table under Alembic ownership.

Revision ID: 20260721_0004
Revises: 20260719_0003
Create Date: 2026-07-21

Older installations may already have some or all of these tables because startup
previously called ``Base.metadata.create_all``.  ``checkfirst`` makes this revision
safe for those installations while still creating a complete schema in a fresh
database.  The frozen table allow-list prevents future model additions from being
silently included in this historical revision.
"""

from importlib import import_module
from typing import Sequence, Union

from alembic import op

from app.database import Base

revision: str = "20260721_0004"
down_revision: Union[str, Sequence[str], None] = "20260719_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

MODEL_MODULES = (
    "app.models",
    "app.auth_models",
    "app.event_models",
    "app.intelligence_models",
    "app.integration_hub_models",
    "app.integration_reliability_models",
    "app.acquisition_intake_models",
    "app.acquisition_worker_models",
    "app.county_queue_models",
    "app.compliance_models",
    "app.outbound_models",
    "app.deal_execution_models",
    "app.closing_command_models",
    "app.disposition_models",
)

TABLES = frozenset(
    """acquisition_automation_runs acquisition_import_batches acquisition_runs
    agent_runs api_credentials app_users approvals assignment_selections
    business_events buyer_offers buyers calls campaigns canonical_entities
    closing_issues closing_items closing_milestones compliance_decisions
    contact_consents contact_suppressions contract_packets
    county_verification_cases crm_activities deal_buyer_matches deal_documents
    deals disposition_campaigns dnc_checks earnest_money_records event_deliveries
    event_subscriptions follow_up_tasks funding_records integration_health_checks
    integration_operation_runs integration_reliability_alerts
    integration_reliability_runs intelligence_conflicts intelligence_facts leads
    memberships offers ops_tasks organizations outbound_requests
    password_reset_codes properties title_orders user_passwords
    workspace_entities""".split()
)


def _load_tables():
    for module_name in MODEL_MODULES:
        import_module(module_name)
    found = TABLES.intersection(Base.metadata.tables)
    missing = TABLES - found
    if missing:
        raise RuntimeError(f"Migration model tables are missing: {sorted(missing)}")
    return [table for table in Base.metadata.sorted_tables if table.name in TABLES]


def upgrade() -> None:
    bind = op.get_bind()
    for table in _load_tables():
        table.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for table in reversed(_load_tables()):
        table.drop(bind=bind, checkfirst=True)
