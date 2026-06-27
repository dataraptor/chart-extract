"""Split 11 — Batch API re-association by ``custom_id`` (Tier-1, pure, no network).

The Batch API returns results **unordered**; the load-bearing guarantee is that
:func:`collate_results` re-keys each result to the right request and **surfaces** any id that never
came back. These tests pin that contract on the pure path (the live submission is ``@pytest.mark.
api``).
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from chartextract import BatchRequest, MissingBatchResultError, collate_results, run_openai_batch
from chartextract.batch import _as_obj
from chartextract.provider.base import ProviderError
from chartextract.provider.openai import OpenAIProvider
from chartextract.schemas import Field, IntakeSchema, PathologySchema


def _req(cid: str, schema=PathologySchema) -> BatchRequest:
    return BatchRequest(custom_id=cid, system="SYS", document_text="DOC", schema_model=schema)


def test_unordered_results_reassociate_to_the_right_request() -> None:
    requests = [_req("doc_a"), _req("doc_b", IntakeSchema), _req("doc_c")]
    # Results arrive in a DIFFERENT order than submitted (the Batch API gives no ordering).
    results = {"doc_c": "C", "doc_a": "A", "doc_b": "B"}
    pairs = collate_results(requests, results)
    # Re-ordered back to request order, each result on its own request.
    assert [r.custom_id for r, _ in pairs] == ["doc_a", "doc_b", "doc_c"]
    assert [v for _, v in pairs] == ["A", "B", "C"]
    # The id is the join key — never positional.
    by_id = {r.custom_id: v for r, v in pairs}
    assert by_id["doc_b"] == "B"


def test_missing_custom_id_is_surfaced_not_silently_dropped() -> None:
    requests = [_req("doc_a"), _req("doc_b"), _req("doc_c")]
    results = {"doc_a": "A", "doc_c": "C"}  # doc_b never came back
    with pytest.raises(MissingBatchResultError) as ei:
        collate_results(requests, results)
    assert ei.value.missing == ["doc_b"]
    assert "doc_b" in str(ei.value)


def test_extra_results_are_ignored_only_requested_ids_returned() -> None:
    requests = [_req("doc_a")]
    results = {"doc_a": "A", "doc_z": "Z"}  # a stray id we never asked for
    pairs = collate_results(requests, results)
    assert [r.custom_id for r, _ in pairs] == ["doc_a"]


def test_duplicate_custom_id_in_requests_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate custom_id"):
        collate_results([_req("dup"), _req("dup")], {"dup": "X"})


def test_empty_batch_is_an_empty_result() -> None:
    assert collate_results([], {}) == []


# --- run_openai_batch over a fake client (no network) ------------------------


def _path_json() -> str:
    inst = PathologySchema(
        specimen=Field(value="Left breast core biopsy", source_span="x", confidence=0.9),
        diagnosis=Field(value="Invasive ductal carcinoma", source_span="x", confidence=0.9),
        grade=Field(value="2", source_span="x", confidence=0.9),
        tumor_size_cm=Field(value=1.4, source_span="x", confidence=0.9),
        er_status=Field(value="positive", source_span="x", confidence=0.9),
        pr_status=Field(value="positive", source_span="x", confidence=0.9),
        her2_status=Field(value="negative", source_span="x", confidence=0.9),
        margin_status=Field(value=None, source_span="", confidence=0.0),
        lymph_nodes_positive=Field(value=None, source_span="", confidence=0.0),
    )
    return inst.model_dump_json()


class _FakeBatchClient:
    """A no-network OpenAI client that completes a batch immediately, results UNORDERED."""

    def __init__(self, *, status: str = "completed", lines: list[str] | None = None) -> None:
        self._status = status
        self._lines = lines
        self.created: dict[str, Any] = {}
        self.files = SimpleNamespace(create=self._files_create, content=self._files_content)
        self.batches = SimpleNamespace(create=self._batches_create, retrieve=self._batches_retrieve)

    def _files_create(self, *, file: Any, purpose: str) -> SimpleNamespace:
        self.created["upload_purpose"] = purpose
        self.created["upload_bytes"] = file[1] if isinstance(file, tuple) else file
        return SimpleNamespace(id="file_in")

    def _batches_create(self, **kw: Any) -> SimpleNamespace:
        self.created["batch_kwargs"] = kw
        return SimpleNamespace(id="batch_1", status="validating")

    def _batches_retrieve(self, _id: str) -> SimpleNamespace:
        return SimpleNamespace(id="batch_1", status=self._status, output_file_id="file_out")

    def _files_content(self, _id: str) -> SimpleNamespace:
        return SimpleNamespace(text="\n".join(self._lines or []))


def _result_line(cid: str, content: str, *, prompt: int = 1200, cached: int = 0) -> str:
    return json.dumps(
        {
            "custom_id": cid,
            "response": {
                "body": {
                    "choices": [{"message": {"content": content}}],
                    "usage": {
                        "prompt_tokens": prompt,
                        "completion_tokens": 180,
                        "prompt_tokens_details": {"cached_tokens": cached},
                    },
                }
            },
        }
    )


def _provider_with(client: Any) -> OpenAIProvider:
    return OpenAIProvider(client=client)


def test_run_openai_batch_submits_and_collects_unordered() -> None:
    reqs = [_req("doc_a"), _req("doc_b")]
    # Results come back b-then-a (unordered); doc_b carries a cached prefix.
    client = _FakeBatchClient(
        lines=[
            _result_line("doc_b", _path_json(), prompt=5000, cached=4096),
            _result_line("doc_a", _path_json()),
        ]
    )
    out = run_openai_batch(_provider_with(client), reqs, poll_seconds=0)
    assert set(out) == {"doc_a", "doc_b"}
    parsed_b, usage_b = out["doc_b"]
    assert isinstance(parsed_b, PathologySchema)
    # the cached prefix is split out of the fresh input (no double-count).
    assert usage_b.cache_read_input_tokens == 4096
    assert usage_b.input_tokens == 904
    # request bodies carry the strict schema + custom_id + no sampling params.
    body = json.loads(client.created["upload_bytes"].decode("utf-8").splitlines()[0])
    assert body["custom_id"] == "doc_a"
    assert body["body"]["response_format"]["json_schema"]["strict"] is True
    assert "temperature" not in body["body"]
    assert client.created["upload_purpose"] == "batch"


def test_run_openai_batch_surfaces_a_failed_batch() -> None:
    client = _FakeBatchClient(status="failed")
    with pytest.raises(ProviderError, match="failed"):
        run_openai_batch(_provider_with(client), [_req("doc_a")], poll_seconds=0)


def test_as_obj_handles_missing_usage() -> None:
    assert _as_obj(None) is None
    obj = _as_obj({"prompt_tokens": 10, "completion_tokens": 2})
    assert obj.prompt_tokens == 10
    assert obj.prompt_tokens_details is None
