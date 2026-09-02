"""The Groq provider, and which provider a configuration selects.

The interesting assertions here are not "the happy path parses". They are the
ways an OpenAI-compatible endpoint can hand back something that is not a
structured result -- a refusal, a plain-prose answer, arguments that are not
JSON, a transport that never answers -- each of which must reach the caller as a
named :class:`ProviderError` rather than as a ``KeyError`` three frames deeper.
"""

import json
from typing import Any

import httpx
import pytest
from pydantic_settings import SettingsConfigDict

from config.settings import Settings
from llm.provider import (
    AnthropicProvider,
    Completion,
    DisabledProvider,
    GeminiProvider,
    GroqProvider,
    LLMProvider,
    ProviderTimeoutError,
    ProviderUnavailableError,
    get_provider,
    openapi_subset,
)

Handler = Any

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"window": {"type": "string"}},
    "required": ["window"],
}


def _payload(arguments: str, *, name: str = "emit") -> dict[str, Any]:
    return {
        "model": "openai/gpt-oss-120b",
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_01",
                            "type": "function",
                            "function": {"name": name, "arguments": arguments},
                        }
                    ],
                }
            }
        ],
        "usage": {
            "queue_time": 0.01,
            "prompt_tokens": 411,
            "prompt_time": 0.02,
            "completion_tokens": 37,
            "completion_time": 0.13,
            "total_tokens": 448,
            "total_time": 0.15,
        },
    }


def _provider(handler: Handler) -> GroqProvider:
    return GroqProvider(
        "gsk_test",
        "openai/gpt-oss-120b",
        transport=httpx.MockTransport(handler),
    )


async def _call(provider: GroqProvider) -> Completion:
    return await provider.structured(
        system="you are a parser",
        prompt="how did revenue move in July",
        schema=SCHEMA,
        max_tokens=1024,
        timeout_seconds=30,
    )


# ------------------------------------------------------------------ the call


async def test_a_forced_tool_call_round_trips() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_payload('{"window": "2024-07"}'))

    completion = await _call(_provider(handler))

    assert json.loads(completion.text) == {"window": "2024-07"}
    assert completion.model == "openai/gpt-oss-120b"
    assert completion.input_tokens == 411
    assert completion.output_tokens == 37


async def test_the_request_forces_the_named_tool_and_carries_the_schema() -> None:
    """The schema is what constrains the model, so it has to actually be sent."""
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        seen["authorization"] = request.headers["authorization"]
        return httpx.Response(200, json=_payload('{"window": "2024-07"}'))

    await _call(_provider(handler))

    assert seen["authorization"] == "Bearer gsk_test"
    assert seen["model"] == "openai/gpt-oss-120b"
    assert seen["tool_choice"] == {"type": "function", "function": {"name": "emit"}}
    assert seen["tools"][0]["function"]["name"] == "emit"
    assert seen["tools"][0]["function"]["parameters"] == SCHEMA


async def test_the_system_prompt_is_a_system_turn() -> None:
    """Folded into the user message it would be a prompt the user can argue with."""
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, json=_payload('{"window": "2024-07"}'))

    await _call(_provider(handler))

    assert [message["role"] for message in seen["messages"]] == ["system", "user"]
    assert seen["messages"][0]["content"] == "you are a parser"
    assert seen["messages"][1]["content"] == "how did revenue move in July"


# --------------------------------------------------------------- the failures


async def test_a_prose_answer_is_a_named_failure_not_a_key_error() -> None:
    """The model ignored the forced call and answered in prose."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "openai/gpt-oss-120b",
                "choices": [{"message": {"role": "assistant", "content": "I cannot help."}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 4},
            },
        )

    with pytest.raises(ProviderUnavailableError) as raised:
        await _call(_provider(handler))
    assert "forced tool call" in str(raised.value)


async def test_a_call_to_some_other_tool_is_not_accepted() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_payload('{"w": "2024-07"}', name="something_else"))

    with pytest.raises(ProviderUnavailableError):
        await _call(_provider(handler))


async def test_arguments_that_are_not_json_fail_here_not_downstream() -> None:
    """An open-weight model putting an apology in ``arguments`` is a real event."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_payload("Sure! Here is the window: 2024-07"))

    with pytest.raises(ProviderUnavailableError) as raised:
        await _call(_provider(handler))
    assert "not JSON" in str(raised.value)


