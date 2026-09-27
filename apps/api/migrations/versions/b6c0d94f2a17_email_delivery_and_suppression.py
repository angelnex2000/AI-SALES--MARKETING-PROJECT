"""email delivery records and contact suppression

Wiring real email delivery (Mailjet over SMTP) made two gaps urgent that were
harmless while `send_draft` only recorded intent:

  * **`contacts.do_not_contact`.** The Reply Intent Agent has classified
    `unsubscribe` and suggested `do_not_contact` since Phase 8 Module 10, but
    there was nowhere to record it and nothing to enforce it. Displayed-only
    consent is a compliance failure the moment something actually sends.
    Scoped to the contact rather than the lead: the person who wrote "remove
    me" asked for their own address to stop, and suppressing every colleague
    at the same company reads that request wider than they made it.
  * **`sent_emails` could not say what happened.** It recorded that a draft was
    dispatched, not where it went or whether it arrived. `delivery_status`
    defaults to `dry_run` precisely so a row that was never transmitted cannot
    be mistaken for one that was — the easiest mistake to make on the first
    real send is assuming the pipeline worked because the row appeared.

`delivery_status` is a String, not a DB enum: provider states grow (queued,
bounced, deferred, complained) and an enum would mean a migration per addition.

Revision ID: b6c0d94f2a17
Revises: a2f8b31c5d94
Create Date: 2026-08-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b6c0d94f2a17'
down_revision: Union[str, None] = 'a2f8b31c5d94'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'contacts',
        sa.Column('do_not_contact', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column('contacts', 'do_not_contact', server_default=None)
    op.add_column('contacts', sa.Column('do_not_contact_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('contacts', sa.Column('do_not_contact_reason', sa.String(), nullable=True))
    op.create_index(
        op.f('ix_contacts_do_not_contact'), 'contacts', ['do_not_contact'], unique=False
    )

    op.add_column('sent_emails', sa.Column('to_address', sa.String(), nullable=True))
    op.add_column(
        'sent_emails',
        sa.Column('delivery_status', sa.String(), nullable=False, server_default='dry_run'),
    )
    op.alter_column('sent_emails', 'delivery_status', server_default=None)
    op.add_column('sent_emails', sa.Column('provider_message_id', sa.String(), nullable=True))
    op.add_column('sent_emails', sa.Column('delivery_error', sa.Text(), nullable=True))
    op.create_index(
        op.f('ix_sent_emails_delivery_status'), 'sent_emails', ['delivery_status'], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_sent_emails_delivery_status'), table_name='sent_emails')
    for column in ('delivery_error', 'provider_message_id', 'delivery_status', 'to_address'):
        op.drop_column('sent_emails', column)

    op.drop_index(op.f('ix_contacts_do_not_contact'), table_name='contacts')
    # Note this is lossy in a way that matters: downgrading discards every
    # recorded opt-out, and the next campaign would email people who asked not
    # to be. Export `contacts.do_not_contact` before running it.
    for column in ('do_not_contact_reason', 'do_not_contact_at', 'do_not_contact'):
        op.drop_column('contacts', column)
