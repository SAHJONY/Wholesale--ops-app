"""Add SAHJONY SMS attribution events.

Revision ID: 20260808_0011
Revises: 20260808_0010
Create Date: 2026-08-08
"""

from importlib import import_module
from typing import Sequence, Union

from alembic import op

from app.database import Base

revision: str = "20260808_0011"
down_revision: Union[str, Sequence[str], None] = "20260808_0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = frozenset({"sms_attribution_events"})


def _tables():
    import_module("app.sms_campaign_models")
    import_module("app.sms_attribution_models")
    return [table for table in Base.metadata.sorted_tables if table.name in TABLES]


def upgrade() -> None:
    bind = op.get_bind()
    for table in _tables():
        table.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for table in reversed(_tables()):
        table.drop(bind=bind, checkfirst=True)