async def test_a_rate_limit_carries_the_status_and_is_truncated() -> None:
    """Groq's free tier rate-limits, and an error body can echo the request back."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="rate limit reached: " + "x" * 5000)

    with pytest.raises(ProviderUnavailableError) as raised:
        await _call(_provider(handler))
    message = str(raised.value)
    assert "429" in message
    assert len(message) < 300


async def test_a_timeout_is_a_timeout_not_an_outage() -> None:
    """The caller switches on the code, so the two must not collapse into one."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow", request=request)

    with pytest.raises(ProviderTimeoutError) as raised:
        await _call(_provider(handler))
    assert "30s" in str(raised.value)


async def test_a_transport_error_is_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host", request=request)

    with pytest.raises(ProviderUnavailableError):
        await _call(_provider(handler))


# ------------------------------------------------------------------ selection


class _Isolated(Settings):
    """Settings with the env file off, so a developer's own ``.env`` cannot
    decide whether this suite passes."""

    model_config = SettingsConfigDict(env_file=None)


def _settings(**overrides: Any) -> Settings:
    return _Isolated(**overrides)


async def _refusal(provider: LLMProvider) -> str:
    with pytest.raises(ProviderUnavailableError) as raised:
        await provider.structured(system="", prompt="", schema={}, max_tokens=1, timeout_seconds=1)
    return str(raised.value)


def test_the_provider_is_named_not_inferred_from_whichever_key_is_present() -> None:
    """Both keys set, and the setting decides. Nothing is picked by accident."""
    provider = get_provider(
        _settings(
            llm_enabled=True,
            llm_provider="groq",
            anthropic_api_key="sk-ant-test",
            groq_api_key="gsk_test",
        )
    )
    assert isinstance(provider, GroqProvider)
    assert provider.name == "groq"


def test_anthropic_stays_the_default() -> None:
    settings = _settings(llm_enabled=True, anthropic_api_key="sk-ant-test", groq_api_key="gsk_test")
    assert isinstance(get_provider(settings), AnthropicProvider)


async def test_a_missing_key_names_the_key_it_wanted() -> None:
    """A provider that refuses without saying why is how a bad deploy survives."""
    groq = get_provider(_settings(llm_enabled=True, llm_provider="groq"))
    anthropic = get_provider(_settings(llm_enabled=True, llm_provider="anthropic"))

    assert isinstance(groq, DisabledProvider)
    assert isinstance(anthropic, DisabledProvider)
    assert "GROQ_API_KEY" in await _refusal(groq)
    assert "ANTHROPIC_API_KEY" in await _refusal(anthropic)


def test_the_switch_beats_a_configured_key() -> None:
    settings = _settings(llm_enabled=False, llm_provider="groq", groq_api_key="gsk_test")
    assert isinstance(get_provider(settings), DisabledProvider)


def test_all_three_vendors_are_reachable_by_name() -> None:
    keys = {
        "anthropic": ("anthropic_api_key", AnthropicProvider),
        "groq": ("groq_api_key", GroqProvider),
        "gemini": ("gemini_api_key", GeminiProvider),
    }
    for vendor, (field, expected) in keys.items():
        settings = _settings(llm_enabled=True, llm_provider=vendor, **{field: "test-key"})
        assert isinstance(get_provider(settings), expected), vendor


async def test_a_missing_gemini_key_names_the_key_it_wanted() -> None:
    provider = get_provider(_settings(llm_enabled=True, llm_provider="gemini"))
    assert isinstance(provider, DisabledProvider)
    assert "GEMINI_API_KEY" in await _refusal(provider)


# -------------------------------------------------------------------- gemini


def _gemini_payload(args: dict[str, Any], *, name: str = "emit") -> dict[str, Any]:
    return {
        "candidates": [
            {
                "content": {
                    "role": "model",
                    "parts": [{"functionCall": {"name": name, "args": args}}],
                },
                "finishReason": "STOP",
            }
        ],
        "usageMetadata": {"promptTokenCount": 11207, "candidatesTokenCount": 1117},
    }


def _gemini(handler: Handler, *, model: str = "gemini-flash-lite-latest") -> GeminiProvider:
    return GeminiProvider("test-key", model, transport=httpx.MockTransport(handler))


async def _gemini_call(provider: GeminiProvider) -> Completion:
    return await provider.structured(
        system="you are a parser",
        prompt="how did revenue move in July",
        schema=SCHEMA,
        max_tokens=1024,
        timeout_seconds=30,
    )


async def test_gemini_round_trips_a_forced_call() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_gemini_payload({"window": "2026-07"}))

    completion = await _gemini_call(_gemini(handler))

    assert json.loads(completion.text) == {"window": "2026-07"}
    assert completion.input_tokens == 11207
    assert completion.output_tokens == 1117
    # Gemini does not echo the model, so this is the one that was asked for.
    assert completion.model == "gemini-flash-lite-latest"


