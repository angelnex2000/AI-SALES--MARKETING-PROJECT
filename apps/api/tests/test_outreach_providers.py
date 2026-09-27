"""The pluggable LLM boundary for the Outreach Agent.

Two providers writing customer-facing email is a place where a *silent*
difference is expensive, so these tests pin the things that actually differ
between Anthropic and OpenAI — not just that both return a dict.
"""

import json

import pytest

from agents.outreach import prompts, providers
from agents.outreach.agent import OutreachAgent, OutreachUnavailableError
from agents.supervisor import failures
from tests.test_outreach_agent import GOOD_EMAIL, RECIPIENT, STRATEGY, draft


def messages() -> list[dict[str, str]]:
    return prompts.build_messages(recipient=RECIPIENT, strategy=STRATEGY, source_block="Sources")


def fake_anthropic(monkeypatch, *, response) -> dict:
    """Install a stub Anthropic client and return the dict its `create` call
    was made with."""

    captured: dict = {}

    class Messages:
        async def create(self, **kwargs):
            captured.update(kwargs)
            return response

    monkeypatch.setattr(
        providers, "AsyncAnthropic", lambda **_: type("C", (), {"messages": Messages()})()
    )
    monkeypatch.setattr(providers.settings, "ANTHROPIC_API_KEY", "test-key")
    return captured


def anthropic_response(text: str, stop_reason: str = "end_turn"):
    block = type("Block", (), {"type": "text", "text": text})()
    return type("Response", (), {"stop_reason": stop_reason, "content": [block]})()


class TestOnePromptDefinition:
    def test_split_system_redistributes_rather_than_rewrites(self):
        """The failure this abstraction exists to prevent is a second prompt
        path that drifts — a hedging instruction fixed for one vendor and not
        the other, so half the drafts assert an inferred pain point as fact."""

        built = messages()
        system, turns = prompts.split_system(built)

        assert system == built[0]["content"]
        assert turns == built[1:]
        assert all(m["role"] != "system" for m in turns)

    def test_the_evidence_inference_split_survives_the_reshape(self):
        system, turns = prompts.split_system(
            prompts.build_messages(recipient=RECIPIENT, strategy=STRATEGY, source_block="")
        )
        combined = system + " ".join(m["content"] for m in turns)
        assert "verified, safe to reference" in combined
        assert "NOT verified" in combined


class TestAnthropicAdapter:
    async def test_never_sends_temperature(self, monkeypatch):
        """`claude-opus-5` rejects `temperature` with a 400. The intent behind
        the OpenAI path's 0.4 — low run-to-run variance on correspondence a rep
        is judged on — carries over as `effort`, not as a temperature."""

        captured = fake_anthropic(monkeypatch, response=anthropic_response(json.dumps(GOOD_EMAIL)))
        result = await providers.AnthropicProvider().generate(messages())

        assert result["subject"] == GOOD_EMAIL["subject"]
        assert "temperature" not in captured
        assert "top_p" not in captured
        assert "top_k" not in captured
        assert captured["output_config"]["effort"] == "low"

    async def test_system_prompt_goes_in_its_own_argument(self, monkeypatch):
        captured = fake_anthropic(monkeypatch, response=anthropic_response(json.dumps(GOOD_EMAIL)))
        await providers.AnthropicProvider().generate(messages())

        assert isinstance(captured["system"], str) and captured["system"]
        assert all(m["role"] != "system" for m in captured["messages"])

    async def test_schema_is_enforced_server_side(self, monkeypatch):
        """A schema without `additionalProperties: false` and `required` is
        accepted and enforces nothing, which reads as working."""

        captured = fake_anthropic(monkeypatch, response=anthropic_response(json.dumps(GOOD_EMAIL)))
        await providers.AnthropicProvider().generate(messages())

        schema = captured["output_config"]["format"]["schema"]
        assert captured["output_config"]["format"]["type"] == "json_schema"
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == {"subject", "body"}

    def test_max_tokens_leaves_room_for_thinking(self):
        """Thinking is on by default on this model and `max_tokens` caps
        thinking *plus* response text together, so carrying the OpenAI path's
        600 across would truncate mid-draft — and the failure would look like a
        model fault rather than a configuration one."""

        assert providers.AnthropicProvider.MAX_TOKENS > providers.OpenAIProvider.MAX_TOKENS * 5

    async def test_refusal_is_an_error_not_an_empty_draft(self, monkeypatch):
        """A refusal short-circuits the structured output, so reading the first
        content block blind would raise IndexError and surface as an unrelated
        crash instead of "the model declined"."""

        fake_anthropic(
            monkeypatch,
            response=type("R", (), {"stop_reason": "refusal", "content": []})(),
        )
        with pytest.raises(providers.LLMUnavailableError, match="declined"):
            await providers.AnthropicProvider().generate(messages())

    async def test_malformed_json_is_a_failure_not_a_draft(self, monkeypatch):
        fake_anthropic(monkeypatch, response=anthropic_response("not json"))
        with pytest.raises(providers.LLMUnavailableError):
            await providers.AnthropicProvider().generate(messages())


