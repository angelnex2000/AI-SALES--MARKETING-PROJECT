"""Outreach drafts and Gate 2.

Gate 2 is the rule that no AI-written email reaches a customer without a
human approving that exact text. Everything here exists to keep that true:

  * A draft is editable only while it is awaiting approval. Editing an
    already-approved draft **voids the approval** and sends it back to
    `pending_approval`, because otherwise Marketing could rewrite the body
    after a Sales Executive approved it and the send would deliver text
    nobody signed off.
  * Only `pending_approval` can be approved, and only `approved` can be
    sent — so a sent draft cannot be re-approved and re-sent.
  * A sent draft is immutable.

The state machine is declared once in `_ALLOWED_EDIT_STATUSES` and the
transition guards below, rather than being re-checked ad hoc per route.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationError
from app.models.lead import Contact, Lead
from app.models.outreach import DraftStatus, EmailDraft, SentEmail
from app.models.user import Role, User
from app.services import crm_service, email_service, lead_service

# Editing is allowed in these states. `approved` is deliberately absent as a
# *safe* state: an edit there is accepted but voids the approval (see
# update_draft), and `sent` is rejected outright.
_ALLOWED_EDIT_STATUSES = (DraftStatus.PENDING_APPROVAL, DraftStatus.REJECTED, DraftStatus.APPROVED)


def _visible(stmt: Select, *, user: User) -> Select:
    """Drafts inherit their visibility from the parent lead.

    Without the Lead join a Sales Executive would see every draft in the
    tenant, including ones for leads assigned to other reps — the list
    endpoints previously did exactly that.
    """

    stmt = stmt.join(Lead, EmailDraft.lead_id == Lead.id).where(
        EmailDraft.company_id == user.company_id,
        Lead.archived_at.is_(None),
    )
    if user.role == Role.SALES_EXECUTIVE:
        stmt = stmt.where(Lead.owner_id == user.id)
    return stmt


async def list_drafts(
    db: AsyncSession, *, user: User, status: DraftStatus | None = None
) -> list[EmailDraft]:
    stmt = _visible(select(EmailDraft), user=user)
    if status is not None:
        stmt = stmt.where(EmailDraft.status == status)
    return list((await db.execute(stmt.order_by(EmailDraft.created_at.desc()))).scalars().all())


async def require_draft(db: AsyncSession, *, draft_id: uuid.UUID, user: User) -> EmailDraft:
    stmt = _visible(select(EmailDraft).where(EmailDraft.id == draft_id), user=user)
    draft = (await db.execute(stmt)).scalar_one_or_none()
    if draft is None:
        raise NotFoundError("Draft not found", error_code="DRAFT_NOT_FOUND")
    return draft


async def update_draft(
    db: AsyncSession, *, draft_id: uuid.UUID, changes: dict, user: User
) -> tuple[EmailDraft, bool]:
    """Returns (draft, approval_voided) so the router can tell the user their
    edit sent the draft back for re-approval."""

    draft = await require_draft(db, draft_id=draft_id, user=user)
    if draft.status not in _ALLOWED_EDIT_STATUSES:
        raise ValidationError(
            f"A {draft.status.value} draft cannot be edited", error_code="DRAFT_NOT_EDITABLE"
        )

    # Module 13 — capture what the AI wrote before the first human keystroke
    # overwrites it. Only once: later edits must still be measured against the
    # AI's original, not against the previous human revision, or a draft that
    # was rewritten in three passes reads as three small tweaks.
    if draft.ai_generated and draft.ai_original_body is None:
        draft.ai_original_subject = draft.subject
        draft.ai_original_body = draft.body

    approval_voided = False
    if draft.status == DraftStatus.APPROVED:
        # The approval was for the previous text. Editing invalidates it, so
        # the draft must go through Gate 2 again before it can be sent.
        draft.status = DraftStatus.PENDING_APPROVAL
        draft.approved_by_id = None
        approval_voided = True
    elif draft.status == DraftStatus.REJECTED:
        # A reworked draft goes back into the approval queue.
        draft.status = DraftStatus.PENDING_APPROVAL

    for field, value in changes.items():
        setattr(draft, field, value)
    await db.commit()
    await db.refresh(draft)
    return draft, approval_voided


async def approve_draft(db: AsyncSession, *, draft_id: uuid.UUID, user: User) -> EmailDraft:
    """Gate 2. `require_role(SALES_EXECUTIVE)` at the router restricts who; the
    status guard here stops an already-sent draft being approved again."""

    draft = await require_draft(db, draft_id=draft_id, user=user)
    if draft.status != DraftStatus.PENDING_APPROVAL:
        raise ValidationError(
            f"Only a pending draft can be approved (this one is {draft.status.value})",
            error_code="DRAFT_NOT_PENDING",
        )
    draft.status = DraftStatus.APPROVED
    draft.approved_by_id = user.id
    await db.commit()
    await db.refresh(draft)
    return draft


async def reject_draft(db: AsyncSession, *, draft_id: uuid.UUID, user: User) -> EmailDraft:
    draft = await require_draft(db, draft_id=draft_id, user=user)
    if draft.status == DraftStatus.SENT:
        raise ValidationError("A sent draft cannot be rejected", error_code="DRAFT_ALREADY_SENT")
    draft.status = DraftStatus.REJECTED
    draft.approved_by_id = None
    await db.commit()
    await db.refresh(draft)
    return draft


async def _recipient(db: AsyncSession, draft: EmailDraft) -> Contact:
    """The person this draft goes to, or a refusal that says why.

    Three ways a Gate-2-approved draft can still be unsendable, each with its
    own error code because each has a different fix:

    * **No contact.** A draft can be created before the attendee is confirmed;
      it cannot be *sent* that way, because there is no address.
    * **No email address** on that contact.
    * **The contact asked not to be emailed.** This one is a hard refusal, not
      a warning, and it is checked here rather than in the router so no future
      caller can route around it. An approved draft is not consent from the
      recipient — Gate 2 is the *sender's* sign-off, and the two are different
      permissions that this code path is the only place to reconcile.
    """

    if draft.contact_id is None:
        raise ValidationError(
            "This draft has no contact, so there is no address to send to",
            error_code="DRAFT_HAS_NO_CONTACT",
        )
    contact = await db.get(Contact, draft.contact_id)
    if contact is None or contact.company_id != draft.company_id:
        raise NotFoundError("Contact not found", error_code="CONTACT_NOT_FOUND")
    if contact.do_not_contact:
        raise ValidationError(
            f"{contact.full_name} has asked not to be contacted"
            f"{f' ({contact.do_not_contact_reason})' if contact.do_not_contact_reason else ''}",
            error_code="CONTACT_DO_NOT_CONTACT",
        )
    if not (contact.email or "").strip():
        raise ValidationError(
            f"{contact.full_name} has no email address on record",
            error_code="CONTACT_HAS_NO_EMAIL",
        )
    return contact


async def suppress_contact(
    db: AsyncSession, *, contact: Contact, reason: str
) -> None:
    """Mark a contact do-not-contact. Idempotent — the first suppression keeps
    its timestamp, because that is the date that answers "when did they ask?"."""

    if contact.do_not_contact:
        return
    contact.do_not_contact = True
    contact.do_not_contact_at = datetime.now(UTC)
    contact.do_not_contact_reason = reason


async def send_draft(db: AsyncSession, *, draft_id: uuid.UUID, user: User) -> SentEmail:
    """The only path from a draft to a customer. Requires an approval that is
    still valid for the current text — see update_draft."""

    draft = await require_draft(db, draft_id=draft_id, user=user)
    if draft.status == DraftStatus.SENT:
        # Without this an approved-then-sent draft could be sent twice; the
        # customer receives duplicates and sent_emails double-counts.
        raise ValidationError("Draft has already been sent", error_code="DRAFT_ALREADY_SENT")
    if draft.status != DraftStatus.APPROVED:
        raise ValidationError(
            "Draft must be approved before sending", error_code="DRAFT_NOT_APPROVED"
        )

    contact = await _recipient(db, draft)
    delivery = email_service.send(
        to_address=contact.email, subject=draft.subject, body=draft.body
    )

    sent = SentEmail(
        company_id=user.company_id,
        draft_id=draft.id,
        lead_id=draft.lead_id,
        sent_at=datetime.now(UTC),
        to_address=delivery.to_address,
        delivery_status=delivery.status,
        provider_message_id=delivery.provider_message_id,
        delivery_error=delivery.error,
    )
    if delivery.status == email_service.STATUS_FAILED:
        # The draft stays `approved`, not `sent`: a transport failure means the
        # customer never received it, and marking it sent would both lie to the
        # rep and make `send_draft`'s terminal-state guard block the retry.
        db.add(sent)
        await db.commit()
        raise ValidationError(
            f"Delivery failed: {delivery.error}", error_code="EMAIL_DELIVERY_FAILED"
        )

    draft.status = DraftStatus.SENT
    db.add(sent)

    # Module 13 step 7 — the send has to show up in the lead's history, or the
    # Timeline tab silently omits the most important thing that happened.
    await crm_service.log_system_activity(
        db,
        company_id=user.company_id,
        lead_id=draft.lead_id,
        actor_id=user.id,
        activity_type="email_sent",
        description=(
            f"Outreach email sent: {draft.subject}"
            if delivery.delivered
            else f"Outreach email recorded (not transmitted — {delivery.reason}): {draft.subject}"
        ),
    )

    await db.commit()
    await db.refresh(sent)
    return sent


async def list_sent_emails(
    db: AsyncSession, *, user: User, lead_id: uuid.UUID | None = None
) -> list[SentEmail]:
    """Same visibility rule as drafts — scoped through the lead, not just the
    tenant."""

    stmt = (
        select(SentEmail)
        .join(Lead, SentEmail.lead_id == Lead.id)
        .where(SentEmail.company_id == user.company_id, Lead.archived_at.is_(None))
    )
    if user.role == Role.SALES_EXECUTIVE:
        stmt = stmt.where(Lead.owner_id == user.id)
    if lead_id is not None:
        await lead_service.require_lead(
            db, lead_id=lead_id, company_id=user.company_id, current_user=user
        )
        stmt = stmt.where(SentEmail.lead_id == lead_id)
    return list((await db.execute(stmt.order_by(SentEmail.sent_at.desc()))).scalars().all())