async def test_gemini_forces_the_call_in_its_own_spelling() -> None:
    """`ANY` plus exactly one allowed name is how Gemini forces a named tool."""
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        seen["key"] = request.headers["x-goog-api-key"]
        seen["url"] = str(request.url)
        return httpx.Response(200, json=_gemini_payload({"window": "2026-07"}))

    await _gemini_call(_gemini(handler))

    assert seen["key"] == "test-key"
    assert seen["url"].endswith("/models/gemini-flash-lite-latest:generateContent")
    assert seen["toolConfig"]["functionCallingConfig"] == {
        "mode": "ANY",
        "allowedFunctionNames": ["emit"],
    }
    assert seen["tools"][0]["functionDeclarations"][0]["name"] == "emit"
    # The system prompt is its own field here, not a first message.
    assert seen["systemInstruction"]["parts"][0]["text"] == "you are a parser"
    assert seen["contents"][0]["parts"][0]["text"] == "how did revenue move in July"


async def test_gemini_retries_a_capacity_error_once() -> None:
    """503 means "ask again", and the free tier says it often."""
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(503, json={"error": {"message": "high demand"}})
        return httpx.Response(200, json=_gemini_payload({"window": "2026-07"}))

    completion = await _gemini_call(_gemini(handler))

    assert len(calls) == 2
    assert json.loads(completion.text) == {"window": "2026-07"}


async def test_gemini_gives_up_after_one_retry() -> None:
    """The retry is for a blip. A provider that is down stays down."""
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(503, json={"error": {"message": "high demand"}})

    with pytest.raises(ProviderUnavailableError) as raised:
        await _gemini_call(_gemini(handler))
    assert len(calls) == 2
    assert "503" in str(raised.value)


async def test_a_thinking_model_that_never_emitted_the_call_says_so() -> None:
    """`MAX_TOKENS` and a refusal are different problems with different fixes."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "candidates": [{"content": {"role": "model"}, "finishReason": "MAX_TOKENS"}],
                "usageMetadata": {"promptTokenCount": 11207, "thoughtsTokenCount": 4096},
            },
        )

    with pytest.raises(ProviderUnavailableError) as raised:
        await _gemini_call(_gemini(handler))
    assert "MAX_TOKENS" in str(raised.value)


async def test_gemini_times_out_as_a_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow", request=request)

    with pytest.raises(ProviderTimeoutError):
        await _gemini_call(_gemini(handler))


# ------------------------------------------------------ the schema dialect


def test_the_declaration_drops_what_gemini_rejects() -> None:
    """`additionalProperties` is a 400, and pydantic emits it for every model."""
    translated = openapi_subset(
        {
            "type": "object",
            "additionalProperties": False,
            "properties": {"window": {"type": "string", "additionalProperties": False}},
            "required": ["window"],
        }
    )
    assert "additionalProperties" not in translated
    assert "additionalProperties" not in translated["properties"]["window"]
    assert translated["required"] == ["window"]


def test_an_optional_field_becomes_nullable() -> None:
    """`X | None` is `anyOf: [X, null]` in pydantic and `nullable` in OpenAPI."""
    translated = openapi_subset(
        {
            "type": "object",
            "properties": {
                "period": {
                    "anyOf": [{"type": "string", "format": "date"}, {"type": "null"}],
                    "default": None,
                }
            },
        }
    )
    period = translated["properties"]["period"]
    assert period["type"] == "string"
    assert period["nullable"] is True
    assert "anyOf" not in period


def test_a_real_union_keeps_its_anyof() -> None:
    """Only the null arm collapses. `int | Decimal` is a choice the model makes."""
    translated = openapi_subset(
        {"anyOf": [{"type": "integer"}, {"type": "string", "pattern": "^-?[0-9.]+$"}]}
    )
    assert [option["type"] for option in translated["anyOf"]] == ["integer", "string"]


def test_the_allowlist_survives_a_keyword_nobody_has_seen_yet() -> None:
    """A denylist would pass an unknown keyword through to a 400 in production."""
    translated = openapi_subset({"type": "string", "$comment": "x", "unevaluatedItems": True})
    assert translated == {"type": "string"}


def test_the_real_schemas_translate_to_something_gemini_accepts() -> None:
    """The two schemas that actually go over the wire, checked as a whole."""
    from intent.models import Intent
    from llm.explainer import Draft
    from llm.provider import json_schema_for

    for model in (Draft, Intent):
        translated = openapi_subset(json_schema_for(model))
        assert "additionalProperties" not in json.dumps(translated)
        assert '"type": "null"' not in json.dumps(translated)
        assert translated["properties"]
