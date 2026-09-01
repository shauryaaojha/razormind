"""The model boundary. One interface, and everything above it is replaceable.

This is the only module in the project that imports a vendor SDK, and it is the
only one allowed to (contract 1 in ``.importlinter``: ``tools``,
``reconciliation``, ``runtime``, ``verification``, ``evidence`` and
``provenance`` cannot reach ``llm`` at all, and the build fails if one tries).

Two things follow from that, and both are the point:

* **The model never returns a number anyone believes.** It returns an intent --
  which window, which comparison, which kind of question -- and later a phrasing
  of numbers it was handed. Every figure is computed and verified underneath it.
* **Absent is a supported state, not an outage.** With no API key, or with
  ``llm_enabled`` off, :func:`get_provider` returns a provider that refuses
  every call with ``PROVIDER_UNAVAILABLE``. Callers degrade -- the intent parser
  asks for clarification, and Phase 7's explainer renders the verified metrics
  from a template. A system whose numbers depend on a third party being up is
  not a system anyone should run a month-end close on.

Structured output is a **forced tool call**, not a "please reply in JSON"
instruction. The schema goes to the provider as the tool's input schema, so the
model's output is constrained rather than requested, and a parse failure is a
real failure rather than a prose apology that happens to contain braces.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from config.settings import Settings, get_settings

__all__ = [
    "Completion",
    "DisabledProvider",
    "LLMProvider",
    "ProviderError",
    "ProviderTimeoutError",
    "ProviderUnavailableError",
    "get_provider",
]

#: The name the forced tool call is given. It appears in the request and in the
#: response block, and nowhere else.
STRUCTURED_TOOL = "emit"


class ProviderError(Exception):
    """A call to the model failed. Carries a stable code for the caller to switch on."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


class ProviderUnavailableError(ProviderError):
    """No provider is configured, or the call could not be made at all."""

    def __init__(self, message: str) -> None:
        super().__init__("PROVIDER_UNAVAILABLE", message)


class ProviderTimeoutError(ProviderError):
    """The model did not answer inside the budget."""

    def __init__(self, message: str) -> None:
        super().__init__("PROVIDER_TIMEOUT", message)


@dataclass(frozen=True)
class Completion:
    """One structured response, plus what it cost.

    ``text`` is JSON matching the requested schema. It is deliberately *not*
    parsed here: the caller owns the model it validates against, and a provider
    that returned already-parsed objects would have to know about every schema
    in the system.
    """

    text: str
    model: str
    input_tokens: int
    output_tokens: int


class LLMProvider(Protocol):
    """What the agent plane is allowed to ask of a model."""

    name: str

    async def structured(
        self,
        *,
        system: str,
        prompt: str,
        schema: Mapping[str, Any],
        max_tokens: int,
        timeout_seconds: int,
    ) -> Completion:
        """Return JSON conforming to ``schema``, or raise a :class:`ProviderError`."""
        ...


class DisabledProvider:
    """The provider used when there is no model. It refuses, loudly and cheaply.

    Returning a canned answer here would be far worse than refusing: a plausible
    intent parsed from nothing is how a question about July gets answered with
    August's numbers, verified and cited, with nothing anywhere indicating that
    no model was ever consulted.
    """

    name = "disabled"

    def __init__(self, reason: str) -> None:
        self._reason = reason

    async def structured(
        self,
        *,
        system: str,
        prompt: str,
        schema: Mapping[str, Any],
        max_tokens: int,
        timeout_seconds: int,
    ) -> Completion:
        del system, prompt, schema, max_tokens, timeout_seconds
        raise ProviderUnavailableError(self._reason)


class AnthropicProvider:
    """The one real implementation.

    ``temperature=0`` because an execution is supposed to be reproducible.
    That is *not* determinism -- the API offers no seed, and two identical
    requests may still differ -- which is exactly why nothing downstream trusts
    the response for anything but routing and phrasing.
    """

    name = "anthropic"

    def __init__(self, api_key: str, model: str) -> None:
        # Imported here rather than at module scope so that a deployment with no
        # model configured does not need the SDK present to start.
        from anthropic import AsyncAnthropic

        self._client = AsyncAnthropic(api_key=api_key)
        self._model = model

    async def structured(
        self,
        *,
        system: str,
        prompt: str,
        schema: Mapping[str, Any],
        max_tokens: int,
        timeout_seconds: int,
    ) -> Completion:
        from anthropic import APIError, APITimeoutError
        from anthropic.types import ToolUseBlock

        try:
            message = await self._client.messages.create(
                model=self._model,
                max_tokens=max_tokens,
                temperature=0,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                tools=[
                    {
                        "name": STRUCTURED_TOOL,
                        "description": "Return the structured result.",
                        "input_schema": dict(schema),
                    }
                ],
                tool_choice={"type": "tool", "name": STRUCTURED_TOOL},
                timeout=float(timeout_seconds),
            )
        except APITimeoutError as error:
            raise ProviderTimeoutError(f"no response in {timeout_seconds}s") from error
        except APIError as error:
            raise ProviderUnavailableError(str(error)) from error

        for block in message.content:
            # A response carries several block kinds and only one of them has a
            # tool name; narrowing on the class rather than on `type` is what
            # makes that safe to read.
            if isinstance(block, ToolUseBlock) and block.name == STRUCTURED_TOOL:
                return Completion(
                    text=json.dumps(block.input),
                    model=message.model,
                    input_tokens=message.usage.input_tokens,
                    output_tokens=message.usage.output_tokens,
                )
        raise ProviderUnavailableError(
            "the model returned no structured block despite a forced tool call"
        )


def get_provider(settings: Settings | None = None) -> LLMProvider:
    """The configured provider, or one that refuses.

    Both branches are supported paths. Which one is in use is visible to the
    caller through ``provider.name``, and ends up on the execution record as
    ``response_source``, so "no model was available" is a fact the UI can state
    rather than something a reader has to infer from the wording.
    """
    resolved = settings or get_settings()
    if not resolved.llm_enabled:
        return DisabledProvider("llm_enabled is false")
    if not resolved.anthropic_api_key:
        return DisabledProvider("no ANTHROPIC_API_KEY is configured")
    return AnthropicProvider(resolved.anthropic_api_key, resolved.llm_model)
