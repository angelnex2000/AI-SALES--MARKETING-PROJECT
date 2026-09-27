"""Gathers the raw material the Research Agent reasons over.

MVP scope: everything here comes from data the tenant already holds — the
lead record and the notes their reps wrote. No outbound network calls.

**Read this before changing how fetching works.** `Lead.website` is user input:
it arrives via lead creation, CSV import, or CRM sync. Fetching it from our
server is a server-side request forgery vector, and a nastier one than usual
because the response is *persisted into a research report and shown to a
user* — an exfiltration channel, not a blind request. A worker that follows
`http://169.254.169.254/latest/meta-data/` returns cloud credentials; one
that follows `http://localhost:6379` reaches our own Redis.

`validate_fetchable_url()` below is the guard that must pass before any
request is made. Since fetching moved to TinyFish it is defence in depth
rather than the primary control — their infrastructure makes the request, so a
hostname resolving to loopback reaches theirs, not ours — but the response is
still persisted and shown to a user, so the guard stays. Anything fetched
in-process in future must go through it again.
"""

import ipaddress
import logging
import socket
from urllib.parse import urlparse

from agents.research import web
from agents.research.schemas import ResearchInput

logger = logging.getLogger(__name__)

ALLOWED_SCHEMES = frozenset({"http", "https"})
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
FETCH_TIMEOUT_SECONDS = 10


class UnsafeURLError(ValueError):
    """The URL resolves somewhere we must never fetch from."""


def validate_fetchable_url(raw_url: str) -> str:
    """Raise `UnsafeURLError` unless this URL is safe for the server to fetch.

    Checks the resolved IP, not just the hostname string: `internal.example.com`
    can resolve to 127.0.0.1, so blocklisting names is not enough.
    """

    parsed = urlparse(raw_url)
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise UnsafeURLError(f"scheme {parsed.scheme!r} is not fetchable")
    if not parsed.hostname:
        raise UnsafeURLError("URL has no host")

    try:
        resolved = socket.getaddrinfo(parsed.hostname, None)
    except socket.gaierror as exc:
        raise UnsafeURLError(f"could not resolve {parsed.hostname!r}") from exc

    for *_, sockaddr in resolved:
        address = ipaddress.ip_address(sockaddr[0])
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local  # 169.254.0.0/16 — cloud metadata
            or address.is_reserved
            or address.is_multicast
            or address.is_unspecified
        ):
            raise UnsafeURLError(f"{parsed.hostname} resolves to non-public {address}")
    return raw_url


def safe_website(raw_url: str | None) -> str | None:
    """The lead's website, if it is safe to ask anyone to fetch it.

    **The threat model shifted when fetching moved to TinyFish, but it did not
    disappear.** Their infrastructure makes the request, so a URL resolving to
    `127.0.0.1` or `169.254.169.254` reaches *their* loopback, not ours — the
    classic SSRF path is closed by architecture rather than by this check.
    What remains is that the response is still persisted into a report and
    shown to a user, so this stays as the filter that keeps obviously-internal
    hostnames out of a third party's request logs and keeps junk out of the
    pipeline. Returns None rather than raising: a malformed website is a
    missing input, not a failed research run.
    """

    if not (raw_url or "").strip():
        return None
    try:
        return validate_fetchable_url(raw_url)
    except UnsafeURLError as exc:
        logger.info("skipping website fetch: %s", exc)
        return None


async def collect(payload: ResearchInput) -> tuple[dict[str, object], list[str]]:
    """Return `(context, sources)` for the agent to reason over.

    `sources` names every origin consulted, so the report can cite them — a
    rep may repeat these claims to a prospect.

    Async since live web sourcing landed. The network step is best-effort: if
    TinyFish is unconfigured or unreachable, `context["web"]` reports
    `available=False` and the agent produces the same report it always did from
    lead data and CRM notes, with a correspondingly lower coverage confidence.
    """

    context: dict[str, object] = {
        "company_name": payload.company_name,
        "industry": payload.industry,
        "website": payload.website,
        "country": payload.country,
        "city": payload.city,
        "employees": payload.employees,
        "annual_revenue": payload.annual_revenue,
        "lead_source": payload.source,
        "crm_notes": payload.crm_notes,
    }

    sources = ["lead_database"]
    if payload.crm_notes:
        sources.append("crm_notes")

    web_sources = await web.gather(
        company_name=payload.company_name, website=safe_website(payload.website)
    )
    context["web"] = web_sources
    # Only origins actually consulted are listed. Naming `web_search` after a
    # failed call would put a source on a report that contributed nothing.
    for name, present in (
        ("web_search", bool(web_sources.news)),
        ("company_website", bool(web_sources.site_summary)),
    ):
        if present:
            sources.append(name)

    return context, sources
