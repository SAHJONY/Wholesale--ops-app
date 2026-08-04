"""Add the cash buyer candidate review queue.

Revision ID: 20260803_0006
Revises: 20260731_0005
Create Date: 2026-08-03
"""

from importlib import import_module
from typing import Sequence, Union

from alembic import op

from app.database import Base

revision: str = "20260803_0006"
down_revision: Union[str, Sequence[str], None] = "20260731_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = frozenset({"cash_buyer_candidates"})


def _tables():
    import_module("app.cash_buyer_models")
    return [table for table in Base.metadata.sorted_tables if table.name in TABLES]


def upgrade() -> None:
    bind = op.get_bind()
    for table in _tables():
        table.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for table in reversed(_tables()):
        table.drop(bind=bind, checkfirst=True)
