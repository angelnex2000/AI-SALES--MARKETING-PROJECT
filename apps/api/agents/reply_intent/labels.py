"""Reply intent taxonomy and the action each label suggests.

Two enums, deliberately separate:

  * `ReplyIntent` is what the customer *meant*. It is a DB enum column
    (`reply_intent_results.intent`), so adding a member costs a migration —
    which is the right friction for a closed set the product is built around
    (the Outreach Center renders one card per label).
  * `SuggestedAction` is what we propose *doing about it*. It stays a plain
    `String` column for the same reason `BuyingSignal.signal_type` does: the
    action list grows as the product grows a new button, and a DB enum would
    mean a migration per addition for no queryable benefit.

**Nothing here is ever executed automatically.** `mark_closed_lost` is a
suggestion rendered as a button, not a state change — a keyword match must
never close a deal, because the same match fires on "we've already closed
that project". The platform's whole premise is that AI prepares work and a
human commits it.
"""

from enum import Enum


class ReplyIntent(str, Enum):
    """MVP label set. `value == name.lower()` for every member, which is what
    `Base.type_annotation_map` relies on to persist enums by value."""

    INTERESTED = "interested"
    PRICING_REQUEST = "pricing_request"
    MEETING_REQUEST = "meeting_request"
    FOLLOW_UP_LATER = "follow_up_later"
    NOT_INTERESTED = "not_interested"
    UNSUBSCRIBE = "unsubscribe"
    OUT_OF_OFFICE = "out_of_office"
    UNKNOWN = "unknown"


class SuggestedAction(str, Enum):
    PROPOSE_MEETING = "propose_meeting"
    SEND_PRICING = "send_pricing"
    SCHEDULE_MEETING = "schedule_meeting"
    CREATE_FOLLOW_UP_TASK = "create_follow_up_task"
    MARK_CLOSED_LOST = "mark_closed_lost"
    DO_NOT_CONTACT = "do_not_contact"
    NO_ACTION = "no_action"
    """Out-of-office: the human never saw the email, so there is nothing to
    respond to and nothing about the lead has changed."""
    MANUAL_REVIEW = "manual_review"


ACTION_FOR_INTENT: dict[ReplyIntent, SuggestedAction] = {
    ReplyIntent.INTERESTED: SuggestedAction.PROPOSE_MEETING,
    ReplyIntent.PRICING_REQUEST: SuggestedAction.SEND_PRICING,
    ReplyIntent.MEETING_REQUEST: SuggestedAction.SCHEDULE_MEETING,
    ReplyIntent.FOLLOW_UP_LATER: SuggestedAction.CREATE_FOLLOW_UP_TASK,
    ReplyIntent.NOT_INTERESTED: SuggestedAction.MARK_CLOSED_LOST,
    ReplyIntent.UNSUBSCRIBE: SuggestedAction.DO_NOT_CONTACT,
    ReplyIntent.OUT_OF_OFFICE: SuggestedAction.NO_ACTION,
    ReplyIntent.UNKNOWN: SuggestedAction.MANUAL_REVIEW,
}


# Resolution order when a reply matches more than one intent — and real replies
# routinely do ("sounds interesting, what does it cost, and can we talk
# Tuesday?"). Lower number wins. The ordering is not cosmetic; each step
# encodes a cost asymmetry:
#
#   1. out_of_office pre-empts everything. An absence notice is not a reply at
#      all, and its body is full of other people's phone numbers and
#      "for urgent matters, call" — every positive rule fires on it.
#   2. unsubscribe outranks every positive intent, including a genuinely warm
#      one. Emailing someone who asked us to stop is a legal exposure
#      (CAN-SPAM/GDPR); wrongly suppressing one lead is not.
#   3. not_interested outranks the positives because a rejection almost always
#      names the thing being rejected — "we're not looking for a demo" contains
#      "demo". Ranking meeting_request above it would turn every polite refusal
#      into a booking.
#
# Below that, the positives are ordered by how specific a commitment they
# represent: proposing a time > asking a price > deferring > general warmth.
INTENT_PRIORITY: dict[ReplyIntent, int] = {
    ReplyIntent.OUT_OF_OFFICE: 0,
    ReplyIntent.UNSUBSCRIBE: 1,
    ReplyIntent.NOT_INTERESTED: 2,
    ReplyIntent.MEETING_REQUEST: 3,
    ReplyIntent.PRICING_REQUEST: 4,
    ReplyIntent.FOLLOW_UP_LATER: 5,
    ReplyIntent.INTERESTED: 6,
    ReplyIntent.UNKNOWN: 99,
}