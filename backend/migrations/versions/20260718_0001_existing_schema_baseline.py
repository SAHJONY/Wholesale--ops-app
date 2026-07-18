"""Establish the migration baseline for the existing SAHJONY schema.

Revision ID: 20260718_0001
Revises:
Create Date: 2026-07-18

This revision intentionally performs no DDL. Production and development databases
were created historically through SQLAlchemy metadata.create_all(). Deployments
must stamp this revision once after verifying that the existing schema is present.
All subsequent schema changes must be implemented as normal Alembic revisions.
"""

from typing import Sequence, Union

revision: str = "20260718_0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    raise RuntimeError("The existing-schema baseline cannot be downgraded safely")
