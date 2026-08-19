"""Reconcile runtime tables that may have been created outside Alembic.

Revision ID: 20260819_0013
Revises: 20260816_0012
Create Date: 2026-08-19

This migration is intentionally idempotent. Earlier production releases used
runtime metadata bootstrap for some tables while Alembic remained behind. The
result was a database that could contain newer tables while alembic_version
still reported an older revision. Import every post-0004 model family and use
checkfirst=True so both clean installs and drifted installs converge on the same
schema without dropping data.
"""

from importlib import import_module
from typing import Sequence, Union

from alembic import op

from app.database import Base

revision: str = "20260819_0013"
down_revision: Union[str, Sequence[str], None] = "20260816_0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

MODULES = (
    "app.business_os_models",
    "app.cash_buyer_models",
    "app.sms_models",
    "app.voice_models",
    "app.sms_agentic_models",
    "app.sms_campaign_models",
    "app.sms_scheduling_models",
    "app.sms_attribution_models",
    "app.title_company_models",
)

TABLES = frozenset({
    "business_plans",
    "business_transactions",
    "business_obligations",
    "operating_playbooks",
    "cash_buyer_candidates",
    "sms_messages",
    "voice_calls",
    "sms_conversation_states",
    "sms_smart_lists",
    "sms_message_templates",
    "sms_acquisition_campaigns",
    "sms_campaign_recipients",
    "sms_appointment_requests",
    "sms_follow_up_jobs",
    "sms_attribution_events",
    "title_company_partners",
    "title_company_deal_matches",
})


def _tables():
    for module in MODULES:
        import_module(module)
    return [table for table in Base.metadata.sorted_tables if table.name in TABLES]


def upgrade() -> None:
    bind = op.get_bind()
    for table in _tables():
        table.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    # Reconciliation must not destroy tables that may predate Alembic tracking.
    # A downgrade only moves the revision marker; destructive rollback requires
    # an explicit, separately reviewed migration.
    pass
