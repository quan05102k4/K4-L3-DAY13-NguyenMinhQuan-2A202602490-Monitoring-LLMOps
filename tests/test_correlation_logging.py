from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import httpx

from app import logging_config
from app.logging_config import scrub_event
from app.main import app
from app.middleware import resolve_correlation_id

PAYLOAD = {
    "user_id": "student-01",
    "session_id": "session-01",
    "feature": "qa",
    "message": "Call 0901234567 or mail a@b.com about 4111 1111 1111 1111",
}


async def _post(headers: dict[str, str] | None = None) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post("/chat", json=PAYLOAD, headers=headers or {})


def test_generated_correlation_id_format() -> None:
    assert re.fullmatch(r"req-[0-9a-f]{8}", resolve_correlation_id(None))
    assert re.fullmatch(r"req-[0-9a-f]{8}", resolve_correlation_id("bad id\nwith newline"))
    assert resolve_correlation_id("req-abcdef12") == "req-abcdef12"


def test_request_id_is_propagated_to_header_body_and_logs(monkeypatch, tmp_path: Path) -> None:
    log_path = tmp_path / "logs.jsonl"
    monkeypatch.setattr(logging_config, "LOG_PATH", log_path)

    response = asyncio.run(_post({"x-request-id": "req-0badc0de"}))

    assert response.headers["x-request-id"] == "req-0badc0de"
    assert float(response.headers["x-response-time-ms"]) >= 0
    assert response.json()["correlation_id"] == "req-0badc0de"
    events = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    api_events = [e for e in events if e.get("service") == "api"]
    assert {e["event"] for e in api_events} == {"request_received", "response_sent"}
    for event in api_events:
        assert event["correlation_id"] == "req-0badc0de"
        assert event["feature"] == "qa" and event["session_id"] == "session-01"
        assert event["model"] and event["env"] and event["user_id_hash"]
        assert "student-01" not in json.dumps(event)


def test_context_does_not_leak_between_requests(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(logging_config, "LOG_PATH", tmp_path / "logs.jsonl")

    first = asyncio.run(_post())
    second = asyncio.run(_post())

    assert first.headers["x-request-id"] != second.headers["x-request-id"]


def test_logs_do_not_contain_raw_pii(monkeypatch, tmp_path: Path) -> None:
    log_path = tmp_path / "logs.jsonl"
    monkeypatch.setattr(logging_config, "LOG_PATH", log_path)

    asyncio.run(_post())

    raw = log_path.read_text(encoding="utf-8")
    for secret in ("0901234567", "a@b.com", "4111 1111 1111 1111"):
        assert secret not in raw


def test_scrub_event_handles_nested_and_top_level_fields() -> None:
    event = scrub_event(None, "info", {
        "event": "request_failed",
        "detail": "user a@b.com failed",
        "payload": {"nested": {"phone": "0901234567"}, "items": ["001203004567"]},
        "latency_ms": 12,
    })
    dumped = json.dumps(event)
    assert "a@b.com" not in dumped and "0901234567" not in dumped and "001203004567" not in dumped
    assert event["latency_ms"] == 12
