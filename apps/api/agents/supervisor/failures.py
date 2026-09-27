"""Deciding whether a failed agent task is worth trying again.

Section 7 of the module brief says "retry if temporary". The whole difficulty
is in *temporary*, and getting it wrong is expensive in both directions:

  * Retrying a permanent failure burns latency and, for the Outreach Agent,
    real money — three attempts at a request that fails because
    `OPENAI_API_KEY` is unset is three round trips to learn what the first one
    said.
  * Not retrying a transient failure fails a job over a rate limit that would
    have cleared in a second.

So the rule is **deny by default**: retry only what is positively identified as
transient, and treat everything else as permanent. The asymmetry is
deliberate — a permanent failure retried is waste with no upside, while a
transient failure not retried leaves a job the user can re-trigger, and the
error message says why.

Classification walks the exception's `__cause__` chain rather than reading its
message. `OutreachUnavailableError` wraps both "no API key" (permanent, raised
with no cause) and "the provider timed out" (transient, raised `from exc`), so
the wrapper type says nothing and only the cause does. Matching on message
substrings would work until somebody rewords an error string.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Exception type names that mean "the same call might work shortly". Matched by
# name so provider SDKs do not have to be imported here — this module must stay
# importable in a worker that has no OpenAI client installed.
TRANSIENT_TYPE_NAMES: frozenset[str] = frozenset(
    {
        "APIConnectionError",
        "APITimeoutError",
        "ConnectionError",
        "ConnectionResetError",
        "InternalServerError",
        "RateLimitError",
        "ServiceUnavailableError",
        "TimeoutError",
        "TooManyRedirects",
        "asyncio.TimeoutError",
    }
)

# Retries and the wait before each. Short and few: these run inside a Celery
# task, so a long backoff holds a worker slot, and an agent that has failed
# twice is unlikely to succeed on a third attempt within the same second.
RETRY_DELAYS_SECONDS: tuple[float, ...] = (1.0, 4.0)
MAX_ATTEMPTS = len(RETRY_DELAYS_SECONDS) + 1

# **A 429 is not automatically transient.** Providers reuse the status — and
# the SDK exception type — for two opposite situations:
#
#   * "too many requests this minute", which clears on its own; and
#   * "this account has no credits", which never clears without a human
#     changing a billing setting.
#
# `openai.RateLimitError` is raised for both, so the type name alone says
# nothing. Retrying the second costs three round trips and five seconds of
# backoff on *every* job to learn what the first attempt already reported —
# precisely the waste this module exists to avoid.
#
# Matched on the provider's structured `code`/`type` field, not on message
# prose: the wording of "You have no credits remaining" is theirs to change,
# the error code is part of their API.
PERMANENT_ERROR_CODES: frozenset[str] = frozenset(
    {
        "insufficient_quota",
        "credit_balance_exhausted",
        "billing_hard_limit_reached",
        "account_deactivated",
        "invalid_api_key",
        "invalid_request_error",
        "model_not_found",
    }
)


def _error_codes(exc: BaseException) -> set[str]:
    """Structured error identifiers carried by a provider exception."""

    codes: set[str] = set()
    for attribute in ("code", "type"):
        value = getattr(exc, attribute, None)
        if isinstance(value, str):
            codes.add(value)
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        error = body.get("error") if isinstance(body.get("error"), dict) else body
        for attribute in ("code", "type"):
            value = error.get(attribute)
            if isinstance(value, str):
                codes.add(value)
    return codes


def _chain(exc: BaseException) -> list[BaseException]:
    seen: list[BaseException] = []
    current: BaseException | None = exc
    while current is not None and current not in seen:
        seen.append(current)
        current = current.__cause__ or current.__context__
    return seen


def is_transient(exc: BaseException) -> bool:
    """True when the same call might succeed if repeated.

    Checks the whole cause chain, because the exception a caller sees is
    usually a wrapper: the Outreach Agent raises `OutreachUnavailableError`
    `from` whatever the provider raised, and only the inner one carries the
    information.
    """

    chain = _chain(exc)

    # A permanent code anywhere in the chain settles it, whatever the exception
    # types say. Checked first so `RateLimitError(code="insufficient_quota")`
    # cannot be read as an ordinary rate limit.
    for link in chain:
        if _error_codes(link) & PERMANENT_ERROR_CODES:
            return False

    for link in chain:
        if type(link).__name__ in TRANSIENT_TYPE_NAMES:
            return True
        # OSError covers the socket-level failures a provider SDK does not
        # always wrap — but not its subclasses that mean a real programming or
        # filesystem error, which are permanent.
        if isinstance(link, OSError) and not isinstance(link, FileNotFoundError | PermissionError):
            return True
    return False


def describe(exc: BaseException) -> str:
    """A message worth storing on the task row.

    Includes the cause, because "OutreachUnavailableError: connection error" on
    its own does not say whether the fix is a config change or a retry.
    """

    links = _chain(exc)
    head = f"{type(exc).__name__}: {exc}"
    if len(links) > 1:
        tail = links[-1]
        if tail is not exc:
            head += f" (caused by {type(tail).__name__}: {tail})"
    return head[:2000]


def should_retry(exc: BaseException, attempt: int) -> bool:
    transient = is_transient(exc)
    if not transient:
        logger.info("not retrying %s — classified permanent", type(exc).__name__)
    return transient and attempt < MAX_ATTEMPTS


def delay_before(attempt: int) -> float:
    """Backoff before `attempt` (1-based; attempt 1 never waits)."""

    index = attempt - 2
    if index < 0:
        return 0.0
    return RETRY_DELAYS_SECONDS[min(index, len(RETRY_DELAYS_SECONDS) - 1)]


__all__: list[Any] = [
    "MAX_ATTEMPTS",
    "RETRY_DELAYS_SECONDS",
    "TRANSIENT_TYPE_NAMES",
    "delay_before",
    "describe",
    "is_transient",
    "should_retry",
]
