"""Add tenant-scoped BatchData MCP OAuth credentials and one-time states.

Revision ID: 20260802_0005
Revises: 20260721_0004
Create Date: 2026-08-02
"""

from typing import Sequence, Union

from alembic import op

from app.database import Base
from app import provider_oauth_models  # noqa: F401

revision: str = "20260802_0005"
down_revision: Union[str, Sequence[str], None] = "20260721_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = ("batchdata_oauth_connections", "batchdata_oauth_states")


def upgrade() -> None:
    bind = op.get_bind()
    for name in TABLES:
        Base.metadata.tables[name].create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for name in reversed(TABLES):
        Base.metadata.tables[name].drop(bind=bind, checkfirst=True)
