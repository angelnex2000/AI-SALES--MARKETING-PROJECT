"""LLM providers for the Outreach Agent.

The Outreach Agent is the only `determinism="llm"` agent in the system, and the
only one whose output a human approves before a customer sees it. This module
is what lets it run on either Anthropic or OpenAI without the rest of the agent
knowing which.

## One prompt, shaped at the boundary

The obvious way to support two providers is two prompt paths, and that is how
the wording silently diverges: someone fixes a hedging instruction in one and
not the other, and half the drafts start asserting inferred pain points as
fact. So `prompts.build_messages()` remains the **single** definition of what
the model is told, and each adapter reshapes that one structure for its own
wire format — Anthropic takes the system prompt as a separate argument, OpenAI
takes it as `messages[0]`. `prompts.PROMPT_VERSION` therefore still means one
thing across both providers.

## What genuinely differs, and why it is not hidden

Two provider differences are real and are recorded rather than papered over:

* **Determinism.** OpenAI runs at `TEMPERATURE = 0.4` because this is
  correspondence a rep is judged on and run-to-run variance is a cost.
  `claude-opus-5` **rejects `temperature` with a 400** — the equivalent lever
  there is `effort: "low"`, which is what the Anthropic adapter sets. Same
  intent, different control.
* **Output enforcement.** OpenAI's `response_format={"type": "json_object"}`
  guarantees *valid JSON*; Anthropic's `output_config.format` with a JSON
  Schema guarantees *this* JSON. The Anthropic path is the stronger of the
  two, so the shared post-parse validation still runs but has less to catch.

Which provider produced a draft is recorded on `EmailDraft.llm_model` and in
the agent's `model_version`, because a complaint about a claim in a sent email
has to be traceable to the exact model that wrote it.
"""

import json
import logging
from typing import Any, Protocol

from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

from agents.outreach import prompts
from app.core.config import settings

logger = logging.getLogger(__name__)

# The shape every provider must return. Anthropic enforces it server-side;
# OpenAI is asked for valid JSON and checked here.
DRAFT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "subject": {"type": "string", "description": "Email subject line."},
        "body": {"type": "string", "description": "Email body, with [S1]-style citation markers."},
    },
    "required": ["subject", "body"],
    "additionalProperties": False,
}


class LLMUnavailableError(RuntimeError):
    """No provider configured, or generation failed.

    Always fatal for a draft. The tempting fallback — a template with the
    company name substituted in — *is* the generic email this feature exists
    to replace, relabelled as AI-personalised.
    """


class LLMProvider(Protocol):
    name: str
    model: str

    async def generate(self, messages: list[dict[str, str]]) -> dict[str, Any]: ...


def _parse(content: str) -> dict[str, Any]:
    """Malformed JSON is a generation failure, not a draft.

    Storing the raw text would put unvalidated model output in front of a rep
    with a Send button next to it.
    """

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise LLMUnavailableError("model did not return valid JSON") from exc
    if not isinstance(parsed, dict):
        raise LLMUnavailableError("model returned JSON that is not an object")
    return parsed


