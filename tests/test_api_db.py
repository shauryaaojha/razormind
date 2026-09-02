"""The API surface against a real Postgres: accept, stream, resume, list.

Four exit criteria live here. The fifth -- the OpenAPI document matching the
app -- is a `check` step rather than a test, because a stale contract should
fail the build before anything runs.

The progressive-delivery test reads frames as they arrive and records *when*.
Asserting that the right events eventually turn up would pass just as happily
against an endpoint that buffered the whole run and flushed at the end, which
is exactly the design [C-14](../docs/00-corrections.md) is about.

That one test drives `event_frames` directly rather than going over HTTP.
httpx's ASGI transport runs the app to completion and hands back the collected
body, so nothing measured through it can distinguish a streaming endpoint from
a buffering one. The rest of the file goes through the real routes, where the
timing does not matter.
"""

import asyncio
import json
import time
import uuid
from collections.abc import Mapping
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select

from llm.provider import Completion
from main import create_app
from routes import agent as agent_routes
from runtime.db import connection
from runtime.schema import agent_executions

pytestmark = pytest.mark.db

MERCHANT = "M123"
OWNER = "11111111-1111-4111-8111-111111111111"
ANALYST = "22222222-2222-4222-8222-222222222222"
VIEWER = "33333333-3333-4333-8333-333333333333"
OUTSIDER = "99999999-9999-4999-8999-999999999999"

QUESTION = "Why did net revenue fall in August?"

AUGUST = {"from": "2026-08-01", "to": "2026-08-24"}
JULY = {"from": "2026-07-01", "to": "2026-07-24"}


class IntentOnlyProvider:
    """Scripts the intent, refuses the explanation. See `test_agent_db.py`."""

    name = "scripted"

    def __init__(self) -> None:
        self._body = json.dumps(
            {
                "intent": "revenue_diagnosis",
                "merchant_id": MERCHANT,
                "period": AUGUST,
                "comparison_period": JULY,
                "confidence_ratio": "0.95",
                "clarification_needed": False,
            }
        )

    async def structured(
        self,
        *,
        system: str,
        prompt: str,
        schema: Mapping[str, Any],
        max_tokens: int,
        timeout_seconds: int,
    ) -> Completion:
        del system, prompt, max_tokens, timeout_seconds
        if "narrative" in schema.get("properties", {}):
            from llm.provider import ProviderUnavailableError

            raise ProviderUnavailableError("this scripted provider only parses intents")
        return Completion(text=self._body, model="scripted", input_tokens=0, output_tokens=0)


@pytest.fixture(autouse=True)
def scripted_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """The route asks for a provider; give it one that routes."""
    monkeypatch.setattr(agent_routes, "get_provider", lambda *args: IntentOnlyProvider())


@pytest.fixture
async def client() -> Any:
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://api") as opened:
        yield opened


def headers(user: str = ANALYST) -> dict[str, str]:
    return {"X-RazorMind-User": user}


async def start(client: httpx.AsyncClient, **body: Any) -> httpx.Response:
    payload = {"merchant_id": MERCHANT, "message": QUESTION, **body}
    return await client.post("/api/v1/agent/runs", json=payload, headers=headers())


async def frames(
    client: httpx.AsyncClient, execution_id: str, **kwargs: Any
) -> list[tuple[float, dict[str, Any]]]:
    """Every SSE frame, with the moment it arrived."""
    received: list[tuple[float, dict[str, Any]]] = []
    url = f"/api/v1/agent/runs/{execution_id}/events"
    async with client.stream("GET", url, timeout=90, **kwargs) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        async for line in response.aiter_lines():
            if line.startswith("data: "):
                received.append((time.monotonic(), json.loads(line.removeprefix("data: "))))
    return received


async def settle(execution_id: str) -> str:
    """Wait for the background run to reach a terminal state."""
    for _ in range(600):
        async with connection() as conn:
            status = (
                await conn.execute(
                    select(agent_executions.c.status).where(
                        agent_executions.c.id == uuid.UUID(execution_id)
                    )
                )
            ).scalar_one()
        if status in agent_routes.TERMINAL_STATES:
            return str(status)
        await asyncio.sleep(0.1)
    raise AssertionError(f"execution {execution_id} never finished")


