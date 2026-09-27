"""revenue forecast: money as numeric, per-currency rows, breakdown

Phase 8 Module 12, the revision that makes `revenue_forecasts` usable:

  * `predicted_revenue` was `Float`. It is money — summed from `Deal.amount`
    across a whole pipeline — and `Deal.amount` is `NUMERIC(14,2)` precisely
    because binary floating point cannot represent values like 0.10 and the
    error compounds per deal. Widened to `NUMERIC(16,2)` since it holds a sum.
  * `currency` added. Without it a tenant selling in INR and USD gets one
    figure that is the sum of two incompatible units. One row per
    (period, currency) instead.
  * `explanation` added via `AIOutputMixin` — the table had the other three
    columns but not this one, on the output a Sales Manager quotes upward.
  * `committed_revenue` / `weighted_pipeline` split the banked part from the
    expectation, and `breakdown` holds the per-stage rollup and top deals.

`USING predicted_revenue::numeric` makes the type change lossless in the
forward direction; the downgrade back to double precision is not.

Revision ID: e91c46a80b35
Revises: d5b8e0c4712f
Create Date: 2026-08-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'e91c46a80b35'
down_revision: Union[str, None] = 'd5b8e0c4712f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        'revenue_forecasts',
        'predicted_revenue',
        existing_type=sa.Float(),
        type_=sa.Numeric(16, 2),
        existing_nullable=False,
        postgresql_using='predicted_revenue::numeric',
    )
    op.add_column(
        'revenue_forecasts',
        sa.Column('currency', sa.String(), nullable=False, server_default='USD'),
    )
    op.alter_column('revenue_forecasts', 'currency', server_default=None)
    op.add_column(
        'revenue_forecasts',
        sa.Column('explanation', sa.Text(), nullable=False, server_default=''),
    )
    op.alter_column('revenue_forecasts', 'explanation', server_default=None)
    for column in ('committed_revenue', 'weighted_pipeline'):
        op.add_column(
            'revenue_forecasts',
            sa.Column(column, sa.Numeric(16, 2), nullable=False, server_default='0'),
        )
        op.alter_column('revenue_forecasts', column, server_default=None)
    op.add_column(
        'revenue_forecasts',
        sa.Column('breakdown', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('revenue_forecasts', 'breakdown')
    op.drop_column('revenue_forecasts', 'weighted_pipeline')
    op.drop_column('revenue_forecasts', 'committed_revenue')
    op.drop_column('revenue_forecasts', 'explanation')
    op.drop_column('revenue_forecasts', 'currency')
    op.alter_column(
        'revenue_forecasts',
        'predicted_revenue',
        existing_type=sa.Numeric(16, 2),
        type_=sa.Float(),
        existing_nullable=False,
        postgresql_using='predicted_revenue::double precision',
    )