class AnthropicProvider:
    """Claude via the Anthropic SDK.

    `max_tokens` is far larger than the OpenAI path's 600 for a reason that is
    easy to get wrong: on `claude-opus-5` thinking is **on by default**, and
    `max_tokens` caps thinking *plus* response text together. A 600-token cap
    carried over from the OpenAI settings would truncate mid-draft, and the
    failure would look like a model problem rather than a configuration one.
    """

    name = "anthropic"

    # Effort, not temperature: `temperature` returns a 400 on this model, and
    # `low` is the documented lever for holding variance down on short,
    # well-specified output like a single email.
    EFFORT = "low"
    MAX_TOKENS = 8000

    def __init__(self) -> None:
        self.model = settings.ANTHROPIC_MODEL

    async def generate(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        system, turns = prompts.split_system(messages)
        client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        try:
            response = await client.messages.create(
                model=self.model,
                max_tokens=self.MAX_TOKENS,
                system=system,
                messages=turns,
                output_config={
                    "effort": self.EFFORT,
                    "format": {"type": "json_schema", "schema": DRAFT_SCHEMA},
                },
            )
        except Exception as exc:
            logger.error("anthropic outreach generation failed", exc_info=exc)
            raise LLMUnavailableError(str(exc)) from exc

        # `output_config.format` guarantees the response is schema-valid JSON,
        # but a refusal short-circuits it — check the stop reason before
        # reading content, or a refused request raises IndexError here.
        if getattr(response, "stop_reason", None) == "refusal":
            raise LLMUnavailableError(
                "model declined to generate this draft "
                f"({getattr(getattr(response, 'stop_details', None), 'category', 'unspecified')})"
            )
        text = next((b.text for b in response.content if b.type == "text"), "")
        if not text:
            raise LLMUnavailableError("model returned no text content")
        return _parse(text)


class OpenAIProvider:
    """GPT via the OpenAI SDK — the original implementation, unchanged in
    behaviour."""

    name = "openai"

    TEMPERATURE = 0.4
    """Low. This is business correspondence a rep will be judged on, not
    creative writing — run-to-run variance is a cost, not a feature."""
    MAX_TOKENS = 600

    def __init__(self) -> None:
        self.model = settings.OPENAI_MODEL

    async def generate(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        try:
            response = await client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=self.TEMPERATURE,
                max_tokens=self.MAX_TOKENS,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content or "{}"
        except Exception as exc:
            logger.error("openai outreach generation failed", exc_info=exc)
            raise LLMUnavailableError(str(exc)) from exc
        return _parse(content)


def configured_providers() -> list[str]:
    """Which providers have a key. Order is the `auto` preference order."""

    available = []
    if settings.ANTHROPIC_API_KEY:
        available.append("anthropic")
    if settings.OPENAI_API_KEY:
        available.append("openai")
    return available


def resolve() -> LLMProvider:
    """Pick the provider for this run.

    `auto` (the default) takes the first configured provider rather than
    failing when one key is absent — a workspace that has only ever set one is
    the common case, and demanding an explicit choice there is friction with no
    safety benefit. An explicit `LLM_PROVIDER` is honoured even if that
    provider is unconfigured, so a deliberate choice fails loudly instead of
    silently falling through to the other vendor and billing the wrong account.
    """

    choice = (settings.LLM_PROVIDER or "auto").lower()
    if choice == "auto":
        available = configured_providers()
        if not available:
            raise LLMUnavailableError(
                "No LLM provider configured — set ANTHROPIC_API_KEY or OPENAI_API_KEY. "
                "A templated fallback is the generic email this feature replaces."
            )
        choice = available[0]

    if choice == "anthropic":
        if not settings.ANTHROPIC_API_KEY:
            raise LLMUnavailableError("LLM_PROVIDER=anthropic but ANTHROPIC_API_KEY is not set")
        return AnthropicProvider()
    if choice == "openai":
        if not settings.OPENAI_API_KEY:
            raise LLMUnavailableError("LLM_PROVIDER=openai but OPENAI_API_KEY is not set")
        return OpenAIProvider()
    raise LLMUnavailableError(f"Unknown LLM_PROVIDER {choice!r} — expected anthropic, openai or auto")


def describe(provider: LLMProvider) -> str:
    """The version string stored on every draft.

    Carries the provider as well as the model: `gpt-4o-mini` and
    `claude-opus-5` are obviously different, but a future model name might not
    be, and `EmailDraft.llm_model` is what a complaint about a sent claim is
    traced through.
    """

    return f"outreach-{provider.name}-{provider.model}-{prompts.PROMPT_VERSION}"


__all__ = [
    "DRAFT_SCHEMA",
    "AnthropicProvider",
    "LLMProvider",
    "LLMUnavailableError",
    "OpenAIProvider",
    "configured_providers",
    "describe",
    "resolve",
]
