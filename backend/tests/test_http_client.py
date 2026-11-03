import httpx2
import pytest

from airsight.ingestion.http_client import get_json

URL = "https://api.example.com/data"


def client_returning(*responses: httpx2.Response | Exception) -> tuple[httpx2.Client, list[str]]:
    """A client whose server replies with the given responses in order, recording each call."""
    calls: list[str] = []
    replies = list(responses)

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(str(request.url))
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    return httpx2.Client(transport=httpx2.MockTransport(handler)), calls


def test_returns_parsed_json() -> None:
    client, _ = client_returning(httpx2.Response(200, json={"ok": True}))

    assert get_json(client, URL) == {"ok": True}


def test_retries_temporary_failures_then_succeeds() -> None:
    client, calls = client_returning(
        httpx2.Response(503),
        httpx2.ConnectError("connection refused"),
        httpx2.Response(200, json={"ok": True}),
    )
    waits: list[float] = []

    assert get_json(client, URL, sleep=waits.append) == {"ok": True}
    assert len(calls) == 3
    assert len(waits) == 2
    assert waits[0] < waits[1]  # backoff grows


def test_does_not_retry_a_bad_key() -> None:
    client, calls = client_returning(httpx2.Response(401))

    with pytest.raises(httpx2.HTTPStatusError):
        get_json(client, URL, sleep=lambda _: None)
    assert len(calls) == 1


def test_gives_up_after_the_last_attempt() -> None:
    client, calls = client_returning(*[httpx2.Response(500) for _ in range(4)])

    with pytest.raises(httpx2.HTTPStatusError):
        get_json(client, URL, attempts=4, sleep=lambda _: None)
    assert len(calls) == 4


def test_waits_as_long_as_the_server_asks() -> None:
    client, _ = client_returning(
        httpx2.Response(429, headers={"Retry-After": "7"}),
        httpx2.Response(200, json={}),
    )
    waits: list[float] = []

    get_json(client, URL, sleep=waits.append)

    assert waits == [7.0]
