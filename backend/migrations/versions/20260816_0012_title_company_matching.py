"""Add title company matching registry and deal matches.

Revision ID: 20260816_0012
Revises: 20260808_0011
Create Date: 2026-08-16
"""

from importlib import import_module
from typing import Sequence, Union

from alembic import op

from app.database import Base

revision: str = "20260816_0012"
down_revision: Union[str, Sequence[str], None] = "20260808_0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = frozenset({"title_company_partners", "title_company_deal_matches"})


def _tables():
    import_module("app.models")
    import_module("app.title_company_models")
    return [table for table in Base.metadata.sorted_tables if table.name in TABLES]


def upgrade() -> None:
    bind = op.get_bind()
    for table in _tables():
        table.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for table in reversed(_tables()):
        table.drop(bind=bind, checkfirst=True)
