"""feedback records and preserved AI draft text

Phase 8 Module 13.

  * `feedback_records` — explicit human feedback on one AI output, polymorphic
    over `target_type`/`target_id`. Deliberately carries no `edited` /
    `meeting_booked` / `deal_closed` booleans: those are already first-class
    facts (`EmailDraft`, `Meeting`, `DealOutcome`) and a copy of them here
    would go stale, which matters because this is the table a retraining run
    reads.
  * `email_drafts.ai_original_subject` / `ai_original_body` — what the Outreach
    Agent wrote, before a human edited it. Editing overwrites `subject`/`body`
    in place, so without these the AI's text was destroyed by the first
    keystroke and edit distance would have compared a draft against itself.

Both enum types are dropped explicitly on downgrade: autogenerate emits
`CREATE TYPE` but never the matching `DROP TYPE`, so without this a
`downgrade` followed by an `upgrade` fails with 'type already exists' — the
same hand-added block the initial migration carries.

Revision ID: f4d2a7c1e806
Revises: e91c46a80b35
Create Date: 2026-08-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'f4d2a7c1e806'
down_revision: Union[str, None] = 'e91c46a80b35'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW_ENUMS: tuple[str, ...] = ('feedbacktarget', 'feedbackverdict')


def upgrade() -> None:
    op.add_column('email_drafts', sa.Column('ai_original_subject', sa.String(), nullable=True))
    op.add_column('email_drafts', sa.Column('ai_original_body', sa.Text(), nullable=True))

    op.create_table(
        'feedback_records',
        sa.Column(
            'target_type',
            sa.Enum(
                'email_draft',
                'research_report',
                'lead_score',
                'buying_signal',
                'icp_score',
                'reply_intent',
                'revenue_forecast',
                name='feedbacktarget',
            ),
            nullable=False,
        ),
        sa.Column('target_id', sa.UUID(), nullable=False),
        sa.Column('lead_id', sa.UUID(), nullable=True),
        sa.Column('author_id', sa.UUID(), nullable=False),
        sa.Column('rating', sa.Integer(), nullable=True),
        sa.Column(
            'verdict',
            sa.Enum('helpful', 'needs_work', 'incorrect', name='feedbackverdict'),
            nullable=True,
        ),
        sa.Column('correction', sa.String(), nullable=True),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('company_id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
        sa.ForeignKeyConstraint(['lead_id'], ['leads.id'], ),
        sa.ForeignKeyConstraint(['author_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_feedback_records_company_id'), 'feedback_records', ['company_id'], unique=False)
    op.create_index(op.f('ix_feedback_records_lead_id'), 'feedback_records', ['lead_id'], unique=False)
    op.create_index(op.f('ix_feedback_records_target_id'), 'feedback_records', ['target_id'], unique=False)
    op.create_index(op.f('ix_feedback_records_target_type'), 'feedback_records', ['target_type'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_feedback_records_target_type'), table_name='feedback_records')
    op.drop_index(op.f('ix_feedback_records_target_id'), table_name='feedback_records')
    op.drop_index(op.f('ix_feedback_records_lead_id'), table_name='feedback_records')
    op.drop_index(op.f('ix_feedback_records_company_id'), table_name='feedback_records')
    op.drop_table('feedback_records')
    for enum_name in NEW_ENUMS:
        op.execute(f'DROP TYPE IF EXISTS {enum_name}')

    op.drop_column('email_drafts', 'ai_original_body')
    op.drop_column('email_drafts', 'ai_original_subject')
