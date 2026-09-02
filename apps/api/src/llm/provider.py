"""The model boundary. One interface, and everything above it is replaceable.

This is the only module in the project that talks to a model vendor, and it is
the only one allowed to (contract 1 in ``.importlinter``: ``tools``,
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

Two vendors implement that: Anthropic, and Groq's open-weight models on a free
tier. They are interchangeable *because* nothing above this module trusts a
model with a number -- swapping a frontier model for an 70B open-weight one
changes how often an answer is phrased well, and changes nothing about whether
a figure on screen is correct (D-57).
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, assert_never

import httpx
from pydantic import BaseModel

from config.settings import Settings, get_settings

__all__ = [
    "AnthropicProvider",
    "Completion",
    "DisabledProvider",
    "GroqProvider",
    "LLMProvider",
    "ProviderError",
    "ProviderTimeoutError",
    "ProviderUnavailableError",
    "get_provider",
    "json_schema_for",
]

#: The name the forced tool call is given. It appears in the request and in the
#: response block, and nowhere else.
STRUCTURED_TOOL = "emit"


def json_schema_for(model: type[BaseModel]) -> dict[str, Any]:
    """The input schema for a forced tool call, generated from a pydantic model.

    Generated rather than written out, so the thing the model is constrained to
    and the thing its response is validated against cannot drift apart. ``$ref``
    is resolved inline because a self-contained schema is what a reader of the
    prompt log can actually check a response against -- a log entry that points
    at a definition it does not contain is a log entry nobody audits.
    """
    schema: dict[str, Any] = model.model_json_schema(by_alias=True)
    defs = schema.pop("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/$defs/"):
                return resolve(dict(defs[ref.removeprefix("#/$defs/")]))
            return {key: resolve(value) for key, value in node.items()}
        if isinstance(node, list):
            return [resolve(item) for item in node]
        return node

    resolved: dict[str, Any] = resolve(schema)
    return resolved


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


class GroqProvider:
    """Groq's OpenAI-compatible endpoint, spoken over ``httpx``.

    Deliberately not the ``groq`` SDK. The whole surface used here is one POST,
    and ``httpx`` is already a dependency -- so this costs no image rebuild, and
    more importantly it keeps the count of vendor SDKs in the tree at one, which
    is the number contract 3 in ``.importlinter`` can meaningfully police.

    The open-weight models behind this are materially weaker than the frontier
    one, and the system is built so that this is a quality question rather than
    a correctness one. Both places a model is consulted are guarded: an intent
    below ``intent_confidence_threshold`` asks instead of assuming, and an
    explanation that does not byte-match the verified rows is discarded for the
    deterministic template. A weaker model trips those gates more often. It
    cannot get past them.
    """

    name = "groq"

    #: Groq's OpenAI-compatible base. The path is fixed here rather than
    #: configurable: a settable model endpoint is a settable exfiltration
    #: target, and the prompts carry a merchant's figures.
    ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._transport = transport

    async def structured(
        self,
        *,
        system: str,
        prompt: str,
        schema: Mapping[str, Any],
        max_tokens: int,
        timeout_seconds: int,
    ) -> Completion:
        body: dict[str, Any] = {
            "model": self._model,
            "max_completion_tokens": max_tokens,
            # Groq rewrites a temperature of 0 to 1e-8 rather than rejecting it,
            # so this is as close to reproducible as the endpoint offers. As
            # with Anthropic, nothing downstream depends on that being true.
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": STRUCTURED_TOOL,
                        "description": "Return the structured result.",
                        "parameters": dict(schema),
                    },
                }
            ],
            "tool_choice": {"type": "function", "function": {"name": STRUCTURED_TOOL}},
        }

        try:
            async with httpx.AsyncClient(
                timeout=float(timeout_seconds),
                transport=self._transport,
            ) as client:
                response = await client.post(
                    self.ENDPOINT,
                    json=body,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                )
        except httpx.TimeoutException as error:
            raise ProviderTimeoutError(f"no response in {timeout_seconds}s") from error
        except httpx.HTTPError as error:
            raise ProviderUnavailableError(str(error)) from error

        if response.status_code != httpx.codes.OK:
            # Truncated: the body of a 4xx from a model host has been known to
            # echo the request, and the request contains the merchant's figures.
            raise ProviderUnavailableError(
                f"groq returned {response.status_code}: {response.text[:200]}"
            )

        return self._completion(response.json())

    def _completion(self, payload: Mapping[str, Any]) -> Completion:
        """Pull the forced call's arguments out of an OpenAI-shaped response."""
        usage: Mapping[str, Any] = payload.get("usage") or {}
        for choice in payload.get("choices") or []:
            message: Mapping[str, Any] = choice.get("message") or {}
            for call in message.get("tool_calls") or []:
                function: Mapping[str, Any] = call.get("function") or {}
                if function.get("name") != STRUCTURED_TOOL:
                    continue
                return Completion(
                    # Unlike Anthropic, Groq returns the arguments as a JSON
                    # *string*. It is parsed and re-dumped rather than passed
                    # through, so that "the model did not emit JSON" surfaces
                    # here, as a provider failure, instead of downstream as a
                    # confusing schema mismatch.
                    text=json.dumps(_parsed(function.get("arguments"))),
                    model=str(payload.get("model") or self._model),
                    input_tokens=int(usage.get("prompt_tokens") or 0),
                    output_tokens=int(usage.get("completion_tokens") or 0),
                )
        raise ProviderUnavailableError(
            "the model returned no structured block despite a forced tool call"
        )


def _parsed(arguments: Any) -> Any:
    if not isinstance(arguments, str):
        raise ProviderUnavailableError(
            f"the tool call carried {type(arguments).__name__}, not JSON"
        )
    try:
        return json.loads(arguments)
    except json.JSONDecodeError as error:
        raise ProviderUnavailableError(f"the tool call arguments are not JSON: {error}") from error


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
    match resolved.llm_provider:
        case "anthropic":
            if not resolved.anthropic_api_key:
                return DisabledProvider("no ANTHROPIC_API_KEY is configured")
            return AnthropicProvider(resolved.anthropic_api_key, resolved.anthropic_model)
        case "groq":
            if not resolved.groq_api_key:
                return DisabledProvider("no GROQ_API_KEY is configured")
            return GroqProvider(resolved.groq_api_key, resolved.groq_model)
        case _:
            assert_never(resolved.llm_provider)
