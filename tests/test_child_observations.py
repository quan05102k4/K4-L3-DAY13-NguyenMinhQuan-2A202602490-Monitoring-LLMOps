from __future__ import annotations

import json

from app import mock_llm, mock_rag
from app.agent import LabAgent


class RecordingClient:
    def __init__(self) -> None:
        self.span_updates: list[dict] = []
        self.generation_updates: list[dict] = []

    def update_current_span(self, **kwargs) -> None:
        self.span_updates.append(kwargs)

    def update_current_generation(self, **kwargs) -> None:
        self.generation_updates.append(kwargs)


def test_generation_records_model_usage_and_cost_without_raw_prompt(monkeypatch) -> None:
    client = RecordingClient()
    monkeypatch.setattr(mock_llm, "get_langfuse_client", lambda: client)
    llm = mock_llm.FakeLLM(model="claude-sonnet-4-5")

    response = mock_llm.FakeLLM.generate.__wrapped__(llm, "Question=mail me at a@b.com")

    update = client.generation_updates[-1]
    assert update["model"] == "claude-sonnet-4-5"
    assert "input" not in update and "output" not in update
    assert update["usage_details"] == {
        "input": response.usage.input_tokens,
        "output": response.usage.output_tokens,
        "total": response.usage.input_tokens + response.usage.output_tokens,
    }
    assert update["cost_details"]["total"] == LabAgent()._estimate_cost(
        response.usage.input_tokens, response.usage.output_tokens
    )
    assert "a@b.com" not in json.dumps(update, default=str)


def test_retrieval_records_only_scrubbed_preview(monkeypatch) -> None:
    client = RecordingClient()
    monkeypatch.setattr(mock_rag, "get_langfuse_client", lambda: client)

    docs = mock_rag.retrieve.__wrapped__("refund for 0901234567")

    update = client.span_updates[-1]
    assert "input" not in update and "output" not in update
    assert update["metadata"]["doc_count"] == len(docs) == 1
    assert "0901234567" not in json.dumps(update)
    assert "REDACTED_PHONE_VN" in update["metadata"]["query_preview"]