# --------------------------------------------------------------------------
# accepting a run
# --------------------------------------------------------------------------


async def test_a_run_is_accepted_and_its_row_exists_immediately(
    client: httpx.AsyncClient,
) -> None:
    """202 hands back an id, and the id resolves. Not "ask again in a moment"."""
    response = await start(client)
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "PENDING"
    assert body["replayed"] is False

    fetched = await client.get(f"/api/v1/executions/{body['execution_id']}")
    assert fetched.status_code == 200
    assert fetched.json()["merchant_id"] == MERCHANT

    assert await settle(body["execution_id"]) == "COMPLETED"


async def test_replaying_a_client_request_id_returns_the_original_run(
    client: httpx.AsyncClient,
) -> None:
    key = f"c_{uuid.uuid4()}"
    first = await start(client, client_request_id=key)
    second = await start(client, client_request_id=key)

    assert first.status_code == 202
    assert second.json()["execution_id"] == first.json()["execution_id"]
    assert second.json()["replayed"] is True

    async with connection() as conn:
        count = (
            await conn.execute(
                select(func.count())
                .select_from(agent_executions)
                .where(agent_executions.c.client_request_id == key)
            )
        ).scalar_one()
    assert count == 1
    await settle(first.json()["execution_id"])


async def test_a_foreign_merchant_is_refused_before_anything_runs(
    client: httpx.AsyncClient,
) -> None:
    response = await client.post(
        "/api/v1/agent/runs",
        json={"merchant_id": MERCHANT, "message": QUESTION},
        headers=headers(OUTSIDER),
    )
    assert response.status_code == 403
    assert response.json()["detail"]["error"]["code"] == "MERCHANT_SCOPE_VIOLATION"

    async with connection() as conn:
        count = (
            await conn.execute(
                select(func.count())
                .select_from(agent_executions)
                .where(agent_executions.c.user_id == uuid.UUID(OUTSIDER))
            )
        ).scalar_one()
    assert count == 0


async def test_a_viewer_may_read_but_not_run(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/v1/agent/runs",
        json={"merchant_id": MERCHANT, "message": QUESTION},
        headers=headers(VIEWER),
    )
    assert response.status_code == 403
    assert response.json()["detail"]["error"]["code"] == "INSUFFICIENT_PERMISSION"


async def test_an_unidentified_caller_is_refused(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/v1/agent/runs", json={"merchant_id": MERCHANT, "message": QUESTION}
    )
    assert response.status_code == 401


async def test_an_owner_may_run(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/v1/agent/runs",
        json={"merchant_id": MERCHANT, "message": QUESTION},
        headers=headers(OWNER),
    )
    assert response.status_code == 202
    await settle(response.json()["execution_id"])


# --------------------------------------------------------------------------
# the stream
# --------------------------------------------------------------------------


async def test_events_arrive_progressively_rather_than_in_one_burst(
    client: httpx.AsyncClient,
) -> None:
    """The whole point of C-14: something to render while the DAG is running."""
    execution_id = (await start(client)).json()["execution_id"]

    received: list[tuple[float, dict[str, Any]]] = []
    async for frame in agent_routes.event_frames(uuid.UUID(execution_id), 0):
        for line in frame.splitlines():
            if line.startswith("data: "):
                received.append((time.monotonic(), json.loads(line.removeprefix("data: "))))

    kinds = [payload["kind"] for _, payload in received]
    assert kinds[0] == "execution.created"
    assert kinds[-1] == "execution.finished"
    assert "node.started" in kinds

    first, last = received[0][0], received[-1][0]
    assert last - first > 0.1, "every frame arrived at once; the stream is buffering"
    # And not merely spread out: the last frame arrives at the end of the run,
    # not at the start of it.
    assert received[-1][0] - received[0][0] > (received[1][0] - received[0][0])

    # And the frames genuinely track the run: the tool events land before the
    # verification event, which lands before the answer.
    assert kinds.index("node.started") < kinds.index("verification.finished")
    assert kinds.index("verification.finished") < kinds.index("explanation.grounded")


