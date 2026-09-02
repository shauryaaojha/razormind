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
    GroqProvider,
    LLMProvider,
    ProviderTimeoutError,
    ProviderUnavailableError,
    get_provider,
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
