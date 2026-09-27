"""Personalized Outreach Agent.

Assembles everything the platform knows about a lead — research, evidenced
signals, campaign strategy, and the tenant's own approved documents — and
drafts one email. It never sends: output lands in `EmailDraft` at
`pending_approval`, and Gate 2 is enforced in `outreach_service`.

Three behaviours worth stating plainly, because each is a place this feature
could quietly cause harm:

**No LLM, no draft.** If the model is unavailable the agent raises and says
why. The tempting alternative — fall back to a template with the company name
substituted in — reproduces the exact generic email this feature exists to
replace, while labelling it AI-personalised.

**No proof, no claims.** When RAG returns nothing, the prompt switches to a
mode that forbids specific claims rather than asking for a best effort. A
shorter honest email beats an impressive invented one.

**Validation gates presentation, not sending.** A draft failing structural
checks is still stored — a reviewer may want to fix it — but carries its
findings so the UI leads with the problem instead of showing it as ready.

Which LLM writes the draft is `providers`' concern, not this module's: the
agent assembles context, hands one prompt to whatever `LLM_PROVIDER` resolves
to, and records the answer. That is why `model_version` is computed per run
rather than fixed at import — the same code path can produce a Claude draft and
a GPT draft, and `EmailDraft.llm_model` has to say which.
"""

import logging
from typing import Any

from agents.base import BaseAgent
from agents.outreach import prompts, providers
from agents.outreach.validator import strip_citation_markers, validate_draft
from agents.rag.prompt_builder import build_source_block

logger = logging.getLogger(__name__)

MODEL_NAME = "outreach"


class OutreachUnavailableError(RuntimeError):
    """No LLM configured, or generation failed. The caller must fail the job
    rather than substitute a template."""


class OutreachAgent(BaseAgent):
    async def run(self, input_data: dict[str, Any]) -> dict[str, Any]:
        recipient = input_data.get("recipient") or {}
        strategy = input_data.get("strategy") or {}
        chunks = input_data.get("chunks") or []

        source_block, citation_map = build_source_block(chunks)
        messages = prompts.build_messages(
            recipient=recipient, strategy=strategy, source_block=source_block
        )

        # Resolved per run, not per process: a deployment can switch provider
        # by environment without a restart, and the draft must record the one
        # that actually wrote it.
        provider = self._provider()
        raw = await self._generate(provider, messages)
        subject = (raw.get("subject") or "").strip()
        body_with_markers = (raw.get("body") or "").strip()

        result = validate_draft(subject=subject, body=body_with_markers, citation_map=citation_map)

        # Markers are stripped only after validation, so the stored body is
        # what would actually be sent while `rag_sources` records what backed it.
        body = strip_citation_markers(body_with_markers)

        return {
            "model_name": MODEL_NAME,
            "model_version": providers.describe(provider),
            "llm_provider": provider.name,
            "llm_model": provider.model,
            "prompt_version": prompts.PROMPT_VERSION,
            "subject": subject,
            "body": body,
            "body_with_citations": body_with_markers,
            "grounded": bool(citation_map) and result["citations"]["grounded"],
            "rag_sources": result["citations"]["chunk_ids"],
            "valid": result["valid"],
            "findings": result["findings"],
            "explanation": self._explanation(result, citation_map),
        }

    def _provider(self) -> providers.LLMProvider:
        try:
            return providers.resolve()
        except providers.LLMUnavailableError as exc:
            raise OutreachUnavailableError(str(exc)) from exc

    async def _generate(
        self, provider: providers.LLMProvider, messages: list[dict[str, str]]
    ) -> dict[str, Any]:
        """Delegate to the resolved provider, re-raising under the agent's own
        error type.

        The wrap keeps `OutreachUnavailableError` the single thing callers and
        `supervisor/failures.py` have to know about, and `from exc` preserves
        the cause chain — which is what the retry classifier actually reads to
        tell a provider timeout (retry) from an exhausted quota (don't).
        """

        try:
            return await provider.generate(messages)
        except providers.LLMUnavailableError as exc:
            logger.error("outreach generation failed on %s", provider.name)
            raise OutreachUnavailableError(str(exc)) from exc

    def _explanation(self, result: dict[str, Any], citation_map: dict[str, str]) -> str:
        parts: list[str] = []
        if citation_map:
            used = result["citations"]["cited_markers"]
            parts.append(
                f"Grounded in {len(used)} of {len(citation_map)} retrieved source(s)."
                if used
                else "Sources were retrieved but the draft cites none of them."
            )
        else:
            parts.append("No approved sources found, so the draft makes no specific claims.")

        blocking = [f["message"] for f in result["findings"] if f["severity"] == "block"]
        warnings = [f["message"] for f in result["findings"] if f["severity"] == "warn"]
        if blocking:
            parts.append("Needs attention: " + " ".join(blocking))
        if warnings:
            parts.append("Notes: " + " ".join(warnings))
        if not result["findings"]:
            parts.append("Passed structural checks — still requires human review before sending.")
        return " ".join(parts)
