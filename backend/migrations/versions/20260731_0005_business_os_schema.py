"""Add tenant-scoped business operating system tables. Now a no-op.

This revision built four tables from ``app.business_os_models`` metadata. That
module was deleted when the business OS dashboard was retired, and a revision
that imports a deleted module cannot replay -- a fresh database could not
migrate past this point at all.

Emptied rather than deleted: the revision id is recorded in every database that
has already run it, and removing it from the chain would strand them with a
``down_revision`` pointing at a revision that no longer exists.

Databases that ran the original version still hold the four tables; revision
20260806_0009 drops them. A fresh database never creates them. Both converge.

Revision ID: 20260731_0005
Revises: 20260721_0004
Create Date: 2026-07-31
"""

from typing import Sequence, Union

revision: str = "20260731_0005"
down_revision: Union[str, Sequence[str], None] = "20260721_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """No-op. See the module docstring; 20260806_0009 drops what this created."""


def downgrade() -> None:
    """No-op, symmetric with upgrade."""
