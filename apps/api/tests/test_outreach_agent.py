"""Personalized Outreach Agent: grounding, validation, and refusal to fake it.

This agent's output reaches customers, so the tests are mostly about what it
declines to produce.
"""

import json

import pytest

from agents.outreach import prompts
from agents.outreach.agent import OutreachAgent, OutreachUnavailableError
from agents.outreach.validator import (
    MAX_BODY_CHARS,
    SEVERITY_BLOCK,
    strip_citation_markers,
    validate_draft,
)

CHUNKS = [
    {
        "chunk_id": "chunk-1",
        "document_title": "CityCare Case Study",
        "text": "CityCare Hospital reduced support workload by 35%.",
    }
]
RECIPIENT = {
    "company_name": "MedCare Hospital",
    "contact_name": "Rahul Sharma",
    "contact_title": "IT Director",
    "industry": "Healthcare",
    "summary": "MedCare operates 14 clinics.",
    "evidence": ["Expanded telemedicine services"],
    "hypotheses": ["Rising patient inquiry volume"],
    "signals": ["expansion"],
}
STRATEGY = {"email_style": "Consultative", "cta": "Schedule a demo"}

GOOD_EMAIL = {
    "subject": "Helping MedCare scale patient support",
    "body": (
        "Hi Rahul,\n\nI noticed MedCare has expanded its telemedicine services. "
        "Hospitals at that stage often see patient inquiry volume climb.\n\n"
        "One of our healthcare customers, CityCare Hospital, reduced support "
        "workload by 35% [S1].\n\nWould you be open to a 30-minute demo next week?"
        "\n\nRegards,\nAnkit"
    ),
}


