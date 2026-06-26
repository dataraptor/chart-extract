"""``/api/eval`` — the UIUX §5.5 leaderboard; halluc-rate 0 on the stub, deterministic (E8)."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_eval_shape_and_zero_hallucination(client: TestClient) -> None:
    resp = client.get("/api/eval")
    assert resp.status_code == 200
    body = resp.json()

    # The §5.5 shape.
    for key in (
        "gold_count",
        "n_runs",
        "macro_f1",
        "hallucination_rate",
        "routing_accuracy",
        "rows",
        "cost",
        "caption",
    ):
        assert key in body, key

    assert body["hallucination_rate"] == 0.0  # the all-correct stub set
    assert body["macro_f1"] == 1.0
    assert body["rows"]  # non-empty per-field rows
    assert body["caption"]
    assert all({"name", "p", "r", "f1", "note"} <= set(row) for row in body["rows"])
    assert all({"model", "f1", "usd_per_doc"} <= set(c) for c in body["cost"])


def test_eval_deterministic(client: TestClient) -> None:
    first = client.get("/api/eval").json()
    second = client.get("/api/eval").json()
    assert first == second