class TestSelection:
    def test_auto_prefers_anthropic_then_falls_back_to_openai(self, monkeypatch):
        monkeypatch.setattr(providers.settings, "LLM_PROVIDER", "auto")
        monkeypatch.setattr(providers.settings, "ANTHROPIC_API_KEY", "a")
        monkeypatch.setattr(providers.settings, "OPENAI_API_KEY", "o")
        assert providers.resolve().name == "anthropic"

        monkeypatch.setattr(providers.settings, "ANTHROPIC_API_KEY", "")
        assert providers.resolve().name == "openai"

    def test_explicit_choice_fails_loudly_instead_of_switching_vendor(self, monkeypatch):
        """Silently falling through to the other provider would bill an account
        the operator did not choose and change which model wrote a draft with
        nothing recording it."""

        monkeypatch.setattr(providers.settings, "LLM_PROVIDER", "anthropic")
        monkeypatch.setattr(providers.settings, "ANTHROPIC_API_KEY", "")
        monkeypatch.setattr(providers.settings, "OPENAI_API_KEY", "o")
        with pytest.raises(providers.LLMUnavailableError, match="ANTHROPIC_API_KEY"):
            providers.resolve()

    def test_nothing_configured_refuses_rather_than_templating(self, monkeypatch):
        monkeypatch.setattr(providers.settings, "LLM_PROVIDER", "auto")
        monkeypatch.setattr(providers.settings, "ANTHROPIC_API_KEY", "")
        monkeypatch.setattr(providers.settings, "OPENAI_API_KEY", "")
        with pytest.raises(providers.LLMUnavailableError, match="No LLM provider configured"):
            providers.resolve()

    def test_version_string_names_the_provider(self, monkeypatch):
        """`EmailDraft.llm_model` is how a complaint about a claim in a sent
        email is traced back to what wrote it — model name alone may not be
        unambiguous for a future model."""

        monkeypatch.setattr(providers.settings, "ANTHROPIC_MODEL", "claude-opus-5")
        described = providers.describe(providers.AnthropicProvider())
        assert "anthropic" in described
        assert "claude-opus-5" in described
        assert prompts.PROMPT_VERSION in described


class TestAgentIntegration:
    async def test_the_draft_records_which_provider_wrote_it(self, monkeypatch):
        result = await draft(monkeypatch)
        assert result["llm_provider"] == "openai"
        assert result["llm_model"] == "gpt-4o-mini"
        assert result["model_version"].startswith("outreach-openai-")

    async def test_anthropic_produces_the_same_draft_shape(self, monkeypatch):
        """The pluggable boundary is only worth having if the rest of the
        pipeline — validation, citation stripping, `rag_sources` — behaves
        identically whichever vendor answered."""

        fake_anthropic(monkeypatch, response=anthropic_response(json.dumps(GOOD_EMAIL)))
        monkeypatch.setattr(providers.settings, "LLM_PROVIDER", "anthropic")

        result = await OutreachAgent().run(
            {
                "recipient": RECIPIENT,
                "strategy": STRATEGY,
                "chunks": [
                    {
                        "chunk_id": "chunk-1",
                        "document_title": "CityCare Case Study",
                        "text": "CityCare Hospital reduced support workload by 35%.",
                    }
                ],
            }
        )

        assert result["llm_provider"] == "anthropic"
        assert result["grounded"] is True
        assert result["rag_sources"] == ["chunk-1"]
        assert "[S1]" not in result["body"]

    async def test_provider_failure_keeps_its_cause_for_the_retry_classifier(self, monkeypatch):
        """`supervisor/failures.py` walks `__cause__` to tell a provider
        timeout (retry) from an exhausted quota (do not). Re-raising without
        `from` would flatten every failure into one indistinguishable case."""

        class Boom(Exception):
            code = "insufficient_quota"

        class Completions:
            async def create(self, **_):
                raise Boom("no credits")

        monkeypatch.setattr(providers.settings, "LLM_PROVIDER", "openai")
        monkeypatch.setattr(providers.settings, "OPENAI_API_KEY", "test-key")
        monkeypatch.setattr(
            providers,
            "AsyncOpenAI",
            lambda **_: type("C", (), {"chat": type("Ch", (), {"completions": Completions()})()})(),
        )

        with pytest.raises(OutreachUnavailableError) as caught:
            await OutreachAgent().run({"recipient": RECIPIENT, "strategy": STRATEGY})

        assert isinstance(caught.value.__cause__, providers.LLMUnavailableError)
        assert failures.is_transient(caught.value) is False
