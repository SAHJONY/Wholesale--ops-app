"""Drop the tables behind the retired reporting dashboards.

The integration hub, integration reliability, national intelligence and
business OS surfaces were removed: they reported on a pipeline rather than
moving one, and nothing reads these tables now.

Dropped rather than left in place because an orphaned table is worse than no
table. It keeps answering queries with stale rows long after the code that
maintained it is gone, and the next person to find it cannot tell whether it is
load-bearing.

``checkfirst`` on both sides so this is safe on a database that never created
them -- a fresh database migrating from scratch no longer builds them at all,
since revision 20260721_0004 stopped listing them.

The downgrade is deliberately incomplete and says so rather than pretending.
Recreating an empty table would satisfy Alembic while restoring none of the
data, which is a worse lie than an explicit refusal.

Revision ID: 20260806_0009
Revises: 20260803_0008
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260806_0009"
down_revision: Union[str, Sequence[str], None] = "20260803_0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

RETIRED_TABLES = (
    # integration_hub_models
    "integration_health_checks",
    "integration_operation_runs",
    # integration_reliability_models
    "integration_reliability_alerts",
    "integration_reliability_runs",
    # national_intelligence_models
    "property_intelligence_scores",
    "national_intelligence_runs",
    # business_os_models
    "business_plans",
    "business_transactions",
    "business_obligations",
    "operating_playbooks",
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())
    for name in RETIRED_TABLES:
        if name in existing:
            op.drop_table(name)


def downgrade() -> None:
    raise NotImplementedError(
        "This revision drops tables whose models were deleted. Downgrading "
        "would need those model definitions back; recreating empty tables here "
        "would report success while restoring nothing. Restore from a backup "
        "taken before the upgrade instead."
    )
