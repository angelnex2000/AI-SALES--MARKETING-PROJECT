"""Email delivery via Mailjet's SMTP relay.

No provider SDK: Mailjet's relay takes the API key as the SMTP username and the
secret key as the password, so `smtplib` plus the existing `SMTP_*` settings do
the whole job. A REST adapter would only earn its place alongside delivery and
bounce webhooks, which do not exist yet.

Three guards, in this order, because each one fails differently:

1. **Suppression** is checked by the caller before anything here runs, since it
   needs the database. It is the only one of the three that is a legal matter
   rather than an operational one.
2. **`EMAIL_SEND_ENABLED`** gates real delivery independently of whether
   credentials exist. Having a key is not consent to email prospects — a test
   against a seeded contact reaches a real inbox and cannot be recalled.
3. **Configuration completeness** is checked *before* the send is attempted, so
   a missing validated sender is an error the caller sees rather than an SMTP
   rejection discovered after the draft has been marked sent.

The return value always says which path ran. A caller must never have to infer
"was this actually delivered?" from the absence of an exception — that is how a
dry run gets recorded as a send.
"""

import logging
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from app.core.config import settings

logger = logging.getLogger(__name__)

STATUS_SENT = "sent"
STATUS_DRY_RUN = "dry_run"
STATUS_FAILED = "failed"


@dataclass(frozen=True)
class DeliveryResult:
    status: str
    to_address: str
    provider_message_id: str | None = None
    error: str | None = None
    reason: str | None = None
    """Why a dry run happened — "sending disabled" and "no SMTP host
    configured" call for different fixes."""

    @property
    def delivered(self) -> bool:
        return self.status == STATUS_SENT


class EmailNotConfiguredError(RuntimeError):
    """Sending is enabled but the settings needed to do it are incomplete."""


def is_configured() -> bool:
    return bool(settings.SMTP_HOST and settings.SMTP_USER and settings.SMTP_PASSWORD)


def _missing_settings() -> list[str]:
    required = {
        "SMTP_HOST": settings.SMTP_HOST,
        "SMTP_USER": settings.SMTP_USER,
        "SMTP_PASSWORD": settings.SMTP_PASSWORD,
        "EMAIL_FROM_ADDRESS": settings.EMAIL_FROM_ADDRESS,
    }
    return sorted(name for name, value in required.items() if not value)


def _build_message(*, to_address: str, subject: str, body: str, message_id: str) -> EmailMessage:
    message = EmailMessage()
    message["From"] = formataddr((settings.EMAIL_FROM_NAME or None, settings.EMAIL_FROM_ADDRESS))
    message["To"] = to_address
    message["Subject"] = subject
    message["Message-ID"] = message_id
    # Threading a customer's reply back to the SentEmail row is what makes the
    # reply webhook resolvable, so the id we generate is the one we store.
    message.set_content(body)
    return message


def send(*, to_address: str, subject: str, body: str) -> DeliveryResult:
    """Deliver one message, or explain precisely why it was not delivered.

    Never raises for an ordinary delivery failure: the caller has already
    committed to a Gate-2-approved send and needs to record the outcome against
    the `SentEmail` row rather than lose it to an exception.
    """

    to_address = (to_address or "").strip()
    if not to_address:
        return DeliveryResult(
            status=STATUS_FAILED,
            to_address="",
            error="no recipient address",
        )

    if not settings.EMAIL_SEND_ENABLED:
        # The common case in development, and the one that must be
        # unmistakable in the record.
        return DeliveryResult(
            status=STATUS_DRY_RUN,
            to_address=to_address,
            reason="EMAIL_SEND_ENABLED is false — nothing was transmitted",
        )

    missing = _missing_settings()
    if missing:
        raise EmailNotConfiguredError(
            f"EMAIL_SEND_ENABLED is true but {', '.join(missing)} "
            f"{'is' if len(missing) == 1 else 'are'} unset"
        )

    message_id = make_msgid(domain=settings.EMAIL_FROM_ADDRESS.split("@")[-1] or None)
    message = _build_message(
        to_address=to_address, subject=subject, body=body, message_id=message_id
    )

    try:
        with smtplib.SMTP(
            settings.SMTP_HOST, settings.SMTP_PORT, timeout=settings.EMAIL_TIMEOUT_SECONDS
        ) as smtp:
            # STARTTLS on 587 rather than plaintext: the SMTP password here is
            # the Mailjet secret key, and it would otherwise cross the network
            # in the clear.
            smtp.starttls(context=ssl.create_default_context())
            smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            smtp.send_message(message)
    except Exception as exc:
        # Logged without the message body: it is customer correspondence and
        # the logging middleware deliberately keeps PII out of logs.
        logger.error(
            "email delivery failed to %s: %s", _mask(to_address), type(exc).__name__, exc_info=exc
        )
        return DeliveryResult(
            status=STATUS_FAILED, to_address=to_address, error=f"{type(exc).__name__}: {exc}"[:1000]
        )

    logger.info("email delivered to %s", _mask(to_address))
    return DeliveryResult(
        status=STATUS_SENT, to_address=to_address, provider_message_id=message_id
    )


def _mask(address: str) -> str:
    """Log the domain, not the person.

    Recipient addresses are lead PII; `RequestLoggingMiddleware` already
    refuses to log bodies for the same reason, and a delivery log line should
    not be the hole in that.
    """

    local, _, domain = address.partition("@")
    if not domain:
        return "***"
    return f"{local[:1]}***@{domain}"


def preview_config() -> dict[str, object]:
    """Non-secret view of the delivery setup, for the Integrations screen.

    Deliberately reports whether a credential is *present*, never its value.
    """

    return {
        "provider": "mailjet_smtp",
        "send_enabled": settings.EMAIL_SEND_ENABLED,
        "configured": is_configured(),
        "missing_settings": _missing_settings(),
        "smtp_host": settings.SMTP_HOST,
        "smtp_port": settings.SMTP_PORT,
        "from_address": settings.EMAIL_FROM_ADDRESS,
        "from_name": settings.EMAIL_FROM_NAME,
    }


__all__ = [
    "STATUS_DRY_RUN",
    "STATUS_FAILED",
    "STATUS_SENT",
    "DeliveryResult",
    "EmailNotConfiguredError",
    "is_configured",
    "preview_config",
    "send",
]


# Deliberately absent: a `send_bulk` helper. Every send in this product passes
# Gate 2 individually, so a batch entry point would be a way to bypass the one
# control that makes AI-written email safe to deliver.