def fake_llm(monkeypatch, payload: dict | str):
    """Stub the LLM. These tests exercise our orchestration and validation,
    not the provider."""

    content = payload if isinstance(payload, str) else json.dumps(payload)

    class Message:
        def __init__(self):
            self.content = content

    class Choice:
        def __init__(self):
            self.message = Message()

    class Completions:
        async def create(self, **_):
            return type("R", (), {"choices": [Choice()]})()

    class Chat:
        def __init__(self):
            self.completions = Completions()

    class FakeClient:
        def __init__(self, **_):
            self.chat = Chat()

    from agents.outreach import providers

    # Patched at the provider boundary, not on the agent: since the provider is
    # pluggable the agent no longer holds a client, and these tests are about
    # drafting behaviour rather than which vendor produced the JSON. The
    # adapters themselves are covered in TestProviders below.
    monkeypatch.setattr(providers.settings, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(providers.settings, "OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(providers, "AsyncOpenAI", FakeClient)


async def draft(monkeypatch, payload=None, chunks=None):
    fake_llm(monkeypatch, payload or GOOD_EMAIL)
    return await OutreachAgent().run(
        {
            "recipient": RECIPIENT,
            "strategy": STRATEGY,
            "chunks": CHUNKS if chunks is None else chunks,
        }
    )


class TestRefusalToFakeIt:
    """The failure mode that matters most: producing something plausible when
    it should produce nothing."""

    async def test_no_provider_configured_raises_rather_than_templating(self, monkeypatch):
        """A template with the company name substituted in is the generic
        email this feature exists to replace."""

        from agents.outreach import providers

        monkeypatch.setattr(providers.settings, "LLM_PROVIDER", "auto")
        monkeypatch.setattr(providers.settings, "OPENAI_API_KEY", "")
        monkeypatch.setattr(providers.settings, "ANTHROPIC_API_KEY", "")
        with pytest.raises(OutreachUnavailableError, match="No LLM provider configured"):
            await OutreachAgent().run({"recipient": RECIPIENT, "strategy": STRATEGY})

    async def test_malformed_json_is_a_failure_not_a_draft(self, monkeypatch):
        """Storing raw text would put unvalidated model output in front of a
        rep as if it had been checked."""

        with pytest.raises(OutreachUnavailableError):
            await draft(monkeypatch, payload="not json at all")

    async def test_non_object_json_is_rejected(self, monkeypatch):
        with pytest.raises(OutreachUnavailableError):
            await draft(monkeypatch, payload="[1, 2, 3]")


class TestGrounding:
    async def test_cited_claim_records_its_source_chunk(self, monkeypatch):
        result = await draft(monkeypatch)
        assert result["grounded"] is True
        assert result["rag_sources"] == ["chunk-1"]

    async def test_citation_markers_are_stripped_from_the_sent_body(self, monkeypatch):
        """Markers let the reviewer and validator trace claims; a prospect
        should never receive them."""

        result = await draft(monkeypatch)
        assert "[S1]" not in result["body"]
        assert "[S1]" in result["body_with_citations"]
        assert "35%" in result["body"]

    async def test_no_chunks_switches_to_a_no_claims_prompt(self, monkeypatch):
        messages = prompts.build_messages(recipient=RECIPIENT, strategy=STRATEGY, source_block="")
        assert "must NOT state any specific claim" in messages[0]["content"]

    async def test_ungrounded_draft_is_reported_as_such(self, monkeypatch):
        no_claims = {
            "subject": "Quick question about MedCare's telemedicine rollout",
            "body": (
                "Hi Rahul,\n\nI saw MedCare has expanded telemedicine services and "
                "wondered how the team is handling the extra coordination load.\n\n"
                "Would you be open to a short call to compare notes?\n\nRegards,\nAnkit"
            ),
        }
        result = await draft(monkeypatch, payload=no_claims, chunks=[])
        assert result["grounded"] is False
        assert "no specific claims" in result["explanation"]

    def test_inference_and_evidence_are_labelled_differently_in_the_prompt(self):
        """The model is told which is which so it hedges a guess instead of
        asserting it."""

        context = prompts.build_recipient_context(RECIPIENT)
        assert "verified, safe to reference" in context
        assert "NOT verified" in context
        assert context.index("Observed") < context.index("Inferred")


class TestValidator:
    citation_map = {"S1": "chunk-1"}

    def test_clean_draft_passes(self):
        result = validate_draft(
            subject=GOOD_EMAIL["subject"], body=GOOD_EMAIL["body"],
            citation_map=self.citation_map,
        )
        assert result["valid"] is True
        assert result["blocking_count"] == 0

    def test_uncited_figure_blocks(self):
        """The literal shape of the failure this feature exists to prevent."""

        result = validate_draft(
            subject="Hi",
            body="We reduced hospital support cost by 80%. Want a demo? " + "x" * 200,
            citation_map=self.citation_map,
        )
        assert result["valid"] is False
        assert any(f["code"] == "UNCITED_FIGURE" for f in result["findings"])

    def test_citation_to_a_source_never_retrieved_blocks(self):
        result = validate_draft(
            subject="Hi",
            body="Our customers save time [S9]. Shall we book a call? " + "x" * 200,
            citation_map=self.citation_map,
        )
        assert any(f["code"] == "UNKNOWN_CITATION" for f in result["findings"])

    @pytest.mark.parametrize(
        "body", ["Hi {{first_name}}, shall we talk? " + "x" * 200, "Hi <COMPANY>, a demo? " + "x" * 200]
    )
    def test_unfilled_placeholders_block(self, body):
        """Shipping "Hi {{first_name}}" reads worse to a prospect than any
        hallucination."""

        result = validate_draft(subject="Hi", body=body, citation_map={})
        assert result["valid"] is False
        assert any(f["code"] == "UNFILLED_PLACEHOLDER" for f in result["findings"])

    @pytest.mark.parametrize("phrase", ["we guarantee results", "100% success", "risk-free"])
    def test_overclaims_block(self, phrase):
        result = validate_draft(
            subject="Hi", body=f"Hello, {phrase} for you. Want a demo? " + "x" * 200,
            citation_map={},
        )
        assert result["valid"] is False
        assert any(f["code"] == "OVERCLAIM" for f in result["findings"])

    def test_empty_subject_or_body_blocks(self):
        assert validate_draft(subject="", body="x" * 300, citation_map={})["valid"] is False
        assert validate_draft(subject="Hi", body="", citation_map={})["valid"] is False

    def test_missing_cta_warns_but_does_not_block(self):
        result = validate_draft(
            subject="Hello", body="Just letting you know about our platform. " * 10,
            citation_map={},
        )
        assert any(f["code"] == "NO_CTA" for f in result["findings"])
        assert result["valid"] is True, "a missing CTA is a style issue, not unsafe"

    def test_overlong_body_warns(self):
        result = validate_draft(
            subject="Hi", body="word " * (MAX_BODY_CHARS // 2), citation_map={}
        )
        assert any(f["code"] == "BODY_TOO_LONG" for f in result["findings"])

    def test_blocking_findings_are_marked_as_such(self):
        result = validate_draft(subject="", body="", citation_map={})
        assert all(
            f["severity"] == SEVERITY_BLOCK
            for f in result["findings"]
            if f["code"] in ("EMPTY_SUBJECT", "EMPTY_BODY")
        )

    def test_marker_stripping_leaves_readable_prose(self):
        assert strip_citation_markers("They saved 35% [S1]. Call?") == "They saved 35%. Call?"


class TestAuditTrail:
    """A complaint about a claim in a sent email must be traceable to the
    exact model, instructions and documents that produced it."""

    async def test_model_and_prompt_version_are_reported(self, monkeypatch):
        result = await draft(monkeypatch)
        assert result["llm_model"]
        assert result["prompt_version"] == prompts.PROMPT_VERSION
        assert prompts.PROMPT_VERSION in result["model_version"]

    async def test_findings_travel_with_the_draft(self, monkeypatch):
        bad = {"subject": "Hi", "body": "We guarantee 100% success. Demo? " + "x" * 200}
        result = await draft(monkeypatch, payload=bad)
        assert result["valid"] is False
        assert result["findings"]
        assert "Needs attention" in result["explanation"]

    async def test_a_flagged_draft_is_still_returned_for_a_human_to_fix(self, monkeypatch):
        """Validation gates presentation, not existence — editing and
        approving a flagged draft is a legitimate path."""

        bad = {"subject": "Hi", "body": "We guarantee results. Demo? " + "x" * 200}
        result = await draft(monkeypatch, payload=bad)
        assert result["subject"] and result["body"]
