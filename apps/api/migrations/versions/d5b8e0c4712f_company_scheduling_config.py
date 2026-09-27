"""per-tenant scheduling config

Phase 8 Module 11. Adds `companies.scheduling_config`, holding the working
hours, working days, timezone and notice period the Meeting Scheduler agent
computes slots from.

Nullable with no default: null means "use `DEFAULT_SCHEDULING`", the same
convention `icp_config` already uses, so an unconfigured workspace keeps
working rather than needing a backfill.

Revision ID: d5b8e0c4712f
Revises: c3a71f9b28d4
Create Date: 2026-08-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'd5b8e0c4712f'
down_revision: Union[str, None] = 'c3a71f9b28d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'companies',
        sa.Column(
            'scheduling_config',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column('companies', 'scheduling_config')
