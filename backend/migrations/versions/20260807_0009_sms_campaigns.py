"""Add SAHJONY SMS acquisition campaign tables.

Revision ID: 20260807_0009
Revises: 20260803_0008
Create Date: 2026-08-07
"""

from importlib import import_module
from typing import Sequence, Union

from alembic import op

from app.database import Base

revision: str = "20260807_0009"
down_revision: Union[str, Sequence[str], None] = "20260803_0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = frozenset({
    "sms_smart_lists",
    "sms_message_templates",
    "sms_acquisition_campaigns",
    "sms_campaign_recipients",
})


def _tables():
    import_module("app.sms_campaign_models")
    return [table for table in Base.metadata.sorted_tables if table.name in TABLES]


def upgrade() -> None:
    bind = op.get_bind()
    for table in _tables():
        table.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for table in reversed(_tables()):
        table.drop(bind=bind, checkfirst=True)
