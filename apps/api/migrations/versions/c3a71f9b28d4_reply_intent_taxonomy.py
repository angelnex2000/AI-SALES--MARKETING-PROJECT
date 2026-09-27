"""reply intent taxonomy and explanation columns

Phase 8 Module 10. Two changes to `reply_intent_results`:

  * The `replyintent` enum grows from the four placeholder labels written in
    Phase 4 to the eight MVP classes the agent actually emits. Three are
    renames of an existing value rather than new members, so the rows that a
    deployed instance might already hold keep their meaning.
  * The table gains `explanation` (it carried the other three AIOutputMixin
    columns but not this one), plus `matched_phrase` and `alternative_intents`.

Written as an incremental revision rather than by editing the initial
migration: the baseline is the contract for anyone who has already applied it,
and an enum whose members differ between a fresh `upgrade head` and an
existing database is the kind of drift that only surfaces as an
InvalidTextRepresentation on the first insert in production.

`ALTER TYPE ... ADD VALUE` runs inside Alembic's transaction, which PostgreSQL
allows from 12 onward provided the new values are not *used* in the same
transaction. Nothing here inserts rows, so that holds.

Revision ID: c3a71f9b28d4
Revises: 92f0cac4322f
Create Date: 2026-08-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c3a71f9b28d4'
down_revision: Union[str, None] = '92f0cac4322f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# old value -> new value. Each is the same concept under the name the agent and
# the API contract use, so renaming in place preserves existing rows.
RENAMED_VALUES: tuple[tuple[str, str], ...] = (
    ('follow_up', 'follow_up_later'),
    ('rejected', 'not_interested'),
    ('info_request', 'pricing_request'),
)

ADDED_VALUES: tuple[str, ...] = (
    'meeting_request',
    'unsubscribe',
    'out_of_office',
    'unknown',
)

# Reverse mapping for downgrade. PostgreSQL cannot remove a value from an
# enum, so the type is rebuilt — and the four labels this migration introduces
# have no equivalent in the old set. Downgrading is therefore lossy by
# construction: `meeting_request` and `unknown` collapse into neighbours that
# do not mean the same thing. Recorded explicitly rather than left to fail.
DOWNGRADE_COLLAPSE: tuple[tuple[str, str], ...] = (
    ('meeting_request', 'interested'),
    ('unsubscribe', 'rejected'),
    ('out_of_office', 'follow_up'),
    ('unknown', 'follow_up'),
    ('not_interested', 'rejected'),
    ('follow_up_later', 'follow_up'),
    ('pricing_request', 'info_request'),
)

OLD_ENUM_VALUES: tuple[str, ...] = ('interested', 'follow_up', 'rejected', 'info_request')


def upgrade() -> None:
    for old, new in RENAMED_VALUES:
        op.execute(f"ALTER TYPE replyintent RENAME VALUE '{old}' TO '{new}'")
    for value in ADDED_VALUES:
        op.execute(f"ALTER TYPE replyintent ADD VALUE IF NOT EXISTS '{value}'")

    # server_default fills the existing rows, then is dropped so the column has
    # no default going forward — an AI result with an empty explanation should
    # be impossible to write, not quietly defaulted.
    op.add_column(
        'reply_intent_results',
        sa.Column('explanation', sa.Text(), nullable=False, server_default=''),
    )
    op.alter_column('reply_intent_results', 'explanation', server_default=None)
    op.add_column(
        'reply_intent_results',
        sa.Column('matched_phrase', sa.String(), nullable=True),
    )
    op.add_column(
        'reply_intent_results',
        sa.Column(
            'alternative_intents',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column('reply_intent_results', 'alternative_intents')
    op.drop_column('reply_intent_results', 'matched_phrase')
    op.drop_column('reply_intent_results', 'explanation')

    # Rebuild the type: RENAME VALUE is reversible, ADD VALUE is not, so both
    # are undone in one swap. The CASE maps every current label onto the old
    # set so the column can be cast without losing rows.
    cases = "\n        ".join(
        f"WHEN '{current}' THEN '{legacy}'" for current, legacy in DOWNGRADE_COLLAPSE
    )
    old_values = ", ".join(f"'{v}'" for v in OLD_ENUM_VALUES)
    op.execute("ALTER TYPE replyintent RENAME TO replyintent_old")
    op.execute(f"CREATE TYPE replyintent AS ENUM ({old_values})")
    op.execute(
        f"""
        ALTER TABLE reply_intent_results
        ALTER COLUMN intent TYPE replyintent
        USING (CASE intent::text
        {cases}
        ELSE intent::text
        END)::replyintent
        """
    )
    op.execute("DROP TYPE replyintent_old")
