"""Create the durable background jobs table.

Revision ID: 20260719_0003
Revises: 20260719_0002
Create Date: 2026-07-19
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "20260719_0003"
down_revision: Union[str, Sequence[str], None] = "20260719_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "background_jobs"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if TABLE not in inspector.get_table_names():
        op.create_table(
            TABLE,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("organization_id", sa.Integer(), nullable=False),
            sa.Column("job_type", sa.String(length=80), nullable=False),
            sa.Column("status", sa.String(length=30), nullable=False, server_default="queued"),
            sa.Column("priority", sa.Integer(), nullable=False, server_default="50"),
            sa.Column("payload_json", sa.JSON(), nullable=False),
            sa.Column("result_json", sa.JSON(), nullable=False),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
            sa.Column("available_at", sa.DateTime(), nullable=False),
            sa.Column("locked_at", sa.DateTime(), nullable=True),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("failed_at", sa.DateTime(), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("created_by_user_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )

    inspector = inspect(bind)
    existing_indexes = {index["name"] for index in inspector.get_indexes(TABLE)}
    for name, columns in (
        ("ix_background_jobs_organization_id", ["organization_id"]),
        ("ix_background_jobs_job_type", ["job_type"]),
        ("ix_background_jobs_status", ["status"]),
        ("ix_background_jobs_priority", ["priority"]),
        ("ix_background_jobs_available_at", ["available_at"]),
        ("ix_background_jobs_created_at", ["created_at"]),
    ):
        if name not in existing_indexes:
            op.create_index(name, TABLE, columns, unique=False)


def downgrade() -> None:
    op.drop_table(TABLE)