async def test_a_finished_run_replays_identically(client: httpx.AsyncClient) -> None:
    """History and live chat are the same rows, so they cannot disagree."""
    execution_id = (await start(client)).json()["execution_id"]
    live = [payload for _, payload in await frames(client, execution_id)]
    await settle(execution_id)
    replayed = [payload for _, payload in await frames(client, execution_id)]

    assert [event["seq"] for event in live] == [event["seq"] for event in replayed]
    assert [event["kind"] for event in live] == [event["kind"] for event in replayed]


async def test_last_event_id_resumes_with_no_gap_and_no_repeat(
    client: httpx.AsyncClient,
) -> None:
    execution_id = (await start(client)).json()["execution_id"]
    await settle(execution_id)

    whole = [payload["seq"] for _, payload in await frames(client, execution_id)]
    assert whole == list(range(len(whole)))

    resumed = [
        payload["seq"]
        for _, payload in await frames(client, execution_id, headers={"Last-Event-ID": "3"})
    ]
    assert resumed == whole[4:]


async def test_a_malformed_last_event_id_replays_from_the_start(
    client: httpx.AsyncClient,
) -> None:
    """A browser sends the header itself; refusing its reconnect helps nobody."""
    execution_id = (await start(client)).json()["execution_id"]
    await settle(execution_id)
    resumed = [
        payload["seq"]
        for _, payload in await frames(client, execution_id, headers={"Last-Event-ID": "nonsense"})
    ]
    assert resumed[0] == 0


async def test_every_frame_carries_a_channel_and_an_id(client: httpx.AsyncClient) -> None:
    execution_id = (await start(client)).json()["execution_id"]
    await settle(execution_id)

    url = f"/api/v1/agent/runs/{execution_id}/events"
    async with client.stream("GET", url, timeout=90) as response:
        body = "".join([chunk async for chunk in response.aiter_text()])

    for block in [part for part in body.split("\n\n") if part.strip()]:
        assert block.startswith("id: ")
        assert "\nevent: " in block
        assert "\ndata: " in block


async def test_streaming_an_unknown_execution_is_a_404(client: httpx.AsyncClient) -> None:
    response = await client.get(f"/api/v1/agent/runs/{uuid.uuid4()}/events")
    assert response.status_code == 404


# --------------------------------------------------------------------------
# history
# --------------------------------------------------------------------------


async def test_history_lists_newest_first_and_pages_by_keyset(
    client: httpx.AsyncClient,
) -> None:
    for _ in range(3):
        await settle((await start(client)).json()["execution_id"])

    page = (
        await client.get("/api/v1/executions", params={"merchant_id": MERCHANT, "limit": 2})
    ).json()
    assert len(page["items"]) == 2
    assert page["items"][0]["created_at"] >= page["items"][1]["created_at"]
    assert page["next_cursor"] is not None
    assert page["items"][0]["question"] == QUESTION

    following = (
        await client.get(
            "/api/v1/executions",
            params={"merchant_id": MERCHANT, "limit": 2, "cursor": page["next_cursor"]},
        )
    ).json()
    seen = {item["execution_id"] for item in page["items"]}
    assert not seen & {item["execution_id"] for item in following["items"]}


async def test_history_can_be_filtered_by_status(client: httpx.AsyncClient) -> None:
    await settle((await start(client)).json()["execution_id"])
    page = (
        await client.get(
            "/api/v1/executions", params={"merchant_id": MERCHANT, "status": "COMPLETED"}
        )
    ).json()
    assert page["items"]
    assert {item["status"] for item in page["items"]} == {"COMPLETED"}


async def test_a_completed_execution_serves_its_answer_and_claims(
    client: httpx.AsyncClient,
) -> None:
    execution_id = (await start(client)).json()["execution_id"]
    await settle(execution_id)

    body = (await client.get(f"/api/v1/executions/{execution_id}")).json()
    assert body["status"] == "COMPLETED"
    assert body["response_source"] == "TEMPLATE_FALLBACK"
    assert body["answer"]
    assert body["claims"]

    # Every claim resolves to a row the evidence endpoint will serve. This is
    # what makes a number in the prose clickable.
    index = (await client.get(f"/api/v1/executions/{execution_id}/evidence")).json()
    published = {item["evidence_id"] for item in index["items"]}
    assert {claim["evidence_id"] for claim in body["claims"]} <= published
