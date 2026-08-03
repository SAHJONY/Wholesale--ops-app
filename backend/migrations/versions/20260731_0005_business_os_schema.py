"""Add tenant-scoped business operating system tables.

Revision ID: 20260731_0005
Revises: 20260721_0004
Create Date: 2026-07-31
"""

from importlib import import_module
from typing import Sequence, Union

from alembic import op

from app.database import Base

revision: str = "20260731_0005"
down_revision: Union[str, Sequence[str], None] = "20260721_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = frozenset({"business_plans", "business_transactions", "business_obligations", "operating_playbooks"})


def _tables():
    import_module("app.business_os_models")
    return [table for table in Base.metadata.sorted_tables if table.name in TABLES]


def upgrade() -> None:
    bind = op.get_bind()
    for table in _tables():
        table.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for table in reversed(_tables()):
        table.drop(bind=bind, checkfirst=True)
