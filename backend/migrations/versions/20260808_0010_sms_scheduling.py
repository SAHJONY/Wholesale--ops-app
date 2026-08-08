"""Add SAHJONY SMS appointment and follow-up tables.

Revision ID: 20260808_0010
Revises: 20260807_0009
Create Date: 2026-08-08
"""

from importlib import import_module
from typing import Sequence, Union

from alembic import op

from app.database import Base

revision: str = "20260808_0010"
down_revision: Union[str, Sequence[str], None] = "20260807_0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = frozenset({"sms_appointment_requests", "sms_follow_up_jobs"})


def _tables():
    import_module("app.sms_agentic_models")
    import_module("app.sms_scheduling_models")
    return [table for table in Base.metadata.sorted_tables if table.name in TABLES]


def upgrade() -> None:
    bind = op.get_bind()
    for table in _tables():
        table.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for table in reversed(_tables()):
        table.drop(bind=bind, checkfirst=True)
